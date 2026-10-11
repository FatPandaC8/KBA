"""Administrative routes: users, roles, status, audit."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.admin_service import change_role, change_status, create_user, list_audit, list_users
from app.auth import get_current_user
from app.models import User
from app.schemas import (
    AuditEventOut,
    RoleChangeIn,
    StatusChangeIn,
    UserAdminOut,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/users", response_model=list[UserAdminOut])
def get_users(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return list_users(db, admin)


@router.post("/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
def post_user(
    username: str,
    password: str,
    display_name: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return create_user(db, admin, username, password, display_name)


@router.put("/users/{user_id}/role")
def put_role(
    user_id: str,
    body: RoleChangeIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = change_role(db, admin, user_id, body.role, body.reason)
    return {"id": target.id, "role": target.role}


@router.put("/users/{user_id}/status")
def put_status(
    user_id: str,
    body: StatusChangeIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = change_status(db, admin, user_id, body.status, body.reason)
    return {"id": target.id, "status": target.status}


@router.get("/audit-events", response_model=list[AuditEventOut])
def get_audit(
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    return list_audit(db, admin, limit=limit)
