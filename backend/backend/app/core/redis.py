"""Per-run replayable Redis Streams. Never trim an active run."""

import json
from typing import Any

from redis.asyncio import ConnectionPool, Redis

from app.core.config import settings

_pool: ConnectionPool | None = None


def get_redis() -> Redis:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL, decode_responses=True, max_connections=50
        )
    return Redis(connection_pool=_pool)


async def close_redis() -> None:
    global _pool
    if _pool is not None:
        await _pool.disconnect()
        _pool = None


def stream_key(run_id: str) -> str:
    return f"chat:run:events:{run_id}"


async def add_event(redis: Redis, run_id: str, event_type: str, data: Any) -> str:
    async with redis.pipeline(transaction=True) as pipe:
        pipe.xadd(
            stream_key(run_id),
            {
                "type": event_type,
                "data": json.dumps(data, ensure_ascii=False, allow_nan=False),
            },
        )
        pipe.expire(stream_key(run_id), settings.CHAT_STREAM_TTL_SECONDS)
        results = await pipe.execute()
    return results[0]


def decode_events(entries: list) -> list[tuple[str, str, dict]]:
    return [
        (entry_id, fields["type"], json.loads(fields["data"]))
        for entry_id, fields in entries
    ]


async def read_events(
    redis: Redis, run_id: str, last_id: str = "0-0", block_ms: int = 5000
) -> list[tuple[str, str, dict]]:
    streams = await redis.xread(
        {stream_key(run_id): last_id}, count=100, block=block_ms
    )
    return [event for _, entries in streams for event in decode_events(entries)]


async def replay_events(redis: Redis, run_id: str):
    """Capture a finite boundary first; concurrent writes remain available after it."""
    tail = await redis.xrevrange(stream_key(run_id), count=1)
    boundary = tail[0][0] if tail else "0-0"
    cursor = "-"
    events = []
    while boundary != "0-0":
        batch = await redis.xrange(
            stream_key(run_id), min=cursor, max=boundary, count=500
        )
        if not batch:
            break
        events.extend(decode_events(batch))
        cursor = f"({batch[-1][0]}"
    return boundary, events
