"""Integration tests use a dedicated, disposable PostgreSQL database and Redis."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.db import engine
from app.main import app
from app.models import User, UserCredits, get_datetime_utc


@pytest.fixture(autouse=True, scope="session")
def isolated_database():
    if settings.POSTGRES_DB != "agent_test" or settings.POSTGRES_PORT != 55439:
        pytest.skip("Run only against disposable agent_test PostgreSQL on port 55439")


@pytest.fixture
def user():
    with Session(engine, expire_on_commit=False) as db:
        user = User(email=f"agent-{uuid.uuid4()}@example.com", hashed_password="unused")
        db.add(user)
        db.flush()
        db.add(
            UserCredits(user_id=user.id, balance=100, last_refill_at=get_datetime_utc())
        )
        db.commit()
        yield user
        db.exec(delete(User).where(User.id == user.id))
        db.commit()


@pytest.fixture
def client(user, monkeypatch):
    from app.api.routes import chats

    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(chats, "launch_run", lambda *args: None)
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client
    app.dependency_overrides.clear()
