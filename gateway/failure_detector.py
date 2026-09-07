# built-in
import asyncio
import logging
import uuid

# local
from gateway.agent.gemini_agent import run_healing_session
from gateway.agent.incident_policy import IncidentPolicy
from gateway.audit.models import HealingSession
from gateway.audit.store import get_events, record_event, save_session
from gateway.observability import healing_sessions
from gateway.time_utils import now_ist

logger = logging.getLogger("gateway.failure_detector")


class FailureDetector:
    def __init__(
        self,
        health_monitor,
        cb_registry,
        interval=15,
        unhealthy_event_interval=60,
    ):
        self.health_monitor = health_monitor
        self.cb_registry = cb_registry
        self.interval = interval
        self.unhealthy_event_interval = unhealthy_event_interval
        self.previous_status = {}  # tracks previous state
        self.last_unhealthy_event_at = {}
        self.healing_in_progress = set()  # prevents duplicate sessions
        self.incident_policy = IncidentPolicy()

    async def start(self):
        while True:
            await self.check_once()
            await asyncio.sleep(self.interval)

    async def check_once(self):
        for upstream_url, is_healthy in self.health_monitor.health_status.items():
            was_healthy = self.previous_status.get(upstream_url, True)

            if was_healthy and not is_healthy:
                logger.warning(
                    "Upstream failure detected; starting healing session",
                    extra={"upstream_url": upstream_url},
                )
                await record_event(
                    event_type="health_failed",
                    upstream_url=upstream_url,
                    message=f"Health check failed for {upstream_url}.",
                )
                self.last_unhealthy_event_at[upstream_url] = now_ist()
                if upstream_url not in self.healing_in_progress:
                    self.healing_in_progress.add(upstream_url)
                    asyncio.create_task(self._heal(upstream_url))

            elif not is_healthy:
                await self._record_still_unhealthy_if_due(upstream_url)

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

    async def _record_still_unhealthy_if_due(self, upstream_url):
        now = now_ist()
        last_recorded_at = self.last_unhealthy_event_at.get(upstream_url)
        if (
            last_recorded_at
            and (now - last_recorded_at).total_seconds()
            < self.unhealthy_event_interval
        ):
            return

        self.last_unhealthy_event_at[upstream_url] = now
        cb = self.cb_registry.get(upstream_url)
        circuit_state = cb.current_state.value if cb else "UNKNOWN"
        await record_event(
            event_type="health_still_unhealthy",
            upstream_url=upstream_url,
            message=(
                f"{upstream_url} is still failing health checks; "
                f"circuit remains {circuit_state}."
            ),
            metadata={"circuit_state": circuit_state},
        )

    async def _heal(self, upstream_url):
        try:
            session_id = str(uuid.uuid4())
            triggered_at = now_ist()
            recent_events = await get_events(limit=10, upstream_url=upstream_url)
            assessment = self.incident_policy.assess(recent_events)

            result = await run_healing_session(
                upstream_url=upstream_url,
                context={
                    "trigger": "health_check_failed",
                    "incident_assessment": {
                        "classification": assessment.classification,
                        "recommended_action": assessment.recommended_action,
                        "operator_guidance": assessment.operator_guidance,
                        "repeated_failures": assessment.repeated_failures,
                        "needs_human_review": assessment.needs_human_review,
                    },
                    "recent_events": recent_events,
                },
                cb_registry=self.cb_registry,
                health_monitor=self.health_monitor,
            )
            healing_sessions.add(
                1,
                {
                    "upstream.url": upstream_url,
                    "status": result.get("status", "unknown"),
                },
            )

            session: HealingSession = HealingSession(
                session_id=session_id,
                upstream_url=result["upstream_url"],
                triggered_at=triggered_at,
                resolved_at=now_ist(),
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
            logger.exception(
                "Healing session failed", extra={"upstream_url": upstream_url}
            )
        finally:
            self.healing_in_progress.discard(upstream_url)
