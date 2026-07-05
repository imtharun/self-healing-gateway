# built-in
# third_party
import asyncio
import uuid
from datetime import datetime

# local
from gateway.agent.gemini_agent import run_healing_session
from gateway.audit.models import HealingSession
from gateway.audit.store import save_session


class FailureDetector:
    def __init__(self, health_monitor, cb_registry, interval=15):
        self.health_monitor = health_monitor
        self.cb_registry = cb_registry
        self.interval = interval
        self.previous_status = {}  # tracks previous state
        self.healing_in_progress = set()  # prevents duplicate sessions

    async def start(self):
        while True:
            for upstream_url, is_healthy in self.health_monitor.health_status.items():
                was_healthy = self.previous_status.get(upstream_url, True)
                print(
                    f"🔍 {upstream_url}: was_healthy={was_healthy}, is_healthy={is_healthy}"
                )

                if was_healthy and not is_healthy:
                    print(
                        f"🚨 Failure detected on {upstream_url}! Triggering healer..."
                    )
                    if upstream_url not in self.healing_in_progress:
                        self.healing_in_progress.add(upstream_url)
                        asyncio.create_task(self._heal(upstream_url))

            self.previous_status = dict(self.health_monitor.health_status)
            await asyncio.sleep(self.interval)

    async def _heal(self, upstream_url):
        try:
            session_id = str(uuid.uuid4())
            triggered_at = datetime.now()

            result = await run_healing_session(
                upstream_url=upstream_url,
                context="Sudden failure noticed in the upstream",
                cb_registry=self.cb_registry,
                health_monitor=self.health_monitor,
            )

            session: HealingSession = HealingSession(
                session_id=session_id,
                upstream_url=result["upstream_url"],
                triggered_at=triggered_at,
                resolved_at=datetime.now(),
                status=result.get("status", ""),
                reason=result.get("reason", ""),
                actions_taken=result.get("actions_taken", []),
            )

            await save_session(session=session)
        except Exception as e:
            print(f"❌ Healing failed for {upstream_url}: {e}")
        finally:
            self.healing_in_progress.discard(upstream_url)
