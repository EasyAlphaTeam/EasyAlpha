"""Run independently of SSE subscriptions; archive generated UI entries at the end."""

import asyncio
import logging
import uuid

from agents import RunConfig, Runner
from openai import APIError

from app.agent import store
from app.agent.agent import build_agent
from app.agent.backtest import ResearchContext
from app.agent.events import RunBuffer, apply_event
from app.agent.session import PostgresSession
from app.core.redis import add_event, get_redis, replay_events, stream_key

logger = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()
_buffers: dict[str, RunBuffer] = {}


def launch_run(run_id: uuid.UUID, user_id: str) -> None:
    task = asyncio.create_task(
        run_agent_and_publish(run_id, user_id), name=f"agent:{run_id}"
    )
    _tasks.add(task)
    task.add_done_callback(_task_finished)


def _task_finished(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception():
        logger.error("Background agent task failed", exc_info=task.exception())


async def _heartbeat(run_id: uuid.UUID, redis) -> None:
    from app.core.config import settings

    while True:
        await asyncio.sleep(10)
        try:
            await asyncio.to_thread(store.heartbeat, run_id)
        except Exception:
            logger.exception("Heartbeat DB update failed for run %s", run_id)
        buffer = _buffers.get(str(run_id))
        if buffer:
            try:
                async with buffer.lock:
                    if not await redis.exists(stream_key(str(run_id))):
                        await add_event(
                            redis, str(run_id), "snapshot", buffer.snapshot()
                        )
                    await redis.expire(
                        stream_key(str(run_id)), settings.CHAT_STREAM_TTL_SECONDS
                    )
            except Exception:
                logger.exception("Heartbeat Redis refresh failed for run %s", run_id)


async def _settle(
    buffer: RunBuffer, status: str, code: str | None, usage: tuple[int, int]
) -> None:
    # Keep the Redis prefix alive while retrying DB-only finalization.
    while True:
        try:
            final = await asyncio.to_thread(
                store.settle_run, buffer.snapshot(), status, code, *usage
            )
            break
        except Exception:
            logger.exception(
                "Archive failed for run %s; retrying archive only", buffer.run_id
            )
            await asyncio.sleep(2)
    buffer.state = final
    await add_event(buffer.redis, buffer.run_id, "snapshot", final)
    await add_event(
        buffer.redis,
        buffer.run_id,
        "done",
        {"run_id": buffer.run_id, "status": final["run"]["status"]},
    )


async def run_agent_and_publish(run_id: uuid.UUID, user_id: str) -> None:
    from app.core.config import settings

    redis = get_redis()
    initial = await asyncio.to_thread(store.start_run, run_id)
    if initial is None:
        return
    buffer = RunBuffer(initial, redis)
    _buffers[str(run_id)] = buffer
    heartbeat = asyncio.create_task(_heartbeat(run_id, redis))
    result = None
    status, code, usage = "completed", None, (0, 0)
    try:
        await add_event(redis, str(run_id), "snapshot", initial)
        session_id, seed = await asyncio.to_thread(store.prepare_session, run_id)
        session = PostgresSession(session_id)
        if seed:
            await session.add_items(seed)
        context = ResearchContext(user_id=user_id, run_id=run_id, buffer=buffer)
        user_input = next(
            m["content"] for m in initial["messages"] if m["type"] == "user"
        )
        result = Runner.run_streamed(
            build_agent(),
            input=user_input,
            context=context,
            session=session,
            max_turns=settings.AGENT_MAX_TURNS,
            run_config=RunConfig(
                tracing_disabled=settings.OPENAI_AGENTS_DISABLE_TRACING
            ),
        )

        async def consume() -> None:
            async for event in result.stream_events():
                await buffer.handle(event)

        await asyncio.wait_for(consume(), timeout=settings.AGENT_RUN_TIMEOUT_SECONDS)
        counts = result.context_wrapper.usage
        usage = counts.input_tokens, counts.output_tokens
    except asyncio.CancelledError:
        status, code = "interrupted", "run_interrupted"
    except asyncio.TimeoutError:
        status, code = "interrupted", "run_timeout"
    except APIError as exc:
        status, code = "failed", "model_service_error"
        if getattr(exc, "status_code", None) in (400, 404, 422):
            code = "model_capability_error"
        logger.warning("Model service rejected run %s: %s", run_id, type(exc).__name__)
    except Exception as exc:
        status, code = "failed", "agent_execution_failed"
        if str(exc) == "agent_context_too_large":
            code = "agent_context_too_large"
        logger.exception("Agent run %s failed", run_id)
    finally:
        if result and status != "completed":
            result.cancel()
        # Store handles incomplete entries too, even when Redis is unavailable.
        try:
            await _settle(buffer, status, code, usage)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            _buffers.pop(str(run_id), None)


async def recover_interrupted_runs() -> None:
    """Single-process MVP: recover UI output, never restart model/tool execution."""
    for run_id in await asyncio.to_thread(store.active_run_ids):
        snapshot = await asyncio.to_thread(store.load_snapshot, run_id)
        redis = get_redis()
        _, events = await replay_events(redis, str(run_id))
        for _, kind, data in events:
            apply_event(snapshot, kind, data)
        code = "run_interrupted" if events else "run_output_unavailable"
        await asyncio.to_thread(store.settle_run, snapshot, "interrupted", code)


async def stop_runs() -> None:
    tasks = list(_tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
