"""SDK-owned PostgreSQL history, read in complete user turns."""

import json
from functools import lru_cache

from agents.extensions.memory import SQLAlchemySession
from agents.items import TResponseInputItem
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import settings


@lru_cache(maxsize=1)
def get_session_engine() -> AsyncEngine:
    return create_async_engine(
        str(settings.SQLALCHEMY_DATABASE_URI), pool_pre_ping=True
    )


class PostgresSession(SQLAlchemySession):
    def __init__(self, session_id: str, *, engine: AsyncEngine | None = None):
        super().__init__(
            session_id,
            engine=engine or get_session_engine(),
            create_tables=False,
            messages_table="agent_session_items",
            ensure_ascii=False,
        )

    async def get_items(self, limit: int | None = None) -> list[TResponseInputItem]:
        # SDK must see paired tool calls/results, never an arbitrary item-count tail.
        items = await super().get_items()
        starts = [i for i, item in enumerate(items) if item.get("role") == "user"]
        if len(starts) >= settings.AGENT_CONTEXT_MAX_USER_TURNS:
            items = items[starts[-settings.AGENT_CONTEXT_MAX_USER_TURNS] :]
        while (
            len(json.dumps(items, ensure_ascii=False))
            > settings.AGENT_CONTEXT_MAX_CHARS
        ):
            next_turn = next(
                (
                    i
                    for i, item in enumerate(items)
                    if i > 0 and item.get("role") == "user"
                ),
                None,
            )
            if next_turn is None:
                raise ValueError("agent_context_too_large")
            items = items[next_turn:]
        # Deliberately ignore positive item limits: user-turn boundaries take priority.
        return [] if limit == 0 else items


async def close_session_engine() -> None:
    if get_session_engine.cache_info().currsize:
        await get_session_engine().dispose()
        get_session_engine.cache_clear()
