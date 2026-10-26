"""Multi-turn chats with Redis-backed stream recovery and end-of-run archiving."""

import asyncio
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import col, select

from app import crud
from app.agent import store
from app.agent.agent import TITLE_MAX_CHARS
from app.agent.events import apply_event
from app.agent.worker import launch_run
from app.api.deps import CurrentUser, SessionDep
from app.core.redis import get_redis, read_events, replay_events, stream_key
from app.models import (
    ACTIVE_RUN_STATUSES,
    Chat,
    ChatAccepted,
    ChatHistory,
    ChatMessage,
    ChatPublic,
    ChatRun,
    Message,
    User,
    get_datetime_utc,
)

router = APIRouter(prefix="/chats", tags=["chats"])


class SendMessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=8000)
    request_id: uuid.UUID


def owned_chat(db, user, chat_id: uuid.UUID, *, lock: bool = False) -> Chat:
    query = select(Chat).where(
        Chat.id == chat_id, Chat.user_id == user.id, col(Chat.is_deleted).is_(False)
    )  # noqa: E712
    if lock:
        query = query.with_for_update()
    chat = db.exec(query).first()
    if chat is None:
        raise HTTPException(404, detail="chat_not_found")
    return chat


def latest_run(db, chat_id: uuid.UUID) -> ChatRun | None:
    return db.exec(
        select(ChatRun)
        .where(ChatRun.chat_id == chat_id)
        .order_by(col(ChatRun.turn_no).desc())
        .limit(1)
    ).first()


def chat_public(db, chat: Chat) -> ChatPublic:
    run = latest_run(db, chat.id)
    return ChatPublic(
        **chat.model_dump(),
        active_run_id=run.id if run and run.status in ACTIVE_RUN_STATUSES else None,
        last_run_status=run.status if run else None,
    )


def accepted(db, chat: Chat, run: ChatRun) -> ChatAccepted:
    user_message = db.exec(
        select(ChatMessage).where(
            ChatMessage.run_id == run.id, ChatMessage.type == "user"
        )
    ).one()
    return ChatAccepted(chat=chat_public(db, chat), run=run, user_message=user_message)


def create_turn(db, chat: Chat, body: SendMessageBody, turn_no: int) -> ChatRun:
    if not body.content.strip():
        raise HTTPException(422, detail="message_empty")
    run = ChatRun(chat_id=chat.id, request_id=body.request_id, turn_no=turn_no)
    db.add(run)
    db.flush()
    db.add(
        ChatMessage(
            run_id=run.id,
            seq=0,
            type="user",
            content=body.content,
            source_item_id=str(body.request_id),
            status="completed",
            finished_at=get_datetime_utc(),
        )
    )
    chat.updated_at = get_datetime_utc()
    db.add(chat)
    return run


@router.post("", response_model=ChatAccepted)
async def create_chat(
    body: SendMessageBody, session: SessionDep, current_user: CurrentUser
) -> Any:
    # User-row lock makes first-chat request idempotent, including concurrent retries.
    session.exec(select(User).where(User.id == current_user.id).with_for_update()).one()
    chat = session.exec(
        select(Chat).where(
            Chat.user_id == current_user.id, Chat.create_request_id == body.request_id
        )
    ).first()
    if chat:
        if chat.is_deleted:
            raise HTTPException(409, detail="chat_deleted")
        run = session.exec(
            select(ChatRun).where(ChatRun.chat_id == chat.id, ChatRun.turn_no == 1)
        ).one()
        if run.status == "queued":
            launch_run(run.id, str(current_user.id))
        return accepted(session, chat, run)
    if crud.get_user_balance(session=session, user_id=current_user.id) < 10:
        raise HTTPException(402, detail="insufficient_credits")
    # Balance refill may commit; reacquire lock and recheck the unique request.
    session.exec(select(User).where(User.id == current_user.id).with_for_update()).one()
    chat = session.exec(
        select(Chat).where(
            Chat.user_id == current_user.id, Chat.create_request_id == body.request_id
        )
    ).first()
    if chat:
        if chat.is_deleted:
            raise HTTPException(409, detail="chat_deleted")
        run = session.exec(
            select(ChatRun).where(ChatRun.chat_id == chat.id, ChatRun.turn_no == 1)
        ).one()
        if run.status == "queued":
            launch_run(run.id, str(current_user.id))
        return accepted(session, chat, run)
    chat = Chat(
        user_id=current_user.id,
        title=body.content.strip()[:TITLE_MAX_CHARS],
        create_request_id=body.request_id,
    )
    session.add(chat)
    session.flush()
    run = create_turn(session, chat, body, 1)
    session.commit()
    response = accepted(session, chat, run)
    launch_run(run.id, str(current_user.id))
    return response


@router.post("/{chat_id}/messages", response_model=ChatAccepted)
async def send_message(
    chat_id: uuid.UUID,
    body: SendMessageBody,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    owned_chat(session, current_user, chat_id)
    # Refill/check before taking the chat lock: this helper owns its own commit.
    balance = crud.get_user_balance(session=session, user_id=current_user.id)
    chat = owned_chat(session, current_user, chat_id, lock=True)
    existing = session.exec(
        select(ChatRun).where(
            ChatRun.chat_id == chat_id, ChatRun.request_id == body.request_id
        )
    ).first()
    if existing:
        if existing.status == "queued":
            launch_run(existing.id, str(current_user.id))
        return accepted(session, chat, existing)
    previous = latest_run(session, chat_id)
    if previous and previous.status in ACTIVE_RUN_STATUSES:
        raise HTTPException(409, detail="chat_busy")
    if balance < 10:
        raise HTTPException(402, detail="insufficient_credits")
    run = create_turn(session, chat, body, previous.turn_no + 1 if previous else 1)
    session.commit()
    response = accepted(session, chat, run)
    launch_run(run.id, str(current_user.id))
    return response


@router.get("", response_model=list[ChatPublic])
def list_chats(
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(default=100, ge=1, le=200),
) -> Any:
    chats = session.exec(
        select(Chat)
        .where(Chat.user_id == current_user.id, col(Chat.is_deleted).is_(False))
        .order_by(col(Chat.updated_at).desc())
        .limit(limit)
    ).all()  # noqa: E712
    runs = (
        session.exec(
            select(ChatRun)
            .where(col(ChatRun.chat_id).in_([chat.id for chat in chats]))
            .distinct(col(ChatRun.chat_id))
            .order_by(col(ChatRun.chat_id), col(ChatRun.turn_no).desc())
        ).all()
        if chats
        else []
    )
    by_chat = {run.chat_id: run for run in runs}
    return [
        ChatPublic(
            **chat.model_dump(),
            active_run_id=run.id
            if (run := by_chat.get(chat.id)) and run.status in ACTIVE_RUN_STATUSES
            else None,
            last_run_status=run.status if run else None,
        )
        for chat in chats
    ]


@router.get("/{chat_id}/messages", response_model=ChatHistory)
def get_chat_messages(
    chat_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    before_turn: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
) -> Any:
    owned_chat(session, current_user, chat_id)
    query = select(ChatRun).where(ChatRun.chat_id == chat_id)
    if before_turn is not None:
        query = query.where(ChatRun.turn_no < before_turn)
    runs = session.exec(query.order_by(col(ChatRun.turn_no).desc()).limit(limit)).all()
    messages = (
        session.exec(
            select(ChatMessage)
            .join(ChatRun)
            .where(col(ChatMessage.run_id).in_([r.id for r in runs]))
            .order_by(col(ChatRun.turn_no), col(ChatMessage.seq))
        ).all()
        if runs
        else []
    )
    last = latest_run(session, chat_id)
    return ChatHistory(
        messages=list(messages),
        active_run_id=last.id if last and last.status in ACTIVE_RUN_STATUSES else None,
        latest_run=last,
        next_before_turn=runs[-1].turn_no
        if len(runs) == limit and runs[-1].turn_no > 1
        else None,
    )


@router.get("/{chat_id}/runs/{run_id}", response_model=ChatRun)
def get_run(
    chat_id: uuid.UUID,
    run_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    owned_chat(session, current_user, chat_id)
    run = session.get(ChatRun, run_id)
    if run is None or run.chat_id != chat_id:
        raise HTTPException(404, detail="run_not_found")
    return run


def sse(kind: str, data: dict, event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/{chat_id}/events")
async def stream_chat_events(
    chat_id: uuid.UUID,
    run_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    current_user: CurrentUser,
    after: str | None = None,
) -> StreamingResponse:
    get_run(chat_id, run_id, session, current_user)
    cursor = request.headers.get("Last-Event-ID") or after
    if cursor and not re.fullmatch(r"\d+-\d+", cursor):
        raise HTTPException(422, detail="invalid_event_cursor")
    session.close()  # Do not retain an auth DB connection for the lifetime of SSE.
    return StreamingResponse(
        stream_run(run_id, request, cursor),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.delete("/{chat_id}", response_model=Message)
def delete_chat(
    chat_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> Any:
    chat = owned_chat(session, current_user, chat_id, lock=True)
    run = latest_run(session, chat_id)
    if run and run.status in ACTIVE_RUN_STATUSES:
        raise HTTPException(409, detail="chat_busy")
    chat.is_deleted = True
    session.add(chat)
    session.commit()
    return Message(message="Chat deleted successfully")
