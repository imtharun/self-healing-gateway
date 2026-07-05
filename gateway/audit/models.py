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
    actions_taken: list[str] = Field(default_factory=list)
