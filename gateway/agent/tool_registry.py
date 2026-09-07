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
                description="Registered upstream URL, for example https://api.example.com",
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
                description="Registered upstream URL, for example https://api.example.com",
            )
        },
        required=["upstream_url"],
    ),
)

get_recent_events_decl = types.FunctionDeclaration(
    name="get_recent_events",
    description=(
        "Returns recent gateway events for an upstream so the agent can detect "
        "first failures, flapping services, or repeated failures before acting."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Registered upstream URL, for example https://api.example.com",
            ),
            "limit": types.Schema(
                type=types.Type.INTEGER,
                description="Maximum number of recent events to retrieve.",
            ),
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
                description="Registered upstream URL, for example https://api.example.com",
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
                description="Registered upstream URL, for example https://api.example.com",
            )
        },
        required=["upstream_url"],
    ),
)

create_incident_ticket_decl = types.FunctionDeclaration(
    name="create_incident_ticket",
    description="Requests creation of an external incident ticket. This requires human approval before the webhook is called.",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(type=types.Type.STRING),
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Concise evidence-based reason for creating the incident.",
            ),
            "severity": types.Schema(
                type=types.Type.STRING,
                enum=["medium", "high", "critical"],
            ),
        },
        required=["upstream_url", "reason", "severity"],
    ),
)

mark_resolved_decl = types.FunctionDeclaration(
    name="mark_resolved",
    description="Ends the healing session with a concise dashboard-ready summary of what happened and what was done",
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "upstream_url": types.Schema(
                type=types.Type.STRING,
                description="Registered upstream URL, for example https://api.example.com",
            ),
            "reason": types.Schema(
                type=types.Type.STRING,
                description=(
                    "One concise operator-ready sentence, 12-25 words. Include "
                    "observed signal, remediation performed, and current traffic impact. "
                    "Do not use raw tool names or vague phrases."
                ),
            ),
            "suspected_cause": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Short suspected cause based on observed gateway data. Use "
                    "'unknown' if there is not enough evidence."
                ),
            ),
            "action_taken": types.Schema(
                type=types.Type.STRING,
                description=(
                    "Short plain-English remediation action, e.g. opened circuit, "
                    "closed circuit, drained upstream, or monitored only."
                ),
            ),
            "operator_next_step": types.Schema(
                type=types.Type.STRING,
                description=(
                    "One short recommended next step for a human operator. Use "
                    "'No immediate action needed' when appropriate."
                ),
            ),
        },
        required=[
            "upstream_url",
            "reason",
            "suspected_cause",
            "action_taken",
            "operator_next_step",
        ],
    ),
)

REMEDIATION_TOOLS = types.Tool(
    function_declarations=[
        get_upstream_state_decl,
        get_recent_events_decl,
        open_circuit_decl,
        close_circuit_decl,
        drain_upstream_decl,
        create_incident_ticket_decl,
        mark_resolved_decl,
    ]
)
