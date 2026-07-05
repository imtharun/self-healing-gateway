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
        for route in self.routes:
            upstream_url = route["upstream_url"]
            health_url = upstream_url + route["health_check"]

            try:
                res = None
                async with httpx.AsyncClient() as client:
                    res = await client.get(health_url)

                self.health_status[upstream_url] = res.status_code == 200
            except Exception:
                self.health_status[upstream_url] = False

    async def start(self) -> None:
        """
        Run health checks forever in the background.
        """
        while True:
            await self.check_once()
            await asyncio.sleep(self.interval)
