from gateway.evals.run_evals import evaluate_policy, load_cases


def test_representative_incident_evaluation_suite():
    cases = load_cases()

    assert len(cases) >= 3
    assert evaluate_policy(cases) == []
