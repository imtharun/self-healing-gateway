# built-in
from datetime import datetime

# third-party
from pydantic import BaseModel, Field


class HealingSession(BaseModel):
    session_id: str
    upstream_url: str
    triggered_at: datetime
    resolved_at: datetime | None = None
    status: str
    reason: str | None = None
    suspected_cause: str | None = None
    action_taken: str | None = None
    operator_next_step: str | None = None
    actions_taken: list[str] = Field(default_factory=list)


class GatewayEvent(BaseModel):
    event_id: str
    event_type: str
    upstream_url: str | None = None
    occurred_at: datetime
    message: str
    metadata: dict = Field(default_factory=dict)
