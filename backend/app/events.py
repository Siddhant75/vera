import asyncio
import json


def format_sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


class EventBus:
    """Per-run event store with replay. Subscribe yields stored events, then live ones.
    Registration and emission share a lock so no event slips between replay and live."""

    def __init__(self):
        self._events: dict[str, list[dict]] = {}
        self._queues: dict[str, list[asyncio.Queue]] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, run_id: str) -> asyncio.Lock:
        if run_id not in self._locks:
            self._locks[run_id] = asyncio.Lock()
        return self._locks[run_id]

    async def emit(self, run_id: str, event: dict) -> None:
        async with self._lock(run_id):
            self._events.setdefault(run_id, []).append(event)
            for q in self._queues.get(run_id, []):
                await q.put(event)

    async def subscribe(self, run_id: str):
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock(run_id):
            stored = list(self._events.get(run_id, []))
            self._queues.setdefault(run_id, []).append(q)
        for e in stored:
            yield e
        while True:
            event = await q.get()
            if event.get("stage") == "__end__":
                break
            yield event

    async def close(self, run_id: str) -> None:
        async with self._lock(run_id):
            for q in self._queues.get(run_id, []):
                await q.put({"stage": "__end__"})


bus = EventBus()
