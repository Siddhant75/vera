import asyncio
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import Settings
from app.events import bus, format_sse
from app.llm import TokenFactoryClient
from app.memory import Memory
from app.pipeline.orchestrator import run_research
from app.search import TavilyClient


class ProfileIn(BaseModel):
    persona: str = "engineer"
    trusted_sources: list[str] = []
    excluded_sources: list[str] = []


class ResearchIn(BaseModel):
    brief: str
    topic: str = ""
    persona: str = ""
    delta: bool = False


class FeedbackIn(BaseModel):
    run_id: str
    claim_id: str
    helpful: bool = True


def create_app(llm: TokenFactoryClient, tavily: TavilyClient, memory: Memory) -> FastAPI:
    app = FastAPI(title="Vera")
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/profile")
    async def get_profile():
        return memory.get_profile()

    @app.post("/api/profile")
    async def post_profile(p: ProfileIn):
        memory.set_profile(p.persona, p.trusted_sources, p.excluded_sources)
        return memory.get_profile()

    app.state.background_tasks = set()

    @app.post("/api/research")
    async def post_research(r: ResearchIn):
        run_id = uuid.uuid4().hex[:12]

        async def emit(event: dict):
            await bus.emit(run_id, event)

        task = asyncio.create_task(run_research(run_id, r.brief, r.persona, r.topic, r.delta,
                                                llm, tavily, memory, emit))
        app.state.background_tasks.add(task)
        task.add_done_callback(app.state.background_tasks.discard)
        return {"run_id": run_id}

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str):
        async def stream():
            async for event in bus.subscribe(run_id):
                yield format_sse(event)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/report/{run_id}")
    async def report(run_id: str):
        rep = memory.get_report(run_id)
        return rep or {"error": "report not found"}

    @app.post("/api/feedback")
    async def feedback(f: FeedbackIn):
        memory.add_feedback(f.run_id, f.claim_id, f.helpful)
        return {"ok": True}

    @app.get("/api/telemetry")
    async def telemetry_snapshot():
        from app.telemetry import telemetry
        return telemetry.snapshot()

    return app


def build_app() -> FastAPI:
    settings = Settings()
    if not settings.planner_model or len(settings.verifier_models) < 2:
        raise ValueError(
            "PLANNER_MODEL and VERIFIER_MODELS (>=2, excluding planner) must be configured in .env"
        )
    llm = TokenFactoryClient(
        settings.token_factory_base_url,
        settings.token_factory_api_key,
        planner_model=settings.planner_model,
        verifier_models=settings.verifier_models,
    )
    tavily = TavilyClient(settings.tavily_api_key)
    memory = Memory(settings.db_path)
    return create_app(llm, tavily, memory)


try:
    app = build_app()
except ValueError:
    app = None  # models unconfigured: tests import fine; `uvicorn app.main:app` fails clearly at start
