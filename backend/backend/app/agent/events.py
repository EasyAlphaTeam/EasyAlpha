"""A deterministic UI projection used both live and while replaying Redis."""

import asyncio
import copy
import uuid
from typing import Any

from app.core.redis import add_event, stream_key
from app.models import get_datetime_utc


def apply_event(snapshot: dict, kind: str, data: dict) -> None:
    if kind == "snapshot":
        snapshot.clear()
        snapshot.update(copy.deepcopy(data))
    elif kind == "run":
        if data["revision"] > snapshot["run"].get("revision", -1):
            snapshot["run"] = copy.deepcopy(data)
    elif kind == "message":
        rows = snapshot["messages"]
        previous = next((m for m in rows if m["id"] == data["id"]), None)
        if previous is None:
            rows.append(copy.deepcopy(data))
        elif data["revision"] > previous["revision"]:
            previous.clear()
            previous.update(copy.deepcopy(data))
        rows.sort(key=lambda m: m["seq"])
    elif kind == "delta":
        message = next(m for m in snapshot["messages"] if m["id"] == data["message_id"])
        if data["revision"] <= message["revision"]:
            return
        content = message["content"] or ""
        if data["start_offset"] > len(content):
            raise ValueError("stream_gap")
        overlap = max(0, len(content) - data["start_offset"])
        message["content"] = content + data["text"][overlap:]
        message["revision"] = data["revision"]
        message["updated_at"] = data["updated_at"]


class RunBuffer:
    """Never writes generated ChatMessage rows before the run is settled."""

    def __init__(self, snapshot: dict, redis):
        self.state = copy.deepcopy(snapshot)
        self.redis = redis
        self.lock = asyncio.Lock()

    @property
    def run_id(self) -> str:
        return self.state["run"]["id"]

    def snapshot(self) -> dict:
        return copy.deepcopy(self.state)

    def find(self, kind: str, source: str) -> dict | None:
        return next(
            (
                m
                for m in self.state["messages"]
                if m["type"] == kind and m["source_item_id"] == source
            ),
            None,
        )

    async def _publish(self, kind: str, data: dict) -> None:
        if not await self.redis.exists(stream_key(self.run_id)):
            await add_event(self.redis, self.run_id, "snapshot", self.snapshot())
        await add_event(self.redis, self.run_id, kind, data)

    async def message(self, kind: str, source: str, **changes: Any) -> dict:
        async with self.lock:
            row = self.find(kind, source)
            now = get_datetime_utc().isoformat()
            if row is None:
                row: dict[str, Any] = {
                    "id": str(uuid.uuid4()),
                    "run_id": self.run_id,
                    "seq": max((m["seq"] for m in self.state["messages"]), default=-1)
                    + 1,
                    "type": kind,
                    "source_item_id": source,
                    "content": None,
                    "activity_type": None,
                    "status": "running",
                    "payload": {},
                    "revision": 0,
                    "created_at": now,
                    "updated_at": now,
                    "finished_at": None,
                }
                self.state["messages"].append(row)
            row.update(changes)
            row["revision"] += 1
            row["updated_at"] = now
            if row["status"] in ("completed", "failed", "interrupted"):
                row["finished_at"] = now
            await self._publish("message", copy.deepcopy(row))
            return copy.deepcopy(row)

    async def delta(self, source: str, text: str) -> None:
        if self.find("ai", source) is None:
            await self.message("ai", source, content="")
        async with self.lock:
            row = self.find("ai", source)
            assert row is not None
            start = len(row["content"] or "")
            row["content"] = (row["content"] or "") + text
            row["revision"] += 1
            row["updated_at"] = get_datetime_utc().isoformat()
            await self._publish(
                "delta",
                {
                    "run_id": self.run_id,
                    "message_id": row["id"],
                    "revision": row["revision"],
                    "start_offset": start,
                    "end_offset": len(row["content"]),
                    "text": text,
                    "updated_at": row["updated_at"],
                },
            )

    async def finish_entries(self, status: str) -> None:
        for row in list(self.state["messages"]):
            if row["status"] in ("pending", "running"):
                await self.message(row["type"], row["source_item_id"], status=status)

    async def run_update(self, run: dict) -> None:
        async with self.lock:
            self.state["run"] = run
            await self._publish("run", run)

    async def handle(self, event) -> None:
        if event.type == "raw_response_event":
            data = event.data
            kind = data.type
            if kind == "response.output_text.delta":
                await self.delta(data.item_id, data.delta)
            elif kind in ("response.output_item.added", "response.output_item.done"):
                item = data.item
                if item.type == "message":
                    if kind.endswith(".added"):
                        if self.find("ai", item.id) is None:
                            await self.message("ai", item.id, content="")
                    else:
                        await self.complete_message(item)
                elif item.type == "web_search_call":
                    payload = item.model_dump(mode="json")
                    await self.message(
                        "activity",
                        item.id,
                        activity_type="web_search",
                        status=("completed" if item.status == "completed" else "failed")
                        if kind.endswith(".done")
                        else "running",
                        payload={"tool_name": "web_search", **payload},
                    )
            elif kind in (
                "response.web_search_call.in_progress",
                "response.web_search_call.searching",
                "response.web_search_call.completed",
            ):
                await self.message(
                    "activity",
                    data.item_id,
                    activity_type="web_search",
                    status="completed" if kind.endswith(".completed") else "running",
                )
        elif (
            event.type == "run_item_stream_event"
            and event.name == "message_output_created"
        ):
            await self.complete_message(event.item.raw_item)

    async def complete_message(self, item) -> None:
        content, annotations, parts = "", [], []
        for part in item.content:
            raw = part.model_dump(mode="json")
            parts.append(raw)
            if part.type == "output_text":
                for annotation in part.annotations:
                    entry = annotation.model_dump(mode="json")
                    if "start_index" in entry:
                        entry["start_index"] += len(content)
                        entry["end_index"] += len(content)
                    annotations.append(entry)
                content += part.text
            elif part.type == "refusal":
                content += part.refusal
        await self.message(
            "ai",
            item.id,
            content=content,
            status="completed",
            payload={"annotations": annotations, "content_parts": parts},
        )
