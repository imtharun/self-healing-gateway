# built-in
import re
import uuid
from datetime import datetime

# third-party
from pydantic import BaseModel, Field, field_validator

# local
from gateway.time_utils import now_ist


class UpstreamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=48)
    path: str = Field(min_length=5, max_length=160)
    upstream_url: str = Field(min_length=8, max_length=500)
    health_check: str = Field(default="/health", min_length=1, max_length=160)
    failure_threshold: int = Field(default=5, ge=1, le=20)
    recovery_timeout: int = Field(default=30, ge=5, le=3600)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", normalized):
            raise ValueError("Name must use lowercase letters, numbers, and hyphens")
        return normalized

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        normalized = "/" + value.strip().strip("/")
        if not re.fullmatch(r"/api/[a-z0-9][a-z0-9/_-]*", normalized):
            raise ValueError("Path must start with /api/ and use URL-safe characters")
        return normalized

    @field_validator("health_check")
    @classmethod
    def validate_health_check(cls, value: str) -> str:
        normalized = "/" + value.strip().strip("/")
        if "?" in normalized or "#" in normalized:
            raise ValueError("Health-check path cannot contain a query or fragment")
        return normalized


class ManagedUpstream(UpstreamCreate):
    upstream_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=now_ist)
    managed: bool = True

    def as_route(self) -> dict:
        return self.model_dump(mode="json")
