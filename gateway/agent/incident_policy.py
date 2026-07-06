# built-in
from dataclasses import dataclass


@dataclass(frozen=True)
class IncidentAssessment:
    classification: str
    recommended_action: str
    operator_guidance: str
    repeated_failures: int
    needs_human_review: bool


class IncidentPolicy:
    def __init__(self, repeated_failure_threshold: int = 3):
        self.repeated_failure_threshold = repeated_failure_threshold

    def assess(self, recent_events: list[dict]) -> IncidentAssessment:
        failure_events = [
            event
            for event in recent_events
            if event.get("event_type")
            in {"health_failed", "upstream_request_failed", "healing_completed"}
        ]
        repeated_failures = len(failure_events)

        if repeated_failures >= self.repeated_failure_threshold:
            return IncidentAssessment(
                classification="repeated_failure",
                recommended_action="drain_upstream",
                operator_guidance="Inspect service logs and dependencies before restoring traffic.",
                repeated_failures=repeated_failures,
                needs_human_review=True,
            )

        if repeated_failures >= 2:
            return IncidentAssessment(
                classification="flapping_service",
                recommended_action="open_circuit",
                operator_guidance="Keep traffic isolated and inspect recent deploys or dependencies.",
                repeated_failures=repeated_failures,
                needs_human_review=True,
            )

        return IncidentAssessment(
            classification="first_failure",
            recommended_action="open_circuit",
            operator_guidance="Open the circuit and monitor health recovery.",
            repeated_failures=repeated_failures,
            needs_human_review=False,
        )
