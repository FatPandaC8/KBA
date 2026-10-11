"""Shared FastAPI dependencies."""
from fastapi import Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.db import get_db
from app.models import User

__all__ = ["get_db", "get_current_user", "require_admin"]
