# built-in
import logging
import os

# third-party
from dotenv import load_dotenv
from google import genai
from google.genai import types

# local
from gateway.agent.prompts import SYSTEM_PROMPT
from gateway.agent.tool_registry import REMEDIATION_TOOLS
from gateway.agent.tools import (
    close_circuit,
    drain_upstream,
    get_upstream_state,
    mark_resolved,
    open_circuit,
)

load_dotenv()

logger = logging.getLogger("gateway.agent")


def _get_client() -> genai.Client | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        logger.warning("GEMINI_API_KEY is not set; skipping healing session")
        return None
    return genai.Client(api_key=api_key)


def _validate_upstream(upstream_url: str, cb_registry: dict) -> str:
    if upstream_url not in cb_registry:
        raise ValueError(f"Upstream is not registered: {upstream_url}")
    return upstream_url


def execute_tool(fn_name: str, fn_args: dict, cb_registry, health_monitor) -> dict:
    upstream_url = _validate_upstream(fn_args.get("upstream_url", ""), cb_registry)

    if fn_name == "open_circuit":
        return open_circuit(upstream_url=upstream_url, cb_registry=cb_registry)
    elif fn_name == "close_circuit":
        return close_circuit(upstream_url=upstream_url, cb_registry=cb_registry)
    elif fn_name == "get_upstream_state":
        return get_upstream_state(
            upstream_url=upstream_url,
            cb_registry=cb_registry,
            health_monitor=health_monitor,
        )
    elif fn_name == "drain_upstream":
        return drain_upstream(upstream_url=upstream_url, cb_registry=cb_registry)
    elif fn_name == "mark_resolved":
        reason = fn_args.get("reason") or "No reason provided by agent"
        return mark_resolved(
            upstream_url=upstream_url,
            reason=reason,
            suspected_cause=fn_args.get("suspected_cause"),
            action_taken=fn_args.get("action_taken"),
            operator_next_step=fn_args.get("operator_next_step"),
        )

    raise ValueError(f"Unsupported remediation tool: {fn_name}")


async def run_healing_session(
    upstream_url: str,
    context: dict | str,  # failure context: error rate, latency etc
    cb_registry: dict,
    health_monitor,
) -> dict:
    client = _get_client()
    if client is None:
        return {
            "status": "skipped",
            "upstream_url": upstream_url,
            "reason": "GEMINI_API_KEY is not configured",
            "actions_taken": [],
        }

    try:
        _validate_upstream(upstream_url, cb_registry)
    except ValueError as exc:
        return {
            "status": "rejected",
            "upstream_url": upstream_url,
            "reason": str(exc),
            "actions_taken": [],
        }

    # start with initial failure message
    initial_message = f"""
    Failure detected on upstream: {upstream_url}
    Context: {context}
    Please diagnose and remediate
    """
    actions_taken = []

    messages = [types.Content(role="user", parts=[types.Part(text=initial_message)])]

    iterations, max_iterations = 0, 6

    while iterations < max_iterations:
        response = await client.aio.models.generate_content(
            model="gemini-2.5-flash",
            contents=messages,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[REMEDIATION_TOOLS],
            ),
        )

        # Add Gemini's response to conversation history
        messages.append(response.candidates[0].content)

        # Check what Gemini returned
        for part in response.candidates[0].content.parts:
            if part.text:
                logger.info("Gemini response: %s", part.text)
            if part.function_call:
                # calling tool
                fn_name = part.function_call.name  # eg open_circuit
                fn_args = dict(part.function_call.args)  # eg {"upstream_url": "..."}

                logger.info("Gemini tool call: %s", fn_name)
                actions_taken.append(fn_name)

                try:
                    result = execute_tool(
                        fn_name, fn_args, cb_registry, health_monitor
                    )
                except ValueError as exc:
                    logger.warning("Rejected Gemini tool call: %s", exc)
                    return {
                        "status": "rejected",
                        "upstream_url": upstream_url,
                        "reason": str(exc),
                        "actions_taken": actions_taken,
                    }

                # If agent called mark_resolved → STOP
                if fn_name == "mark_resolved":
                    result["actions_taken"] = actions_taken
                    if not result.get("reason"):
                        result["reason"] = "Gemini did not provide a healing summary."
                    return result

                # send tool back to Gemini
                messages.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    name=fn_name, response={"result": result}
                                )
                            )
                        ],
                    )
                )

        iterations += 1

    return {
        "status": "max_iteration_reached",
        "upstream_url": upstream_url,
        "reason": "Gemini did not complete the healing summary before the iteration limit.",
        "actions_taken": actions_taken,
    }
