"""Isolated auth tests: no application lifespan or business database access."""

import base64
import hashlib
import json
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from jwt.exceptions import PyJWKClientConnectionError
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.deps import get_db
from app.api.routes import google, users
from app.core.config import settings
from app.models import InviteCode, User, UserCredits

PREFIX = "/api/v1/auth/google"
RETURN_URI = "http://localhost:5173/auth/google/callback?source=login"


class MemoryRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    async def set(self, key, value, ex):
        self.values[key] = value
        self.ttls[key] = ex

    async def getdel(self, key):
        return self.values.pop(key, None)


@pytest.fixture(scope="module")
def signing_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture
def auth(monkeypatch, signing_key):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "test-client")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "test-secret")
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URI", f"http://localhost{PREFIX}/callback"
    )
    monkeypatch.setattr(settings, "GOOGLE_ALLOWED_REDIRECT_URIS", [RETURN_URI])
    monkeypatch.setattr(settings, "INVITE_CODE_ENABLED", False)
    redis = MemoryRedis()
    monkeypatch.setattr(google, "get_redis", lambda: redis)
    monkeypatch.setattr(
        google._jwks,
        "get_signing_key_from_jwt",
        lambda _token: SimpleNamespace(key=signing_key.public_key()),
    )
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(
        engine, tables=[User.__table__, UserCredits.__table__, InviteCode.__table__]
    )
    with Session(engine) as db:
        app = FastAPI()
        app.include_router(google.router, prefix="/api/v1")
        app.include_router(users.router, prefix="/api/v1")
        app.dependency_overrides[get_db] = lambda: db
        harness = SimpleNamespace(
            db=db,
            redis=redis,
            claims={},
            calls=[],
            token_status=200,
            token_payload=None,
            signing_key=signing_key,
        )

        async def exchange(_client, url, *, data):
            harness.calls.append(data)
            flow = harness.flow
            claims = {
                "iss": "https://accounts.google.com",
                "aud": "test-client",
                "sub": "google-subject",
                "iat": int(time.time()),
                "exp": int(time.time()) + 300,
                "nonce": flow["nonce"],
                "email": "google.user@gmail.com",
                "email_verified": True,
                "name": "Google User",
            }
            claims.update(harness.claims)
            payload = harness.token_payload
            if payload is None:
                payload = {
                    "id_token": jwt.encode(
                        claims, harness.signing_key, algorithm="RS256"
                    )
                }
            return httpx.Response(
                harness.token_status, json=payload, request=httpx.Request("POST", url)
            )

        monkeypatch.setattr(httpx.AsyncClient, "post", exchange)
        with TestClient(
            app, base_url="http://localhost", follow_redirects=False
        ) as client:
            harness.client = client
            yield harness
    engine.dispose()


def start(auth, **params):
    response = auth.client.get(PREFIX, params={"redirect_uri": RETURN_URI, **params})
    assert response.status_code == 302
    auth.parameters = parse_qs(urlsplit(response.headers["location"]).query)
    auth.state = auth.parameters["state"][0]
    auth.flow = json.loads(auth.redis.values[f"auth:google:state:{auth.state}"])
    return response


def callback(auth, **params):
    return auth.client.get(
        f"{PREFIX}/callback",
        params={"state": auth.state, "code": "google-code", **params},
    )


def test_authorization_parameters_and_cookie(auth):
    response = start(auth)
    params = auth.parameters
    assert params["redirect_uri"] == [settings.GOOGLE_REDIRECT_URI]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["openid email profile"]
    expected = (
        base64.urlsafe_b64encode(
            hashlib.sha256(auth.flow["verifier"].encode()).digest()
        )
        .decode()
        .rstrip("=")
    )
    assert params["code_challenge"] == [expected]
    assert params["code_challenge_method"] == ["S256"]
    assert (
        auth.redis.ttls[f"auth:google:state:{auth.state}"]
        == settings.GOOGLE_STATE_TTL_SECONDS
    )
    assert "httponly" in response.headers["set-cookie"].lower()
    assert "samesite=lax" in response.headers["set-cookie"].lower()
    assert "client_secret" not in response.headers["location"]
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example/callback",
        "//evil.example",
        "javascript:alert(1)",
        RETURN_URI + "#fragment",
        RETURN_URI + "#",
        "http://localhost:5173@evil.example/callback",
        "http://example.com/callback",
        "https://example.com:bad/callback",
        "https://example.com/\\evil",
        "https://example.com/callback\n",
    ],
)
def test_rejects_unsafe_return_uris(auth, uri):
    assert auth.client.get(PREFIX, params={"redirect_uri": uri}).status_code == 400
    assert not auth.redis.values


def test_missing_config(auth, monkeypatch):
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "")
    assert (
        auth.client.get(PREFIX, params={"redirect_uri": RETURN_URI}).status_code == 503
    )


def test_secure_cookie_for_https_callback(auth, monkeypatch):
    monkeypatch.setattr(
        settings, "GOOGLE_REDIRECT_URI", f"https://localhost{PREFIX}/callback"
    )
    assert "secure" in start(auth).headers["set-cookie"].lower()


def test_register_and_use_existing_system_token(auth):
    start(auth)
    response = callback(auth)
    assert response.status_code == 302
    location = urlsplit(response.headers["location"])
    assert location.query == "source=login"
    token = parse_qs(location.fragment)
    assert token["token_type"] == ["bearer"]
    assert "access_token" not in location.query
    user = auth.db.exec(select(User)).one()
    assert user.google_sub == "google-subject"
    assert user.hashed_password is None
    assert user.is_active and not user.is_superuser
    assert user.full_name == "Google User"
    credits = auth.db.get(UserCredits, user.id)
    assert credits.balance == settings.CREDITS_NEW_USER
    assert auth.calls[0]["redirect_uri"] == settings.GOOGLE_REDIRECT_URI
    assert auth.calls[0]["code_verifier"] == auth.flow["verifier"]
    me = auth.client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token['access_token'][0]}"},
    )
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)
    assert "google_sub" not in me.json()
    assert response.headers["cache-control"] == "no-store"
    assert "max-age=0" in response.headers["set-cookie"].lower()


def test_repeat_login_uses_sub_even_after_email_change(auth, monkeypatch):
    start(auth)
    assert callback(auth).status_code == 302
    user = auth.db.exec(select(User)).one()
    credits = auth.db.get(UserCredits, user.id)
    credits.balance = 17
    auth.db.add(credits)
    auth.db.commit()
    monkeypatch.setattr(settings, "INVITE_CODE_ENABLED", True)
    start(auth)
    auth.claims["email"] = "changed@gmail.com"
    assert callback(auth).status_code == 302
    assert auth.db.exec(select(User)).one().id == user.id
    auth.db.refresh(credits)
    assert credits.balance == 17
    assert user.email == "google.user@gmail.com"


@pytest.mark.parametrize(
    "email,hd,expected",
    [
        ("google.user@gmail.com", None, 302),
        ("user@example.com", "example.com", 302),
        ("user@example.com", None, 409),
    ],
)
def test_existing_email_link_rules(auth, monkeypatch, email, hd, expected):
    user = User(email=email, hashed_password="existing-hash")
    auth.db.add(user)
    auth.db.commit()
    monkeypatch.setattr(settings, "INVITE_CODE_ENABLED", True)
    start(auth)
    auth.claims.update(email=email, hd=hd)
    assert callback(auth).status_code == expected
    auth.db.refresh(user)
    assert user.hashed_password == "existing-hash"
    assert user.google_sub == ("google-subject" if expected == 302 else None)
    assert not auth.db.exec(select(UserCredits)).all()


@pytest.mark.parametrize("google_sub", [None, "google-subject"])
def test_inactive_account_cannot_login_or_link(auth, google_sub):
    user = User(email="google.user@gmail.com", google_sub=google_sub, is_active=False)
    auth.db.add(user)
    auth.db.commit()
    start(auth)
    assert callback(auth).status_code == 400
    auth.db.refresh(user)
    assert user.google_sub == google_sub


def test_cannot_replace_existing_google_binding(auth):
    user = User(email="google.user@gmail.com", google_sub="another-google-subject")
    auth.db.add(user)
    auth.db.commit()
    start(auth)
    assert callback(auth).status_code == 409
    auth.db.refresh(user)
    assert user.google_sub == "another-google-subject"


@pytest.mark.parametrize("kind", ["missing", "invalid", "used", "valid"])
def test_invite_registration(auth, monkeypatch, kind):
    monkeypatch.setattr(settings, "INVITE_CODE_ENABLED", True)
    invitation = InviteCode(code="ABCDEFGH")
    if kind == "used":
        owner = User(email="existing@example.com")
        auth.db.add(owner)
        auth.db.flush()
        invitation.used_by = owner.id
    auth.db.add(invitation)
    auth.db.commit()
    params = (
        {}
        if kind == "missing"
        else {"invite_code": "INVALID1" if kind == "invalid" else "ABCDEFGH"}
    )
    start(auth, **params)
    assert callback(auth).status_code == (302 if kind == "valid" else 400)
    auth.db.refresh(invitation)
    if kind == "valid":
        user = auth.db.exec(select(User)).one()
        assert invitation.used_by == user.id
        assert invitation.used_at is not None
        assert auth.db.get(UserCredits, user.id) is not None
    else:
        assert not auth.db.exec(select(User).where(User.google_sub.is_not(None))).all()
        assert not auth.db.exec(select(UserCredits)).all()


def test_transaction_failure_does_not_consume_invite_or_create_account(
    auth, monkeypatch
):
    monkeypatch.setattr(settings, "INVITE_CODE_ENABLED", True)
    invitation = InviteCode(code="ABCDEFGH")
    auth.db.add(invitation)
    auth.db.commit()
    start(auth, invite_code="ABCDEFGH")

    def fail():
        raise IntegrityError("test insert", {}, Exception("test constraint failure"))

    monkeypatch.setattr(auth.db, "commit", fail)
    assert callback(auth).status_code == 409
    assert not auth.db.exec(select(User)).all()
    assert not auth.db.exec(select(UserCredits)).all()
    auth.db.refresh(invitation)
    assert invitation.used_by is None


@pytest.mark.parametrize(
    "kind", ["wrong", "missing", "no-cookie", "expired", "unicode"]
)
def test_invalid_state_never_exchanges_code(auth, kind):
    start(auth)
    state = auth.state
    if kind == "wrong":
        state = "wrong"
    elif kind == "missing":
        state = ""
    elif kind == "no-cookie":
        auth.client.cookies.clear()
    elif kind == "expired":
        auth.redis.values.clear()
    elif kind == "unicode":
        state = "无效"
    assert callback(auth, state=state).status_code == 400
    assert not auth.calls


def test_state_cannot_be_replayed(auth):
    start(auth)
    assert callback(auth).status_code == 302
    auth.client.cookies.set(google.STATE_COOKIE, auth.state)
    assert callback(auth).status_code == 400
    assert len(auth.calls) == 1


@pytest.mark.parametrize("params", [{"error": "access_denied"}, {"code": ""}])
def test_denied_or_missing_code_consumes_state(auth, params):
    start(auth)
    assert callback(auth, **params).status_code == 400
    assert not auth.redis.values
    assert not auth.calls


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "another-client"},
        {"iss": "https://evil.example"},
        {"nonce": "wrong"},
        {"nonce": None},
        {"exp": 1},
        {"iat": int(time.time()) + 3600},
        {"email_verified": False},
        {"email_verified": "true"},
        {"email": "invalid"},
        {"sub": ""},
        {"azp": "another-client"},
    ],
)
def test_invalid_signed_identity_is_rejected(auth, claims):
    start(auth)
    auth.claims.update(claims)
    assert callback(auth).status_code == 400
    assert not auth.db.exec(select(User)).all()


def test_invalid_signature(auth):
    auth.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    start(auth)
    assert callback(auth).status_code == 400


@pytest.mark.parametrize(
    "status,expected", [(400, 400), (401, 400), (429, 502), (500, 502)]
)
def test_google_token_errors(auth, status, expected):
    auth.token_status = status
    start(auth)
    response = callback(auth)
    assert response.status_code == expected
    assert not auth.db.exec(select(User)).all()
    assert "test-secret" not in response.text


@pytest.mark.parametrize("payload", [{}, {"id_token": None}, []])
def test_malformed_token_response(auth, payload):
    auth.token_payload = payload
    start(auth)
    assert callback(auth).status_code == 502


def test_jwks_outage(auth, monkeypatch):
    def fail(_token):
        raise PyJWKClientConnectionError("unreachable")

    monkeypatch.setattr(google._jwks, "get_signing_key_from_jwt", fail)
    start(auth)
    assert callback(auth).status_code == 502


@pytest.mark.parametrize("stage", ["start", "callback"])
def test_redis_outage(auth, monkeypatch, stage):
    async def fail(*_args, **_kwargs):
        raise RedisConnectionError("unreachable")

    if stage == "callback":
        start(auth)
        monkeypatch.setattr(auth.redis, "getdel", fail)
        response = callback(auth)
    else:
        monkeypatch.setattr(auth.redis, "set", fail)
        response = auth.client.get(PREFIX, params={"redirect_uri": RETURN_URI})
    assert response.status_code == 503


def test_return_uri_is_rechecked_on_callback(auth, monkeypatch):
    start(auth)
    monkeypatch.setattr(
        settings, "GOOGLE_ALLOWED_REDIRECT_URIS", ["https://another.example/callback"]
    )
    assert callback(auth).status_code == 400
    assert not auth.calls


def test_invalid_system_subject_returns_auth_error(auth):
    token = jwt.encode(
        {"sub": "invalid-uuid", "exp": int(time.time()) + 300},
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    response = auth.client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403
