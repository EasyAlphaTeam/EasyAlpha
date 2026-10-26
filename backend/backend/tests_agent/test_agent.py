import asyncio
import copy
import json
import uuid
from types import SimpleNamespace

from agents import Agent, WebSearchTool
from agents.models.interface import Model
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemAddedEvent,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseTextDeltaEvent,
    ResponseUsage,
)
from sqlmodel import Session, select

from app.agent import store, worker
from app.agent.backtest import backtest_tool
from app.agent.events import RunBuffer, apply_event
from app.agent.session import PostgresSession, close_session_engine
from app.api.routes.chats import stream_run
from app.core.config import settings
from app.core.db import engine
from app.core.redis import close_redis, get_redis, replay_events, stream_key
from app.models import Backtest, Chat, ChatMessage, ChatRun, Factor, UserCredits


def new_turn(user, chat=None, content="设计低波动因子", turn=1):
    with Session(engine, expire_on_commit=False) as db:
        if chat is None:
            chat = Chat(user_id=user.id, title="test")
            db.add(chat)
            db.flush()
        run = ChatRun(chat_id=chat.id, request_id=uuid.uuid4(), turn_no=turn)
        db.add(run)
        db.flush()
        db.add(
            ChatMessage(
                run_id=run.id,
                seq=0,
                type="user",
                content=content,
                source_item_id=str(run.request_id),
            )
        )
        db.commit()
        return chat, run


def execute(coro):
    async def wrapped():
        try:
            return await coro
        finally:
            await close_session_engine()
            await close_redis()

    return asyncio.run(wrapped())


def output_message(item_id, text):
    return ResponseOutputMessage(
        id=item_id,
        type="message",
        role="assistant",
        status="completed",
        content=[
            ResponseOutputText(
                type="output_text", text=text, annotations=[], logprobs=[]
            )
        ],
    )


class ScriptedModel(Model):
    """Uses the real SDK runner, tools and Session; replaces only model inference."""

    def __init__(self, *, gate=None, tool=False, failure=False):
        self.inputs = []
        self.gate = gate
        self.tool = tool
        self.failure = failure
        self.ready = asyncio.Event()

    async def get_response(self, *args, **kwargs):
        raise AssertionError("streaming expected")

    async def stream_response(self, system_instructions, input, *args, **kwargs):
        self.inputs.append(copy.deepcopy(input))
        item_id = f"msg_{uuid.uuid4().hex}"
        output = []
        if self.tool and len(self.inputs) == 1:
            # Native hosted search progress must not depend on a local tool hook.
            from openai.types.responses import (
                ResponseFunctionWebSearch,
                ResponseWebSearchCallInProgressEvent,
            )

            search = ResponseFunctionWebSearch(
                id="ws_test",
                type="web_search_call",
                status="completed",
                action={"type": "search", "query": "低波动因子"},
            )
            yield ResponseWebSearchCallInProgressEvent(
                type="response.web_search_call.in_progress",
                item_id=search.id,
                output_index=0,
                sequence_number=0,
            )
            yield ResponseOutputItemDoneEvent(
                type="response.output_item.done",
                item=search,
                output_index=0,
                sequence_number=1,
            )
            output = [
                search,
                ResponseFunctionToolCall(
                    id="fc_test",
                    call_id="call_test",
                    type="function_call",
                    name="backtest",
                    arguments=json.dumps(
                        {"factor_name": "低波动", "factor_expr": "Std($close,20)"}
                    ),
                ),
            ]
        else:
            text = "已生成中文🙂，因子结果为20天。"
            yield ResponseOutputItemAddedEvent(
                type="response.output_item.added",
                sequence_number=0,
                output_index=0,
                item=ResponseOutputMessage(
                    id=item_id,
                    type="message",
                    role="assistant",
                    status="in_progress",
                    content=[],
                ),
            )
            yield ResponseTextDeltaEvent(
                type="response.output_text.delta",
                content_index=0,
                delta=text[:8],
                item_id=item_id,
                logprobs=[],
                output_index=0,
                sequence_number=1,
            )
            self.ready.set()
            if self.gate:
                await self.gate.wait()
            if self.failure:
                # Allow the already streamed prefix to reach the consumer before a later I/O error.
                await asyncio.sleep(0.05)
                raise RuntimeError("simulated provider failure")
            yield ResponseTextDeltaEvent(
                type="response.output_text.delta",
                content_index=0,
                delta=text[8:],
                item_id=item_id,
                logprobs=[],
                output_index=0,
                sequence_number=2,
            )
            message = output_message(item_id, text)
            yield ResponseOutputItemDoneEvent(
                type="response.output_item.done",
                item=message,
                output_index=0,
                sequence_number=3,
            )
            output = [message]
        response = Response(
            id=f"resp_{uuid.uuid4().hex}",
            created_at=1,
            model="test",
            object="response",
            status="completed",
            output=output,
            parallel_tool_calls=False,
            tool_choice="auto",
            tools=[],
            usage=ResponseUsage(
                input_tokens=1000,
                output_tokens=200,
                total_tokens=1200,
                input_tokens_details={"cached_tokens": 0, "cache_write_tokens": 0},
                output_tokens_details={"reasoning_tokens": 0},
            ),
        )
        yield ResponseCompletedEvent(
            type="response.completed", response=response, sequence_number=4
        )


async def wait_for_buffer(run_id):
    async def wait():
        while True:
            buffer = worker._buffers.get(str(run_id))
            if buffer and any(
                row["type"] == "ai" and row["content"]
                for row in buffer.state["messages"]
            ):
                return buffer
            await asyncio.sleep(0.01)

    return await asyncio.wait_for(wait(), 5)


async def connected():
    return False


def test_archive_only_at_end_and_refresh_then_live(user, monkeypatch):
    chat, run = new_turn(user)

    async def scenario():
        gate = asyncio.Event()
        model = ScriptedModel(gate=gate)
        monkeypatch.setattr(
            worker, "build_agent", lambda: Agent(name="test", model=model)
        )
        task = asyncio.create_task(worker.run_agent_and_publish(run.id, str(user.id)))
        buffer = await wait_for_buffer(run.id)
        assert [row["type"] for row in store.load_snapshot(run.id)["messages"]] == [
            "user"
        ]
        stream = stream_run(run.id, SimpleNamespace(is_disconnected=connected))
        first = await anext(stream)
        restored = json.loads(first.split("data: ")[1])
        assert (
            next(row for row in restored["messages"] if row["type"] == "ai")["content"]
            == "已生成中文🙂，因"
        )
        assert "id: " in first
        gate.set()
        frames = []
        async for frame in stream:
            frames.append(frame)
        await task
        assert any("event: delta" in frame for frame in frames)
        assert any("event: done" in frame for frame in frames)
        final = store.load_snapshot(run.id)
        assert final["run"]["status"] == "completed"
        assert (
            next(row for row in final["messages"] if row["type"] == "ai")["content"]
            == "已生成中文🙂，因子结果为20天。"
        )
        # The final Redis reconstruction and DB archive agree on IDs, order and content.
        _, events = await replay_events(get_redis(), str(run.id))
        replay = store.load_snapshot(run.id)
        for _, kind, data in events:
            apply_event(replay, kind, data)
        assert replay == final
        assert buffer.run_id == str(run.id)
        with Session(engine) as db:
            assert db.get(UserCredits, user.id).balance == 98
        store.settle_run(final, "completed", input_tokens=1000, output_tokens=200)
        with Session(engine) as db:
            assert db.get(UserCredits, user.id).balance == 98

    execute(scenario())


def test_real_sdk_session_persists_across_three_turns(user, monkeypatch):
    chat, first = new_turn(user)

    async def scenario():
        model = ScriptedModel()
        monkeypatch.setattr(
            worker, "build_agent", lambda: Agent(name="test", model=model)
        )
        await worker.run_agent_and_publish(first.id, str(user.id))
        _, second = new_turn(user, chat=chat, content="把窗口改为60天", turn=2)
        await worker.run_agent_and_publish(second.id, str(user.id))
        _, third = new_turn(user, chat=chat, content="解释一下上一轮", turn=3)
        await worker.run_agent_and_publish(third.id, str(user.id))
        assert len(model.inputs) == 3
        assert sum(item.get("role") == "user" for item in model.inputs[2]) == 3
        assert any(item.get("content") == "把窗口改为60天" for item in model.inputs[2])
        assert len(await PostgresSession(chat.sdk_session_id).get_items()) == 6
        assert all(
            store.load_snapshot(r.id)["run"]["status"] == "completed"
            for r in [first, second, third]
        )

    execute(scenario())


def test_native_search_function_tool_and_ordering(user, monkeypatch):
    chat, run = new_turn(user)
    calls = []

    def fake_service(_user_id, run_id, name, expr):
        calls.append(run_id)
        with Session(engine, expire_on_commit=False) as db:
            factor = Factor(
                user_id=user.id, chat_run_id=run.id, index=1, name=name, expr=expr
            )
            db.add(factor)
            db.flush()
            backtest = Backtest(factor_id=factor.id, results={"IC Mean": 0.1})
            db.add(backtest)
            db.commit()
            return {
                "ok": True,
                "factor_id": str(factor.id),
                "backtest_id": str(backtest.id),
                "name": name,
                "expr": expr,
                "index": 1,
                "result": backtest.results,
            }

    async def scenario():
        import app.agent.backtest as module

        monkeypatch.setattr(module, "run_backtest", fake_service)
        model = ScriptedModel(tool=True)
        monkeypatch.setattr(
            worker,
            "build_agent",
            lambda: Agent(
                name="test", model=model, tools=[WebSearchTool(), backtest_tool]
            ),
        )
        await worker.run_agent_and_publish(run.id, str(user.id))
        final = store.load_snapshot(run.id)
        assert final["run"]["status"] == "completed"
        assert [row["type"] for row in final["messages"]] == [
            "user",
            "activity",
            "activity",
            "factor",
            "ai",
        ]
        assert [row["status"] for row in final["messages"]] == ["completed"] * 5
        assert calls == [run.id]
        assert final["messages"][1]["payload"]["action"]["query"] == "低波动因子"
        # SDK's native history includes the paired tool call and result.
        history = await PostgresSession(chat.sdk_session_id).get_items()
        assert any(item.get("type") == "function_call_output" for item in history)

    execute(scenario())


def test_failure_archives_partial_output_and_rotates_session(user, monkeypatch):
    chat, run = new_turn(user)

    async def scenario():
        model = ScriptedModel(failure=True)
        monkeypatch.setattr(
            worker, "build_agent", lambda: Agent(name="test", model=model)
        )
        await worker.run_agent_and_publish(run.id, str(user.id))
        result = store.load_snapshot(run.id)
        assert result["run"]["status"] == "failed"
        assert result["messages"][1]["status"] == "interrupted"
        assert result["messages"][1]["content"]
        _, followup = new_turn(user, chat=chat, turn=2, content="继续解释")
        model.failure = False
        await worker.run_agent_and_publish(followup.id, str(user.id))
        assert store.load_snapshot(followup.id)["run"]["status"] == "completed"
        with Session(engine) as db:
            assert db.get(Chat, chat.id).sdk_session_id != chat.sdk_session_id
        assert any("中断" in str(item) for item in model.inputs[-1])

    execute(scenario())


def test_recover_crashed_run_from_redis_and_final_snapshot_after_expiry(user):
    _, run = new_turn(user)

    async def scenario():
        initial = store.start_run(run.id)
        buffer = RunBuffer(initial, get_redis())
        await buffer.delta("msg_crash", "恢复🙂内容")
        await buffer.message("activity", "ws_crash", activity_type="web_search")
        await worker.recover_interrupted_runs()
        final = store.load_snapshot(run.id)
        assert final["run"]["status"] == "interrupted"
        assert final["messages"][1]["content"] == "恢复🙂内容"
        assert final["messages"][2]["status"] == "interrupted"
        await get_redis().delete(stream_key(str(run.id)))
        stream = stream_run(run.id, SimpleNamespace(is_disconnected=connected))
        assert "snapshot" in await anext(stream)
        assert "done" in await anext(stream)

    execute(scenario())


def test_archive_retry_does_not_regenerate_or_recharge(user, monkeypatch):
    _, run = new_turn(user)

    async def scenario():
        model = ScriptedModel()
        monkeypatch.setattr(
            worker, "build_agent", lambda: Agent(name="test", model=model)
        )
        original = store.settle_run
        attempts = []

        def fail_once(*args, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("temporary database failure")
            return original(*args, **kwargs)

        monkeypatch.setattr(store, "settle_run", fail_once)
        await worker.run_agent_and_publish(run.id, str(user.id))
        assert len(model.inputs) == 1
        assert len(attempts) == 2
        assert len(store.load_snapshot(run.id)["messages"]) == 2

    execute(scenario())


def test_api_idempotency_busy_authorization_and_history(client):
    body = {"content": "设计因子", "request_id": str(uuid.uuid4())}
    response = client.post("/api/v1/chats", json=body)
    assert response.status_code == 200, response.text
    first = response.json()
    assert (
        client.post("/api/v1/chats", json=body).json()["run"]["id"]
        == first["run"]["id"]
    )
    chat_id = first["chat"]["id"]
    listed = client.get("/api/v1/chats").json()
    assert listed[0]["id"] == chat_id
    assert listed[0]["active_run_id"] == first["run"]["id"]
    second = client.post(
        f"/api/v1/chats/{chat_id}/messages",
        json={"content": "继续", "request_id": str(uuid.uuid4())},
    )
    assert second.status_code == 409
    assert client.delete(f"/api/v1/chats/{chat_id}").status_code == 409
    store.settle_run(store.load_snapshot(uuid.UUID(first["run"]["id"])), "completed")
    follow_body = {"content": "解释一下", "request_id": str(uuid.uuid4())}
    follow = client.post(f"/api/v1/chats/{chat_id}/messages", json=follow_body).json()
    assert follow["run"]["turn_no"] == 2
    assert (
        client.post(f"/api/v1/chats/{chat_id}/messages", json=follow_body).json()[
            "run"
        ]["id"]
        == follow["run"]["id"]
    )
    history = client.get(f"/api/v1/chats/{chat_id}/messages?limit=1").json()
    assert history["active_run_id"] == follow["run"]["id"]
    assert history["next_before_turn"] == 2
    with Session(engine, expire_on_commit=False) as db:
        from app.models import User

        other = User(email=f"other-{uuid.uuid4()}@example.com")
        db.add(other)
        db.commit()
        from app.api.deps import get_current_user
        from app.main import app

        app.dependency_overrides[get_current_user] = lambda: other
        try:
            assert client.get(f"/api/v1/chats/{chat_id}/messages").status_code == 404
            assert (
                client.get(
                    f"/api/v1/chats/{chat_id}/events?run_id={follow['run']['id']}"
                ).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/chats/{chat_id}/runs/{follow['run']['id']}"
                ).status_code
                == 404
            )
        finally:
            db.delete(other)
            db.commit()


def test_session_window_keeps_paired_items(user, monkeypatch):
    chat, _ = new_turn(user)

    async def scenario():
        session = PostgresSession(chat.sdk_session_id)
        await session.add_items(
            [
                {"role": "user", "content": "old"},
                {"role": "assistant", "content": "old answer"},
                {"role": "user", "content": "new"},
                {
                    "type": "function_call",
                    "call_id": "call",
                    "name": "backtest",
                    "arguments": "{}",
                },
                {"type": "function_call_output", "call_id": "call", "output": "ok"},
                {"role": "assistant", "content": "new answer"},
            ]
        )
        monkeypatch.setattr(settings, "AGENT_CONTEXT_MAX_USER_TURNS", 1)
        items = await session.get_items(limit=1)
        assert len(items) == 4
        assert items[0]["content"] == "new"
        assert await session.pop_item() == {
            "role": "assistant",
            "content": "new answer",
        }
        await session.clear_session()
        assert await session.get_items() == []

    execute(scenario())


def test_custom_base_url_client_uses_responses_and_hosted_search(user, monkeypatch):
    import httpx
    from openai import AsyncOpenAI

    from app.agent import agent as agent_module

    _, run = new_turn(user)
    requests = []

    async def scenario():
        async def transport(request):
            requests.append(request)
            model = ScriptedModel()
            frames = []
            async for event in model.stream_response(None, []):
                frames.append(f"data: {event.model_dump_json()}\n\n")
            return httpx.Response(
                200,
                headers={"Content-Type": "text/event-stream"},
                content="".join(frames),
            )

        client = AsyncOpenAI(
            api_key="custom-test-key",
            base_url="https://custom.example/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        )
        monkeypatch.setattr(agent_module, "get_model_client", lambda: client)
        monkeypatch.setattr(worker, "build_agent", agent_module.build_agent)
        try:
            await worker.run_agent_and_publish(run.id, str(user.id))
        finally:
            await client.close()
        assert store.load_snapshot(run.id)["run"]["status"] == "completed"
        assert str(requests[0].url) == "https://custom.example/v1/responses"
        assert requests[0].headers["authorization"] == "Bearer custom-test-key"
        body = json.loads(requests[0].content)
        assert body["stream"] is True
        assert any(tool["type"] == "web_search" for tool in body["tools"])
        assert any(tool.get("name") == "backtest" for tool in body["tools"])

    execute(scenario())


def test_timeout_archives_and_allows_followup(user, monkeypatch):
    _, run = new_turn(user)

    async def scenario():
        gate = asyncio.Event()
        model = ScriptedModel(gate=gate)
        monkeypatch.setattr(
            worker, "build_agent", lambda: Agent(name="test", model=model)
        )
        monkeypatch.setattr(settings, "AGENT_RUN_TIMEOUT_SECONDS", 1)
        await worker.run_agent_and_publish(run.id, str(user.id))
        final = store.load_snapshot(run.id)
        assert final["run"]["status"] == "interrupted"
        assert final["run"]["error_code"] == "run_timeout"
        assert final["messages"][1]["content"] == "已生成中文🙂，因"

    execute(scenario())


def test_cursor_reconnect_redis_loss_and_two_chats_are_isolated(user):
    _, run1 = new_turn(user)
    _, run2 = new_turn(user)

    async def scenario():
        redis = get_redis()
        one = RunBuffer(store.start_run(run1.id), redis)
        two = RunBuffer(store.start_run(run2.id), redis)
        await one.delta("msg_one", "第一个🙂")
        await two.delta("msg_two", "第二个")
        cursor, events = await replay_events(redis, str(run1.id))
        restored = store.load_snapshot(run1.id)
        for _, kind, data in events:
            apply_event(restored, kind, data)
        assert restored["messages"][1]["content"] == "第一个🙂"
        stream = stream_run(run1.id, SimpleNamespace(is_disconnected=connected), cursor)
        await one.delta("msg_one", "续写")
        frame = await anext(stream)
        assert "event: delta" in frame
        assert json.loads(frame.split("data: ")[1])["text"] == "续写"
        await stream.aclose()
        # Lost stream cache is restored by the executor's next event as a full snapshot.
        await redis.delete(stream_key(str(run1.id)))
        await one.delta("msg_one", "恢复后")
        cursor, events = await replay_events(redis, str(run1.id))
        recovered = store.load_snapshot(run1.id)
        for _, kind, data in events:
            apply_event(recovered, kind, data)
        assert recovered["messages"][1]["content"] == "第一个🙂续写恢复后"
        assert "第二个" not in json.dumps(recovered, ensure_ascii=False)

    execute(scenario())


def test_backtest_limits_are_enforced_by_tool_not_prompt(user, monkeypatch):
    from agents.tool_context import ToolContext

    import app.agent.backtest as module
    from app.agent.backtest import ResearchContext

    _, run = new_turn(user)

    async def scenario():
        buffer = RunBuffer(store.start_run(run.id), get_redis())
        context = ResearchContext(user_id=str(user.id), run_id=run.id, buffer=buffer)
        calls = []

        def failed_service(*_args):
            calls.append(1)
            return {"ok": False, "error_code": "invalid_expression"}

        monkeypatch.setattr(module, "run_backtest", failed_service)
        monkeypatch.setattr(settings, "AGENT_BACKTEST_MAX_ATTEMPTS", 2)
        args = json.dumps({"factor_name": "test", "factor_expr": "bad"})
        for i in range(3):
            ctx = ToolContext(
                context=context,
                tool_name="backtest",
                tool_call_id=f"call-{i}",
                tool_arguments=args,
            )
            result = await backtest_tool.on_invoke_tool(ctx, args)
        assert len(calls) == 2
        assert result["error_code"] == "backtest_attempt_limit"
        assert all(
            row["status"] == "failed"
            for row in buffer.state["messages"]
            if row["type"] == "activity"
        )
        context.succeeded = True
        ctx = ToolContext(
            context=context,
            tool_name="backtest",
            tool_call_id="new-call",
            tool_arguments=args,
        )
        assert (await backtest_tool.on_invoke_tool(ctx, args))[
            "error_code"
        ] == "backtest_already_completed"
        assert len(calls) == 2

    execute(scenario())


def test_repeated_request_in_parallel_creates_one_chat(user, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi.testclient import TestClient

    from app.api.deps import get_current_user
    from app.api.routes import chats
    from app.main import app

    app.dependency_overrides[get_current_user] = lambda: user
    monkeypatch.setattr(chats, "launch_run", lambda *_args: None)
    body = {"content": "并发重试", "request_id": str(uuid.uuid4())}

    def send():
        # No lifespan: two request threads exercise the row lock on the same user.
        return TestClient(app).post("/api/v1/chats", json=body)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: send(), range(2)))
        assert [response.status_code for response in responses] == [200, 200]
        assert responses[0].json()["run"]["id"] == responses[1].json()["run"]["id"]
        with Session(engine) as db:
            assert len(db.exec(select(Chat).where(Chat.user_id == user.id)).all()) == 1
    finally:
        app.dependency_overrides.clear()


def test_duplicate_executors_claim_a_queued_run_once(user):
    from concurrent.futures import ThreadPoolExecutor

    _, run = new_turn(user)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.start_run(run.id), range(2)))
    assert sum(result is not None for result in results) == 1
    assert store.load_snapshot(run.id)["run"]["status"] == "running"
