"""Pydantic schemas for API requests/responses."""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator


class TokenOut(BaseModel):
    access_token: str


class LoginIn(BaseModel):
    username: str
    password: str


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    role: str
    status: str
    created_at: datetime


class UserAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    username: str
    display_name: Optional[str] = None
    role: str
    status: str
    created_at: datetime


class RoleChangeIn(BaseModel):
    role: str
    reason: Optional[str] = None

    @field_validator("role")
    @classmethod
    def _role(cls, v: str) -> str:
        if v not in ("user", "admin"):
            raise ValueError("role must be 'user' or 'admin'")
        return v


class StatusChangeIn(BaseModel):
    status: str
    reason: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in ("active", "disabled"):
            raise ValueError("status must be 'active' or 'disabled'")
        return v


class AuditEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    actor_user_id: str
    action: str
    target_user_id: Optional[str] = None
    outcome: str
    reason: Optional[str] = None
    created_at: datetime


class NoteIn(BaseModel):
    content: str
    idempotency_key: Optional[str] = None


class NotePatchIn(BaseModel):
    content: str


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    content: str
    capture_type: str
    status: str
    content_version: int
    created_at: datetime
    updated_at: datetime
