# local
from gateway.agent.incident_policy import IncidentPolicy


def test_incident_policy_classifies_first_failure():
    assessment = IncidentPolicy().assess([])

    assert assessment.classification == "first_failure"
    assert assessment.recommended_action == "open_circuit"
    assert assessment.needs_human_review is False


def test_incident_policy_escalates_repeated_failures():
    events = [
        {"event_type": "health_failed"},
        {"event_type": "upstream_request_failed"},
        {"event_type": "healing_completed"},
    ]

    assessment = IncidentPolicy().assess(events)

    assert assessment.classification == "repeated_failure"
    assert assessment.recommended_action == "drain_upstream"
    assert assessment.needs_human_review is True
