# third-party
from google.genai import types

open_circuit_decl = types.FunctionDeclaration(
    name="open_circuit",
    description="Opens the circuit breaker for an upstream service, immediately blocking all traffic to it. Use when error rate is high and you need to stop traffic fast.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Full upstream URL e.g. http://localhost:9091",
            ),
        },
        required=["upstream_url"],
    ),
)

get_upstream_state_decl = types.FunctionDeclaration(
    name="get_upstream_state",
    description="Returns current state of an upstream including CB state, health, failure count etc. Always call this first to understand the system state before making any changes",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Full upstream URL e.g. http://localhost:9091",
            )
        },
        required=["upstream_url"],
    ),
)

close_circuit_decl = types.FunctionDeclaration(
    name="close_circuit",
    description="Closes the circuit breaker for an upstream service, allowing traffic to resume",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Full upstream URL e.g. http://localhost:9091",
            )
        },
        required=["upstream_url"],
    ),
)

drain_upstream_decl = types.FunctionDeclaration(
    name="drain_upstream",
    description="Completely opens circuit and marks as drained (no auto-recovery)",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Full upstream URL e.g. http://localhost:9091",
            )
        },
        required=["upstream_url"],
    ),
)

mark_resolved_decl = types.FunctionDeclaration(
    name="mark_resolved",
    description="Signals the agent that healing is complete",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Full upstream URL e.g. http://localhost:9091",
            ),
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Reason for resolving",
            ),
        },
        required=["upstream_url", "reason"],
    ),
)

REMEDIATION_TOOLS = types.Tool(
    function_declarations=[
        get_upstream_state_decl,
        open_circuit_decl,
        close_circuit_decl,
        drain_upstream_decl,
        mark_resolved_decl,
    ]
)
