# built-in
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

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


def execute_tool(fn_name: str, fn_args: dict, cb_registry, health_monitor) -> dict:
    if fn_name == "open_circuit":
        return open_circuit(
            upstream_url=fn_args["upstream_url"], cb_registry=cb_registry
        )
    elif fn_name == "close_circuit":
        return close_circuit(
            upstream_url=fn_args["upstream_url"], cb_registry=cb_registry
        )
    elif fn_name == "get_upstream_state":
        return get_upstream_state(
            upstream_url=fn_args["upstream_url"],
            cb_registry=cb_registry,
            health_monitor=health_monitor,
        )
    elif fn_name == "drain_upstream":
        return drain_upstream(
            upstream_url=fn_args["upstream_url"], cb_registry=cb_registry
        )
    elif fn_name == "mark_resolved":
        return mark_resolved(
            upstream_url=fn_args["upstream_url"], reason=fn_args["reason"]
        )


async def run_healing_session(
    upstream_url: str,
    context: dict,  # failure context: error rate, latency etc
    cb_registry: dict,
    health_monitor,
) -> dict:

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
                print(f"Gemini: {part.text}")
            if part.function_call:
                # calling tool
                fn_name = part.function_call.name  # eg open_circuit
                fn_args = dict(part.function_call.args)  # eg {"upstream_url": "..."}

                print(f"Tool call: {fn_name}")
                actions_taken.append(fn_name)

                result = execute_tool(fn_name, fn_args, cb_registry, health_monitor)

                # If agent called mark_resolved → STOP
                if fn_name == "mark_resolved":
                    result["actions_taken"] = actions_taken
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
        "actions_taken": actions_taken,
    }
