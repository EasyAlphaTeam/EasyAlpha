from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.crud import create_user
from app.models import PhoneOtp, User, UserCreate
from app.utils import generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string, random_phone


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_auto_registers_new_user(
    client: TestClient, db: Session
) -> None:
    email = random_email()
    password = random_lower_string()

    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )

    assert r.status_code == 200
    tokens = r.json()
    assert tokens["access_token"]

    user = crud.get_user_by_email(session=db, email=email)
    assert user
    assert user.email == email


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_send_otp_creates_code(client: TestClient, db: Session) -> None:
    phone = random_phone()
    mock_client = Mock()
    mock_client.send_sms_with_options.return_value = Mock(
        body=Mock(code="OK", message="OK")
    )

    with (
        patch("app.api.routes.login.settings.ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak"),
        patch(
            "app.api.routes.login.settings.ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-sk"
        ),
        patch("app.api.routes.login.settings.SMS_SIGN_NAME", "test-sign"),
        patch(
            "app.api.routes.login.settings.SMS_TEMPLATE_CODE",
            "SMS_TEMPLATE_TEST",
        ),
        patch("app.api.routes.login._create_sms_client", return_value=mock_client),
    ):
        r = client.post(
            f"{settings.API_V1_STR}/login/send-otp",
            json={"phone": phone},
        )

    assert r.status_code == 200
    assert r.json() == {"message": "OTP sent successfully"}

    otp = db.exec(select(PhoneOtp).where(PhoneOtp.phone == phone)).first()
    assert otp
    assert otp.phone == phone
    assert len(otp.code) == 6
    mock_client.send_sms_with_options.assert_called_once()
    request_arg = mock_client.send_sms_with_options.call_args.args[0]
    assert request_arg.phone_numbers == phone
    assert request_arg.sign_name == "test-sign"
    assert request_arg.template_code == "SMS_TEMPLATE_TEST"
    assert request_arg.template_param == f'{{"code": "{otp.code}"}}'


def test_send_otp_returns_500_when_sms_provider_fails(
    client: TestClient, db: Session
) -> None:
    phone = random_phone()
    mock_client = Mock()
    mock_client.send_sms_with_options.return_value = Mock(
        body=Mock(code="isv.BUSINESS_LIMIT_CONTROL", message="limit")
    )

    with (
        patch("app.api.routes.login.settings.ALIBABA_CLOUD_ACCESS_KEY_ID", "test-ak"),
        patch(
            "app.api.routes.login.settings.ALIBABA_CLOUD_ACCESS_KEY_SECRET", "test-sk"
        ),
        patch("app.api.routes.login.settings.SMS_SIGN_NAME", "test-sign"),
        patch(
            "app.api.routes.login.settings.SMS_TEMPLATE_CODE",
            "SMS_TEMPLATE_TEST",
        ),
        patch("app.api.routes.login._create_sms_client", return_value=mock_client),
    ):
        r = client.post(
            f"{settings.API_V1_STR}/login/send-otp",
            json={"phone": phone},
        )

    assert r.status_code == 500
    assert r.json() == {"detail": "Failed to send OTP SMS"}

    otp = db.exec(select(PhoneOtp).where(PhoneOtp.phone == phone)).first()
    assert otp


def test_login_or_register_with_phone_otp(client: TestClient, db: Session) -> None:
    phone = random_phone()
    otp = crud.create_phone_otp(
        session=db,
        phone=phone,
        code="123456",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )

    r = client.post(
        f"{settings.API_V1_STR}/login/auth",
        json={"phone": phone, "otp_code": "123456"},
    )

    assert r.status_code == 200
    tokens = r.json()
    assert tokens["access_token"]

    user = crud.get_user_by_phone(session=db, phone=phone)
    assert user
    assert user.phone == phone

    db.refresh(otp)
    assert otp.used_at is not None


def test_login_or_register_with_email_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()

    r = client.post(
        f"{settings.API_V1_STR}/login/auth",
        json={"email": email, "password": password},
    )

    assert r.status_code == 200
    tokens = r.json()
    assert tokens["access_token"]

    user = crud.get_user_by_email(session=db, email=email)
    assert user
    assert user.email == email


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    # Should return 200 with generic message to prevent email enumeration attacks
    assert r.status_code == 200
    assert r.json() == {
        "message": "If that email is registered, we sent a password recovery link"
    }


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user_create = UserCreate(
        email=email,
        full_name="Test User",
        password=password,
        is_active=True,
        is_superuser=False,
    )
    user = create_user(session=db, user_create=user_create)
    token = generate_password_reset_token(email=email)
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """Test that logging in with a bcrypt password hash upgrades it to argon2."""
    email = random_email()
    password = random_lower_string()

    # Create a bcrypt hash directly (simulating legacy password)
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt hashes start with $2

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # Verify the hash was upgraded to argon2
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # Should not need another update since it's already argon2
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """Test that logging in with an argon2 password hash does not update it."""
    email = random_email()
    password = random_lower_string()

    # Create an argon2 hash (current default)
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # Create user with argon2 hash
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")
