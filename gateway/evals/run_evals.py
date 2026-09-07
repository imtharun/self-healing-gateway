# built-in
import argparse
import asyncio
import json
import os
from pathlib import Path

# third-party
from google import genai
from pydantic import BaseModel

# local
from gateway.agent.incident_policy import IncidentPolicy

FIXTURES_PATH = Path(__file__).with_name("incidents.json")


class ModelDecision(BaseModel):
    classification: str
    recommended_action: str
    needs_human_review: bool


def load_cases() -> list[dict]:
    return json.loads(FIXTURES_PATH.read_text())


def evaluate_policy(cases: list[dict]) -> list[str]:
    failures = []
    policy = IncidentPolicy()
    for case in cases:
        result = policy.assess(case["events"])
        actual = (
            result.classification,
            result.recommended_action,
            result.needs_human_review,
        )
        expected = (
            case["expected_classification"],
            case["expected_action"],
            case["expected_human_review"],
        )
        if actual != expected:
            failures.append(f"{case['name']}: expected {expected}, received {actual}")
    return failures


async def evaluate_gemini(cases: list[dict]) -> list[str]:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return ["GEMINI_API_KEY is required for --live"]
    client = genai.Client(api_key=api_key)
    failures = []
    for case in cases:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=(
                "Classify this gateway incident and recommend exactly one action. "
                "Allowed classifications: first_failure, flapping_service, "
                "repeated_failure. Allowed actions: open_circuit, drain_upstream. "
                f"Events: {json.dumps(case['events'])}"
            ),
            config={
                "response_mime_type": "application/json",
                "response_schema": ModelDecision,
                "temperature": 0,
            },
        )
        decision = response.parsed
        expected = (
            case["expected_classification"],
            case["expected_action"],
            case["expected_human_review"],
        )
        actual = (
            decision.classification,
            decision.recommended_action,
            decision.needs_human_review,
        )
        if actual != expected:
            failures.append(f"{case['name']}: policy {expected}, Gemini {actual}")
    return failures


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Compare Gemini to policy")
    args = parser.parse_args()
    cases = load_cases()
    failures = evaluate_policy(cases)
    if args.live:
        failures.extend(await evaluate_gemini(cases))
    if failures:
        print("\n".join(failures))
        return 1
    mode = "policy and Gemini" if args.live else "deterministic policy"
    print(f"{len(cases)} incident evaluations passed for {mode}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
