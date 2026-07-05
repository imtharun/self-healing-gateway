# built-in
import asyncio

# third-party
import httpx


class HealthMonitor:
    def __init__(self, routes: list, interval: int = 10):
        self.routes = routes
        self.health_status: dict[str, bool] = {}
        self.interval = interval

    async def check_once(self) -> None:
        """
        Check health of all upstreams once.
        """
        async with httpx.AsyncClient(timeout=5.0) as client:
            results = await asyncio.gather(
                *[self._check_route(client, route) for route in self.routes]
            )

        self.health_status.update(results)

    async def _check_route(self, client: httpx.AsyncClient, route: dict) -> tuple[str, bool]:
        upstream_url = route["upstream_url"]
        health_url = upstream_url + route["health_check"]

        try:
            res = await client.get(health_url)
            return upstream_url, res.status_code == 200
        except httpx.HTTPError:
            return upstream_url, False

    async def start(self) -> None:
        """
        Run health checks forever in the background.
        """
        while True:
            await self.check_once()
            await asyncio.sleep(self.interval)
