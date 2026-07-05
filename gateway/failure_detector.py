# built-in
import asyncio
import logging
import uuid
from datetime import datetime

# local
from gateway.agent.gemini_agent import run_healing_session
from gateway.audit.models import HealingSession
from gateway.audit.store import record_event, save_session

logger = logging.getLogger("gateway.failure_detector")


class FailureDetector:
    def __init__(self, health_monitor, cb_registry, interval=15):
        self.health_monitor = health_monitor
        self.cb_registry = cb_registry
        self.interval = interval
        self.previous_status = {}  # tracks previous state
        self.healing_in_progress = set()  # prevents duplicate sessions

    async def start(self):
        while True:
            await self.check_once()
            await asyncio.sleep(self.interval)

    async def check_once(self):
        for upstream_url, is_healthy in self.health_monitor.health_status.items():
            was_healthy = self.previous_status.get(upstream_url, True)

            if was_healthy and not is_healthy:
                logger.warning(
                    f"🚨 Failure detected on {upstream_url}! Triggering healer..."
                )
                await record_event(
                    event_type="health_failed",
                    upstream_url=upstream_url,
                    message=f"Health check failed for {upstream_url}.",
                )
                if upstream_url not in self.healing_in_progress:
                    self.healing_in_progress.add(upstream_url)
                    asyncio.create_task(self._heal(upstream_url))

            elif is_healthy:
                cb = self.cb_registry.get(upstream_url)

                if cb and cb.can_try_recovery():
                    logger.info(
                        "%s health check recovered; allowing trial traffic.",
                        upstream_url,
                    )
                    cb.mark_half_open()
                    await record_event(
                        event_type="circuit_half_open",
                        upstream_url=upstream_url,
                        message=(
                            f"Health check recovered for {upstream_url}; "
                            "trial traffic is allowed."
                        ),
                        metadata={"circuit_state": cb.current_state.value},
                    )

        self.previous_status = dict(self.health_monitor.health_status)

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
                suspected_cause=result.get("suspected_cause"),
                action_taken=result.get("action_taken"),
                operator_next_step=result.get("operator_next_step"),
                actions_taken=result.get("actions_taken", []),
            )

            await save_session(session=session)
            await record_event(
                event_type="healing_completed",
                upstream_url=session.upstream_url,
                message=session.reason or "Healing session completed.",
                metadata={
                    "status": session.status,
                    "suspected_cause": session.suspected_cause,
                    "action_taken": session.action_taken,
                    "operator_next_step": session.operator_next_step,
                    "actions_taken": session.actions_taken,
                },
            )
        except Exception:
            import traceback

            logger.error(
                f"❌ Healing failed for {upstream_url}:\n{traceback.format_exc()}"
            )
        finally:
            self.healing_in_progress.discard(upstream_url)
