import asyncio
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

try:
    import truststore
    truststore.inject_into_ssl()  # machine-local TLS stacks (e.g. AV interception) break httpx
except ImportError:
    pass

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
    role_context: str = ""
    goals: str = ""
    expertise_notes: str = ""


class ResearchIn(BaseModel):
    brief: str
    topic: str = ""
    persona: str = ""
    delta: bool = False


class FeedbackIn(BaseModel):
    run_id: str
    claim_id: str
    helpful: bool = True
    claim_text: str = ""


def create_app(llm: TokenFactoryClient, tavily: TavilyClient, memory: Memory,
               daily_token_budget: int = 0, watch_interval_minutes: int = 0) -> FastAPI:
    from contextlib import asynccontextmanager

    state = {"memory": memory, "llm": llm, "tavily": tavily,
             "daily_token_budget": daily_token_budget,
             "webhook_url": Settings().digest_webhook_url,
             "emit": None}

    async def _emit_any(event: dict):
        await bus.emit(event["run_id"], event)

    state["emit"] = _emit_any

    @asynccontextmanager
    async def lifespan(_app):
        task = None
        if watch_interval_minutes > 0:  # 0 = watcher off (tests, local dev)
            from app.watcher import watch_loop
            task = asyncio.create_task(watch_loop(state, watch_interval_minutes))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Vera", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/api/profile")
    async def get_profile():
        return memory.get_profile()

    @app.post("/api/profile")
    async def post_profile(p: ProfileIn):
        memory.set_profile(p.persona, p.trusted_sources, p.excluded_sources,
                           role_context=p.role_context, goals=p.goals,
                           expertise_notes=p.expertise_notes)
        return memory.get_profile()

    app.state.background_tasks = set()

    @app.post("/api/research")
    async def post_research(r: ResearchIn):
        from app.telemetry import telemetry
        if daily_token_budget and telemetry.snapshot()["tf_tokens"] >= daily_token_budget:
            return JSONResponse(status_code=429, content={
                "error": f"daily token budget exhausted ({daily_token_budget}); come back tomorrow"})
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
        memory.add_feedback(f.run_id, f.claim_id, f.helpful, claim_text=f.claim_text)
        return {"ok": True}

    # ---- Private context notes ----
    class NoteIn(BaseModel):
        topic: str
        content: str

    @app.post("/api/notes")
    async def post_note(n: NoteIn):
        if not n.topic.strip() or not n.content.strip():
            return JSONResponse(status_code=422, content={"error": "topic and content required"})
        from app.privacy import scan_for_secrets
        nid, warnings = memory.add_note(n.topic.strip(), n.content)
        return {"id": nid, "warnings": warnings}

    @app.get("/api/notes")
    async def get_notes(topic: str = ""):
        if not topic.strip():
            return JSONResponse(status_code=422, content={"error": "topic required"})
        return memory.list_notes(topic.strip())

    @app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: int):
        memory.delete_note(note_id)
        return {"ok": True}

    # ---- Memory control (your data under your control) ----
    @app.get("/api/memory")
    async def get_memory():
        from app.telemetry import telemetry
        return {"runs": memory.list_runs(), "telemetry": telemetry.snapshot()}

    @app.delete("/api/runs/{run_uuid}")
    async def delete_run(run_uuid: str):
        memory.delete_run(run_uuid)
        return {"ok": True}

    @app.delete("/api/memory")
    async def purge_memory():
        memory.purge_all()
        return {"ok": True}

    @app.get("/api/telemetry")
    async def telemetry_snapshot():
        from app.telemetry import telemetry
        return telemetry.snapshot()

    # ---- Topic Watch (always-on) ----
    class WatchIn(BaseModel):
        topic: str
        brief: str
        persona: str = "engineer"
        interval_hours: int = 6

    @app.post("/api/watch")
    async def post_watch(w: WatchIn):
        if not w.topic.strip() or not w.brief.strip():
            return JSONResponse(status_code=422, content={"error": "topic and brief required"})
        wid = memory.add_watch(w.topic.strip(), w.brief.strip(), w.persona, w.interval_hours)
        return {"id": wid}

    @app.get("/api/watch")
    async def get_watch():
        return memory.list_watches()

    @app.delete("/api/watch/{watch_id}")
    async def delete_watch(watch_id: int):
        memory.remove_watch(watch_id)
        return {"ok": True}

    # ---- Skills (reusable research recipes) ----
    class SkillIn(BaseModel):
        name: str
        persona: str = "engineer"
        brief_template: str
        topic: str = ""
        trusted_sources: list[str] = []
        excluded_sources: list[str] = []

    @app.post("/api/skills")
    async def post_skill(s: SkillIn):
        if not s.name.strip() or not s.brief_template.strip():
            return JSONResponse(status_code=422, content={"error": "name and brief_template required"})
        sid = memory.upsert_skill(s.name.strip(), s.persona, s.brief_template.strip(), s.topic.strip(),
                                  trusted=s.trusted_sources, excluded=s.excluded_sources)
        return {"id": sid}

    @app.get("/api/skills")
    async def get_skills():
        return memory.list_skills()

    @app.delete("/api/skills/{name}")
    async def delete_skill(name: str):
        memory.delete_skill(name)
        return {"ok": True}

    class SkillRunIn(BaseModel):
        vars: dict[str, str] = {}
        watch: bool = False
        interval_hours: int = 6

    @app.post("/api/skills/{name}/run")
    async def run_skill(name: str, s: SkillRunIn | None = None):
        skill = next((sk for sk in memory.list_skills() if sk["name"] == name), None)
        if not skill:
            return JSONResponse(status_code=404, content={"error": "skill not found"})
        s = s or SkillRunIn()
        from app.skills import auto_vars, fill_template
        filled_brief = fill_template(skill["brief_template"], s.vars, auto_vars(skill["topic"]))
        filled_topic = skill["topic"] or s.vars.get("topic", "")
        memory.set_profile(skill["persona"], skill["trusted_sources"], skill["excluded_sources"])
        run_resp = await post_research(ResearchIn(brief=filled_brief, topic=filled_topic,
                                                  persona=skill["persona"]))
        resp = dict(run_resp)
        if s.watch and not isinstance(run_resp, JSONResponse):
            wid = memory.add_watch(filled_topic or filled_brief[:40], filled_brief,
                                   skill["persona"], s.interval_hours)
            resp["watch_id"] = wid
        return resp

    return app


def build_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
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
    return create_app(llm, tavily, memory, daily_token_budget=settings.daily_token_budget,
                      watch_interval_minutes=settings.watch_interval_minutes)


try:
    app = build_app()
except ValueError:
    app = None  # models unconfigured: tests import fine; `uvicorn app.main:app` fails clearly at start
