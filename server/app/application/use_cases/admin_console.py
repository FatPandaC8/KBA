"""Business operations used by the admin console.

The HTTP layer only validates input and maps DTOs. All cross-table reads and
destructive operations live here so the admin UI cannot bypass ownership
scoping or the existing capture/account deletion rules. This module owns NO
SQL (ADR R8): direct reads/writes go through ``admin_repo`` (Postgres adapter).
"""

import os
from typing import Any, Dict, Optional

from server.app.domain.entities import UserEntity
from server.app.security import hash_password, normalize_email, validate_password
from server.app.domain.errors import ValidationError


class AdminConsoleUseCase:
    """Admin surface on capture-truth only (pipeline split): no job table,
    no worker process. Reads stay in the read port (this module owns NO SQL,
    ADR R8); rerun-extraction re-points to the Text-KB port (addendum rule 2).
    """

    def __init__(self, admin_repo, auth_service, user_repo, account_delete,
                 capture_delete, entity_repo, ingestor, upload_dir,
                 password_min_length):
        self.admin_repo = admin_repo
        self.auth_service = auth_service
        self.user_repo = user_repo
        self.account_delete = account_delete
        self.capture_delete = capture_delete
        self.entity_repo = entity_repo
        # Text-KB port (addendum rule 2): rerun-extraction re-points here.
        self.ingestor = ingestor
        self.upload_dir = upload_dir
        self.password_min_length = password_min_length

    def overview(self) -> Dict[str, Any]:
        data = self.admin_repo.overview_counts()
        data.update(self.admin_repo.overview_sections())
        return data

    def users(self, q: str, limit: int, offset: int) -> Dict[str, Any]:
        return self.admin_repo.users_page(q, limit, offset)

    def create_user(self, email: str, password: str) -> Dict[str, Any]:
        normalized = normalize_email(email)
        error = validate_password(password, self.password_min_length)
        if error:
            raise ValidationError(error)
        if self.user_repo.get_by_email(normalized):
            raise ValidationError("A user with that email already exists.")
        user = UserEntity.create(normalized, hash_password(password))
        user.email_verified_at = user.created_at
        self.user_repo.save(user)
        # R3: same self-entity gate as signup (atomic upsert in the adapter).
        self.entity_repo.get_or_create_self(user.id)
        return self._user(user.id)

    def _user(self, user_id: str) -> Dict[str, Any]:
        row = self.admin_repo.user_row(user_id)
        if not row:
            raise KeyError(user_id)
        return row

    def update_user(self, user_id: str, email: str) -> Dict[str, Any]:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            raise KeyError(user_id)
        normalized = normalize_email(email)
        other = self.user_repo.get_by_email(normalized)
        if other and other.id != user_id:
            raise ValidationError("A user with that email already exists.")
        user.email = normalized
        user.email_normalized = normalized
        self.user_repo.update(user)
        return self._user(user_id)

    def user_detail(self, user_id: str) -> Dict[str, Any]:
        data = self._user(user_id)
        data.update(self.admin_repo.user_detail_sections(user_id))
        return data

    def delete_user(self, user_id: str) -> Dict[str, Any]:
        if not self.user_repo.get_by_id(user_id):
            raise KeyError(user_id)
        return self.account_delete.execute(user_id)

    def captures(self, q: str, user_id: str, status: str, limit: int, offset: int) -> Dict[str, Any]:
        return self.admin_repo.captures_page(q, user_id, status, limit, offset)

    def capture(self, capture_id: str) -> Optional[Dict[str, Any]]:
        return self.admin_repo.capture_detail(capture_id)

    def update_transcript(self, capture_id: str, transcript: str) -> Dict[str, Any]:
        self.admin_repo.update_transcript(capture_id, transcript)
        return self.capture(capture_id) or {}

    def rerun_extraction(self, capture_id: str) -> Dict[str, Any]:
        """Re-run Text-KB from the stored transcript (addendum rule 2).

        Synchronous inside the request and idempotent on capture_id — the
        existing capture/story rows are reused by the ingest port, so a rerun
        can only change the graph output of that capture, never duplicate it.
        """
        capture = self.capture(capture_id)
        if not capture or not capture.get("knowledge_item"):
            raise KeyError(capture_id)
        user_id = capture["user_id"]
        transcript = capture["knowledge_item"].get("transcript") or ""
        if not transcript.strip():
            raise ValidationError("A transcript is required before extraction.")
        result = self.ingestor.ingest(user_id, capture_id, transcript)
        data = self.capture(capture_id) or {}
        data["replacement_counts"] = {
            "entities": result.entities_added,
            "relationships": result.relationships_added,
        }
        return data

    def delete_capture(self, capture_id: str) -> Dict[str, Any]:
        capture = self.capture(capture_id)
        if not capture:
            raise KeyError(capture_id)
        return self.capture_delete.execute(capture_id, capture["user_id"])

    def graph_entities(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        return self.admin_repo.graph_entities_page(q, user_id, limit, offset)

    def graph_relationships(self, q: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        return self.admin_repo.graph_relationships_page(q, user_id, limit, offset)

    def audit(self, action: str, user_id: str, limit: int, offset: int) -> Dict[str, Any]:
        return self.admin_repo.audit_page(action, user_id, limit, offset)
