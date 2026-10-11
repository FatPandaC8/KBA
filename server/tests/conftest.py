"""Test fixtures: fresh DB per test, seeded users, auth helpers."""
import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://kba:kba@localhost:5433/kba_test")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ["ADMIN_SEED_USERNAME"] = "admin"
os.environ["ADMIN_SEED_PASSWORD"] = "pw"
os.environ["ADMIN_SEED_EMAIL"] = "admin@local"
# Re-import config so the seed hook picks up the test credentials.
import importlib
import app.config
importlib.reload(app.config)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.admin_service import seed_initial_admin
from app.auth import hash_password
from app.models import Base

ENGINE = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
TestingSession = sessionmaker(bind=ENGINE, autocommit=False, autoflush=False)


def _reset():
    with ENGINE.connect() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.commit()
    Base.metadata.create_all(ENGINE)
    db = TestingSession()
    seed_initial_admin(db)
    db.close()


@pytest.fixture()
def client():
    _reset()
    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def db():
    s = TestingSession()
    try:
        yield s
    finally:
        s.close()


def make_user(db, username, role="user", status="active", password="pw"):
    from app.models import User
    u = User(username=username, password_hash=hash_password(password),
             role=role, status=status)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def token(client, username, password="pw"):
    r = client.post("/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(client, t):
    return {"Authorization": f"Bearer {t}"}
