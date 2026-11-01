"""Deterministic admin-console fixture seed.

Usage:
  E2E_SEED_ENABLED=true python -m server.tools.seed_admin seed
  E2E_SEED_ENABLED=true python -m server.tools.seed_admin reset --confirm-reset
"""

import argparse
import os
import uuid

from server.app.api.dependencies import get_container
from server.app.application.dto import ProcessingJobDTO
from server.app.domain.entities import CaptureEntity, EntityType, ExtractedEntity, KnowledgeItemEntity, RelationshipEntity, UserEntity, current_utc_iso
from server.app.domain.value_objects import JobStage, JobStatus
from server.app.security import hash_password

SEED = "echo-admin-v1"


def _id(label: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{SEED}:{label}"))


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SystemExit(f"Missing required environment variable: {name}")
    return value


def _guard() -> None:
    if os.getenv("E2E_SEED_ENABLED", "").lower() != "true":
        raise SystemExit("Refusing seed: set E2E_SEED_ENABLED=true")
    if os.getenv("ECHO_ENV", "development").lower() in {"production", "prod"}:
        raise SystemExit("Refusing seed in production")


def _register(container, record_type: str, record_id: str) -> None:
    container.db_manager.get_connection().execute(
        "INSERT OR IGNORE INTO admin_seed_registry(seed_name, record_type, record_id, created_at) VALUES (?, ?, ?, ?)",
        (SEED, record_type, record_id, current_utc_iso()),
    )


def seed() -> None:
    _guard()
    admin_email = _env("E2E_ADMIN_EMAIL")
    _env("E2E_ADMIN_PASSWORD")  # Existing shared-token auth remains authoritative.
    user_emails = [_env(f"E2E_USER_{i}_EMAIL") for i in range(1, 4)]
    passwords = [_env(f"E2E_USER_{i}_PASSWORD") for i in range(1, 4)]
    container = get_container()
    db = container.db_manager.get_connection()
    existing = db.execute("SELECT count(*) AS count FROM admin_seed_registry WHERE seed_name = ?", (SEED,)).fetchone()["count"]
    if existing:
        print("seed already present; no changes made")
        return
    _register(container, "admin_identity", admin_email)
    users = []
    for i, (email, password) in enumerate(zip(user_emails, passwords), start=1):
        if container.user_repo.get_by_email(email.lower()):
            raise SystemExit(f"Refusing to overwrite existing account: {email}")
        user = UserEntity(id=_id(f"user:{i}"), email=email, email_normalized=email.lower(), password_hash=hash_password(password), email_verified_at=current_utc_iso())
        container.user_repo.save(user); _register(container, "user", user.id); users.append(user)

    def capture(user, n: int, transcript: str, status: str = "ready") -> str:
        cid = _id(f"capture:{user.id}:{n}")
        container.capture_repo.save(CaptureEntity(id=cid, idempotency_key=cid, audio_path="", user_id=user.id, duration_ms=42000 + n * 7000, status=status))
        container.knowledge_repo.save(KnowledgeItemEntity.create(id=cid, capture_id=cid, title=f"Seed capture {n}", core_idea=transcript[:80], transcript=transcript, user_id=user.id))
        _register(container, "capture", cid)
        return cid

    c11 = capture(users[0], 1, "The Echo project depends on FastAPI and uses a private knowledge graph.")
    c12 = capture(users[0], 2, "The Echo project is being tested with the admin console and FastAPI.")
    c13 = capture(users[0], 3, "The team wants the knowledge graph to stay readable and useful.")
    c21 = capture(users[1], 1, "A separate user also works with FastAPI on a different project.")
    c22 = capture(users[1], 2, "The second project documents a small research workflow.")
    c31 = capture(users[2], 1, "This capture demonstrates a failed extraction job.", status="failed")
    now = current_utc_iso()
    def entity(user, capture_id, n, name, kind="concept"):
        eid = _id(f"entity:{user.id}:{name}")
        container.entity_repo.save(ExtractedEntity.create(id=eid, user_id=user.id, capture_id=capture_id, name=name, entity_type=kind, description=f"Seed entity for {user.email}"))
        container.support_repo.add(user.id, capture_id, "entity", eid); _register(container, "entity", eid); return eid
    echo = entity(users[0], c11, 1, "Echo", "project")
    fastapi = entity(users[0], c11, 2, "FastAPI", "tool")
    console = entity(users[0], c13, 3, "Admin console", "concept")
    # Same user, same graph item supported by two captures.
    container.support_repo.add(users[0].id, c12, "entity", echo)
    container.support_repo.add(users[0].id, c12, "entity", fastapi)
    rel_id = _id("relationship:user1:echo-fastapi")
    container.rel_repo.save(RelationshipEntity.create(id=rel_id, user_id=users[0].id, from_id=echo, to_id=fastapi, relation_type="Depends on", source_capture_id=c11))
    container.support_repo.add(users[0].id, c11, "relationship", rel_id); container.support_repo.add(users[0].id, c12, "relationship", rel_id); _register(container, "relationship", rel_id)
    console_rel = _id("relationship:user1:echo-console")
    container.rel_repo.save(RelationshipEntity.create(id=console_rel, user_id=users[0].id, from_id=echo, to_id=console, relation_type="Related to", source_capture_id=c13))
    container.support_repo.add(users[0].id, c13, "relationship", console_rel); _register(container, "relationship", console_rel)
    user2_fastapi = entity(users[1], c21, 1, "FastAPI", "tool")
    user2_research = entity(users[1], c22, 2, "Research workflow", "concept")
    user2_rel = _id("relationship:user2:fastapi-research")
    container.rel_repo.save(RelationshipEntity.create(id=user2_rel, user_id=users[1].id, from_id=user2_fastapi, to_id=user2_research, relation_type="Related to", source_capture_id=c22))
    container.support_repo.add(users[1].id, c22, "relationship", user2_rel); _register(container, "relationship", user2_rel)
    job = ProcessingJobDTO(id=c31, capture_id=c31, stage=JobStage.EXTRACT, status=JobStatus.FAILED, duration_ms=0, error_message="Seeded provider schema failure", created_at=now, updated_at=now, user_id=users[2].id, error_class="schema_invalid")
    container.job_repo.record_job(job); container.job_repo.record_attempt(c31, 3, "schema_invalid", "Seeded provider schema failure", user_id=users[2].id, retry_limit=3)
    db.commit()
    print("seeded admin identity and 3 users")


def reset() -> None:
    _guard()
    if os.getenv("E2E_RESET_CONFIRM") != "DELETE_ECHO_ADMIN_SEED":
        raise SystemExit("Refusing reset: set E2E_RESET_CONFIRM=DELETE_ECHO_ADMIN_SEED")
    container = get_container(); db = container.db_manager.get_connection()
    ids = [row["record_id"] for row in db.execute("SELECT record_id FROM admin_seed_registry WHERE seed_name = ? AND record_type = 'user'", (SEED,))]
    for user_id in ids:
        if container.user_repo.get_by_id(user_id): container.delete_account_uc.execute(user_id)
    db.execute("DELETE FROM admin_seed_registry WHERE seed_name = ?", (SEED,)); db.commit()
    print(f"reset {len(ids)} seeded users")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("command", choices=["seed", "reset"]); parser.add_argument("--confirm-reset", action="store_true"); args = parser.parse_args()
    if args.command == "seed": seed()
    elif args.confirm_reset: reset()
    else: raise SystemExit("Pass --confirm-reset for reset")
