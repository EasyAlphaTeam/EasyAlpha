import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import Session, select

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import (
    InviteCode,
    Item,
    ItemCreate,
    PhoneOtp,
    User,
    UserCreate,
    UserCredits,
    UserUpdate,
)


def create_user(*, session: Session, user_create: UserCreate) -> User:
    update_data: dict[str, Any] = {}
    if user_create.password:
        update_data["hashed_password"] = get_password_hash(user_create.password)
    db_obj = User.model_validate(user_create, update=update_data)
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    # Create initial credits record for the new user
    create_user_credits(session=session, user_id=db_obj.id)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    extra_data = {}
    if "password" in user_data:
        password = user_data["password"]
        if password:
            hashed_password = get_password_hash(password)
            extra_data["hashed_password"] = hashed_password
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    session_user = session.exec(statement).first()
    return session_user


def get_user_by_phone(*, session: Session, phone: str) -> User | None:
    statement = select(User).where(User.phone == phone)
    session_user = session.exec(statement).first()
    return session_user


# Dummy hash to use for timing attack prevention when user is not found
# This is an Argon2 hash of a random password, used to ensure constant-time comparison
DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$MjQyZWE1MzBjYjJlZTI0Yw$YTU4NGM5ZTZmYjE2NzZlZjY0ZWY3ZGRkY2U2OWFjNjk"


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        # Prevent timing attacks by running password verification even when user doesn't exist
        # This ensures the response time is similar whether or not the email exists
        verify_password(password, DUMMY_HASH)
        return None
    if not db_user.hashed_password:
        verify_password(password, DUMMY_HASH)
        return None
    verified, updated_password_hash = verify_password(password, db_user.hashed_password)
    if not verified:
        return None
    if updated_password_hash:
        db_user.hashed_password = updated_password_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_phone_otp(
    *,
    session: Session,
    phone: str,
    code: str,
    expires_at: datetime,
    purpose: str = "login",
) -> PhoneOtp:
    otp = PhoneOtp(phone=phone, code=code, expires_at=expires_at, purpose=purpose)
    session.add(otp)
    session.commit()
    session.refresh(otp)
    return otp


def get_valid_phone_otp(
    *, session: Session, phone: str, code: str, purpose: str = "login"
) -> PhoneOtp | None:
    now = datetime.now(timezone.utc)
    statement = (
        select(PhoneOtp)
        .where(PhoneOtp.phone == phone)
        .where(PhoneOtp.code == code)
        .where(PhoneOtp.purpose == purpose)
        .where(PhoneOtp.used_at.is_(None))
        .where(PhoneOtp.expires_at >= now)
        .order_by(PhoneOtp.created_at.desc())
    )
    return session.exec(statement).first()


def mark_phone_otp_used(*, session: Session, otp: PhoneOtp) -> PhoneOtp:
    otp.used_at = datetime.now(timezone.utc)
    session.add(otp)
    session.commit()
    session.refresh(otp)
    return otp


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item


# ── Invite Code ───────────────────────────────────────────────────────────────


def get_invite_code_by_code(*, session: Session, code: str) -> InviteCode | None:
    statement = select(InviteCode).where(InviteCode.code == code)
    return session.exec(statement).first()


def create_invite_code(*, session: Session, code: str) -> InviteCode:
    invite_code = InviteCode(code=code)
    session.add(invite_code)
    session.commit()
    session.refresh(invite_code)
    return invite_code


def use_invite_code(
    *, session: Session, invite_code: InviteCode, user_id: uuid.UUID
) -> InviteCode:
    invite_code.used_by = user_id
    invite_code.used_at = datetime.now(timezone.utc)
    session.add(invite_code)
    session.commit()
    session.refresh(invite_code)
    return invite_code


# ── User Credits ──────────────────────────────────────────────────────────────

# UTC+8 timezone offset
_UTC8 = timezone(timedelta(hours=8))


def create_user_credits(*, session: Session, user_id: uuid.UUID) -> UserCredits:
    """Create a UserCredits record for a new user with CREDITS_NEW_USER balance."""
    credits = UserCredits(
        user_id=user_id,
        balance=settings.CREDITS_NEW_USER,
        last_refill_at=datetime.now(timezone.utc),
    )
    session.add(credits)
    session.commit()
    session.refresh(credits)
    return credits


def deduct_user_credits(*, session: Session, user_id: uuid.UUID, amount: int) -> int:
    """Deduct credits from a user's balance.

    Returns the new balance after deduction. The balance will not go below 0.
    If no UserCredits record exists, creates one first (via get_user_balance refill logic).
    """
    credits = session.get(UserCredits, user_id)

    if not credits:
        # Ensure a record exists by calling get_user_balance (which handles creation)
        get_user_balance(session=session, user_id=user_id)
        credits = session.get(UserCredits, user_id)

    credits.balance = max(credits.balance - amount, 0)
    session.add(credits)
    session.commit()
    session.refresh(credits)
    return credits.balance


def get_user_balance(*, session: Session, user_id: uuid.UUID) -> int:
    """Get the user's current credits balance.

    Implements daily refill logic:
    - If last_refill_at is today (UTC+8), return current balance.
    - Otherwise, reset balance to CREDITS_DAILY_FREE_PLAN and update last_refill_at.
    - If no UserCredits record exists, create one with CREDITS_NEW_USER.
    """
    credits = session.get(UserCredits, user_id)

    if not credits:
        credits = create_user_credits(session=session, user_id=user_id)
        return credits.balance

    now_utc8 = datetime.now(_UTC8)
    last_refill_utc8 = (
        credits.last_refill_at.astimezone(_UTC8) if credits.last_refill_at else None
    )

    if last_refill_utc8 is None or last_refill_utc8.date() < now_utc8.date():
        # Last refill was before today (UTC+8), reset balance
        credits.balance = settings.CREDITS_DAILY_FREE_PLAN
        credits.last_refill_at = datetime.now(timezone.utc)
        session.add(credits)
        session.commit()
        session.refresh(credits)

    return credits.balance
