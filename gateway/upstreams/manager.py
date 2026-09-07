# built-in
import asyncio
from contextlib import asynccontextmanager

# local
from gateway.audit.store import (
    delete_upstream,
    record_event,
    save_upstream,
    update_upstream,
)
from gateway.resilience.circuit_breaker import CircuitBreaker
from gateway.router import route_matches
from gateway.upstreams.models import ManagedUpstream


class UpstreamConflictError(ValueError):
    pass


class UpstreamNotFoundError(ValueError):
    pass


class UpstreamManager:
    def __init__(self, static_routes: list[dict], managed_routes: list[dict]):
        self._condition = asyncio.Condition()
        self._active_requests: dict[str, int] = {}
        self._draining_routes: dict[str, dict] = {}
        self.health_monitor = None
        self.routes = [self._static_route(route) for route in static_routes]
        self.routes.extend(self._managed_route(route) for route in managed_routes)
        self.cb_registry = {
            route["upstream_url"]: self._build_breaker(route) for route in self.routes
        }

    @staticmethod
    def _static_route(route: dict) -> dict:
        path = route["path"].rstrip("/")
        return {
            **route,
            "upstream_id": f"config:{path}",
            "name": route.get("name") or path.rsplit("/", 1)[-1],
            "failure_threshold": route.get("failure_threshold", 5),
            "recovery_timeout": route.get("recovery_timeout", 30),
            "managed": False,
        }

    @staticmethod
    def _managed_route(route: dict) -> dict:
        return {**route, "managed": True}

    @staticmethod
    def _build_breaker(route: dict) -> CircuitBreaker:
        return CircuitBreaker(
            name=route["name"],
            failure_threshold=route.get("failure_threshold", 5),
            recovery_timeout=route.get("recovery_timeout", 30),
        )

    def attach_monitor(self, monitor) -> None:
        self.health_monitor = monitor
        self._sync_monitor_routes()

    def _sync_monitor_routes(self) -> None:
        if self.health_monitor is not None:
            self.health_monitor.routes = list(self.routes)

    def list_upstreams(self) -> list[dict]:
        return [dict(route) for route in self.routes]

    def active_request_count(self, upstream_id: str) -> int:
        return self._active_requests.get(upstream_id, 0)

    def _assert_unique(self, candidate: dict, exclude_id: str | None = None) -> None:
        for route in [*self.routes, *self._draining_routes.values()]:
            if route["upstream_id"] == exclude_id:
                continue
            if route["name"] == candidate["name"]:
                raise UpstreamConflictError("An upstream with this name already exists")
            if route["path"] == candidate["path"]:
                raise UpstreamConflictError("An upstream with this route path already exists")
            if route["upstream_url"] == candidate["upstream_url"]:
                raise UpstreamConflictError("This upstream URL is already registered")

    async def add(self, upstream: ManagedUpstream) -> dict:
        route = upstream.as_route()
        async with self._condition:
            self._assert_unique(route)
            await save_upstream(upstream)
            self.routes.append(route)
            self.cb_registry[route["upstream_url"]] = self._build_breaker(route)
            self._sync_monitor_routes()

        await record_event(
            event_type="upstream_added",
            upstream_url=route["upstream_url"],
            message=f"Operator registered {route['name']} at {route['path']}.",
            metadata={"upstream_id": route["upstream_id"], "path": route["path"]},
        )
        return dict(route)

    async def update(self, upstream: ManagedUpstream) -> dict:
        replacement = upstream.as_route()
        upstream_id = replacement["upstream_id"]
        async with self._condition:
            current = next(
                (
                    route
                    for route in self.routes
                    if route["upstream_id"] == upstream_id and route["managed"]
                ),
                None,
            )
            if current is None:
                raise UpstreamNotFoundError("Managed upstream was not found")
            self._assert_unique(replacement, exclude_id=upstream_id)

            self.routes.remove(current)
            self._draining_routes[upstream_id] = current
            self._sync_monitor_routes()
            while self._active_requests.get(upstream_id, 0) > 0:
                await self._condition.wait()

            try:
                await update_upstream(upstream)
            except Exception:
                self._draining_routes.pop(upstream_id, None)
                self.routes.append(current)
                self._sync_monitor_routes()
                raise

            self.cb_registry.pop(current["upstream_url"], None)
            if self.health_monitor is not None:
                self.health_monitor.health_status.pop(current["upstream_url"], None)
            self.cb_registry[replacement["upstream_url"]] = self._build_breaker(
                replacement
            )
            self.routes.append(replacement)
            self._active_requests.pop(upstream_id, None)
            self._draining_routes.pop(upstream_id, None)
            self._sync_monitor_routes()

        await record_event(
            event_type="upstream_updated",
            upstream_url=replacement["upstream_url"],
            message=f"Operator updated {replacement['name']} at {replacement['path']}.",
            metadata={
                "upstream_id": upstream_id,
                "previous_url": current["upstream_url"],
                "previous_path": current["path"],
            },
        )
        return dict(replacement)

    async def remove(self, upstream_id: str) -> dict:
        async with self._condition:
            route = next(
                (
                    item
                    for item in self.routes
                    if item["upstream_id"] == upstream_id and item["managed"]
                ),
                None,
            )
            if route is None:
                raise UpstreamNotFoundError("Managed upstream was not found")

            self.routes.remove(route)
            self._draining_routes[upstream_id] = route
            self._sync_monitor_routes()
            while self._active_requests.get(upstream_id, 0) > 0:
                await self._condition.wait()

            try:
                await delete_upstream(upstream_id)
            except Exception:
                self._draining_routes.pop(upstream_id, None)
                self.routes.append(route)
                self._sync_monitor_routes()
                raise
            self.cb_registry.pop(route["upstream_url"], None)
            if self.health_monitor is not None:
                self.health_monitor.health_status.pop(route["upstream_url"], None)
            self._active_requests.pop(upstream_id, None)
            self._draining_routes.pop(upstream_id, None)

        await record_event(
            event_type="upstream_removed",
            upstream_url=route["upstream_url"],
            message=f"Operator removed {route['name']} from {route['path']}.",
            metadata={"upstream_id": upstream_id, "path": route["path"]},
        )
        return dict(route)

    @asynccontextmanager
    async def resolve(self, request_path: str):
        async with self._condition:
            route = next(
                (
                    item
                    for item in sorted(
                        self.routes, key=lambda value: len(value["path"]), reverse=True
                    )
                    if route_matches(item["path"], request_path)
                ),
                None,
            )
            if route is not None:
                upstream_id = route["upstream_id"]
                self._active_requests[upstream_id] = (
                    self._active_requests.get(upstream_id, 0) + 1
                )

        try:
            yield dict(route) if route else None
        finally:
            if route is not None:
                async with self._condition:
                    self._active_requests[upstream_id] -= 1
                    if self._active_requests[upstream_id] == 0:
                        self._condition.notify_all()
