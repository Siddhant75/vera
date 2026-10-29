import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.memory import Memory, domain_of
from app.pipeline.orchestrator import run_research
from app.pipeline.planner import topic_key
from app.search import TavilyClient
from app.llm import TokenFactoryClient

log = logging.getLogger("vera.watcher")


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


async def probe_changed(memory: Memory, tavily: TavilyClient, watch: dict) -> bool:
    """Freshness probe: 1 Tavily search, zero LLM. New top-5 URL vs last run's saved
    sources = changed. No prior run (watch or topic) = first watch, immediately changed."""
    last_uuid = watch.get("last_run_uuid") or memory.latest_run_uuid_for_topic(
        topic_key(watch["topic"]))
    if not last_uuid:
        return True
    results = await tavily.search(watch["topic"], max_results=5, role="grounding")
    results = [r for r in results
               if memory.trust_multiplier(domain_of(r["url"])) > 0.0]  # same trust semantics as searcher/verifier
    known = {s["url"] for s in memory.get_sources(last_uuid)}
    return any(r["url"] not in known for r in results)


async def _post_digest(text: str, payload: dict, url: str) -> None:
    """Operator-set webhook only (SSRF-safe: never from API input). 10s timeout.
    HTTP-level failures raise — the caller logs them; delivery truthfulness matters."""
    import httpx
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json={"text": text, **payload})
        resp.raise_for_status()


async def check_due_watches(memory: Memory, llm: TokenFactoryClient, tavily: TavilyClient,
                            emit, probe_fn=probe_changed, daily_token_budget: int = 0,
                            webhook_url: str = "",
                            now: datetime | None = None) -> None:
    from app.telemetry import telemetry
    now = now or datetime.now(timezone.utc)
    for watch in memory.list_watches():
        last = _parse(watch.get("last_checked"))
        due = last is None or now - last >= timedelta(hours=watch["interval_hours"])
        if not due:
            continue
        try:
            changed = await probe_fn(memory, tavily, watch)
        except Exception as exc:
            log.warning("probe failed for watch %s (%s): %s", watch["id"], watch["topic"], exc)
            memory.set_watch_result(watch["id"], "error", checked_at=now.isoformat(timespec="seconds"))
            continue  # one bad watch never blocks the others
        if not changed:
            memory.set_watch_result(watch["id"], "no-change", checked_at=now.isoformat(timespec="seconds"))
            continue
        if daily_token_budget and telemetry.snapshot()["tf_tokens"] >= daily_token_budget:
            memory.set_watch_result(watch["id"], "budget-limited", checked_at=now.isoformat(timespec="seconds"))
            continue
        report = await run_research(f"watch-{watch['id']}-{now.strftime('%Y%m%d%H%M%S')}",
                                    watch["brief"], watch["persona"], watch["topic"], True,
                                    llm, tavily, memory, emit)
        if report is None:
            memory.set_watch_result(watch["id"], "error", checked_at=now.isoformat(timespec="seconds"))
            continue  # run_research already emitted its own error event; retry next cycle
        digest_text = f"Vera update on '{watch['topic']}': {len(report.changes)} changes — " \
            + ("; ".join(report.changes[:8]) if report.changes else "fresh research run")
        memory.set_watch_result(watch["id"], "changed", run_uuid=_last_run(memory, watch),
                                changes=len(report.changes), checked_at=now.isoformat(timespec="seconds"),
                                digest=digest_text)
        if webhook_url:
            try:
                await _post_digest(digest_text, {"topic": watch["topic"], "changes": report.changes[:8],
                                                 "verdict_summary": report.verdict_summary,
                                                 "run_uuid": _last_run(memory, watch)}, webhook_url)
            except Exception as exc:
                log.warning("webhook delivery failed for watch %s: %s", watch["id"], exc)


def _last_run(memory: Memory, watch: dict) -> str:
    # run_research generated its own run uuid (watch-<id>-<ts> prefix); recover it by topic key
    return memory.latest_run_uuid_for_topic(topic_key(watch["topic"])) or ""


async def watch_loop(app_state, interval_minutes: int = 30) -> None:
    while True:
        try:
            await check_due_watches(app_state["memory"], app_state["llm"], app_state["tavily"],
                                    emit=app_state["emit"], daily_token_budget=app_state["daily_token_budget"],
                                    webhook_url=app_state.get("webhook_url", ""))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("watch cycle failed; retrying next tick")
        await asyncio.sleep(max(1, interval_minutes) * 60)
