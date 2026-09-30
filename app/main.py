"""Dashboard backend: serves pinned, verified evidence runs for replay.

Replay happens in the viewer's browser (one tick every 2 seconds, under the
viewer's control). Every endpoint accepts ``upto`` / ``tick`` so the dashboard
and assistant only ever see what the evidence says up to the tick on screen.
"""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.assistant import AssistantError, GeminiChat, ask as assistant_ask
from app.assistant_tools import Toolbox
from app.evidence import RunEvidence, load_runs_config, store_from_env, verify_run
from app.state import core_upto, explanations_upto, state_at
from engine.registry import load_registry
from explain.facts import EvidenceIntegrityError
from projects import ProjectError, find_project, list_projects

app = FastAPI(title="TwinEvidence")

_cache: dict[str, RunEvidence] = {}
_lock = threading.Lock()
VERIFY_LIMIT_PER_MINUTE = int(os.environ.get("VERIFY_LIMIT_PER_MINUTE", "6"))
_verify_calls: dict[str, deque] = defaultdict(deque)


def _pinned(run: str) -> dict:
    cfg = load_runs_config()
    for r in cfg["runs"]:
        if r["run"] == run:
            return r
    raise HTTPException(404, f"unknown run {run!r}")


def _project_or_404(project_id: str):
    project = find_project(project_id)
    if project is None:
        raise HTTPException(404, f"unknown project {project_id!r}")
    return project


def _project_summary(p) -> dict:
    return {"project_id": p.project_id, "name": p.name, "domain": p.domain, "summary": p.summary}


def _project_detail(p) -> dict:
    reg = load_registry(p)
    return {
        **_project_summary(p),
        "gap_metric": p.gap_metric,
        "entry_twins": [reg.products[t].operational_twin_id for t in p.entry_twins],
        # Twins below are in processing order (feeding twins first); display fields come from the project file.
        "twins": {
            tw.operational_twin_id: {
                "twin_type": tw.twin_type, "design_twin_id": tw.design_twin_id, "vendor": tw.vendor,
                "twin_mode": tw.twin_mode, "name": p.twin(tw.twin_type).name, "role": p.twin(tw.twin_type).role,
                "registry_id": p.twin(tw.twin_type).registry_id, "asset_kind": p.twin(tw.twin_type).asset_kind,
                "channels": [{"channel_id": c.channel_id, "name": c.name, "unit": c.unit, "direction": c.direction,
                              "envelope": [c.env_min, c.env_max], "tolerance_pct": c.tolerance_pct}
                             for c in tw.channels],
            } for tw in reg.products.values()
        },
        "system_twin": {
            "twin_id": reg.system.operational_system_twin_id,
            "name": p.system_name,
            "constituents": [reg.products[t].operational_twin_id for t in reg.system.constituents],
            "outputs_come_from": [reg.products[t].operational_twin_id for t in reg.system.output_constituents],
            "connections": list(reg.system.connections),
        },
    }


def evidence(run: str) -> RunEvidence:
    with _lock:
        if run not in _cache:
            pin = _pinned(run)
            try:
                _cache[run] = verify_run(store_from_env(), run, pin["title"], pin["core_ledger_head_hash"])
            except EvidenceIntegrityError as exc:
                raise HTTPException(503, f"evidence failed verification and will not be served: {exc}")
        return _cache[run]


def _upto(ev: RunEvidence, upto: int | None) -> int:
    return len(ev.timeline) - 1 if upto is None else upto


def _rate_limited(store: dict, key: str, limit: int, window_s: float) -> bool:
    now, calls = time.monotonic(), store[key]
    while calls and now - calls[0] > window_s:
        calls.popleft()
    if len(calls) >= limit:
        return True
    calls.append(now)
    return False


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/projects")
def projects() -> dict:
    return {"projects": [_project_summary(p) for p in list_projects()]}


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict:
    return _project_detail(_project_or_404(project_id))


@app.get("/api/registry")
def registry() -> dict:
    """Twins registered on the platform by their owners. Each entry is read from the twin's own
    config file (never modified), so the interface shown is exactly what the owner declared."""
    entries: dict[str, dict] = {}
    for p in list_projects():
        for tw in p.twins:
            if not tw.registry_id:
                continue
            if tw.registry_id in entries:
                entries[tw.registry_id]["used_by"].append(p.project_id)
                continue
            cfg = tw.config
            entries[tw.registry_id] = {
                "registry_id": tw.registry_id, "name": f"{tw.name} twin", "vendor": cfg["vendor"],
                "asset_kind": tw.asset_kind, "domain": p.domain, "role": tw.role,
                "summary": cfg.get("description", ""), "modes": [cfg["twin_mode"]],
                "channels": [{"id": c["channel_id"], "name": c["name"], "unit": c["unit"], "direction": c["direction"],
                              "declared_range": [c["envelope"]["min"], c["envelope"]["max"]],
                              "tolerance_pct": c.get("tolerance_pct")} for c in cfg["channels"]],
                "used_by": [p.project_id],
            }
    return {"entries": list(entries.values())}


@app.get("/api/projects/{project_id}/runs")
def project_runs(project_id: str) -> dict:
    _project_or_404(project_id)
    return runs(project_id=project_id)


@app.get("/api/runs")
def runs(project_id: str | None = None) -> dict:
    cfg = load_runs_config()
    rows = cfg["runs"] if project_id is None else [r for r in cfg["runs"] if r.get("project_id") == project_id]
    return {"default": cfg["default"], "runs": [{"run": r["run"], "title": r["title"],
                                                  "project_id": r.get("project_id"),
                                                  "core_ledger_head_hash": r["core_ledger_head_hash"]} for r in rows]}


@app.get("/api/runs/{run}/meta")
def meta(run: str) -> dict:
    ev = evidence(run)
    pin = _pinned(run)
    started = next(e["payload"] for e in ev.core if e["entry_type"] == "run_started")
    project_fields = {}
    if pin.get("project_id"):
        detail = _project_detail(_project_or_404(pin["project_id"]))
        project_fields = {"project_id": detail["project_id"], "twins": detail["twins"],
                          "system_twin": detail["system_twin"], "entry_twins": detail["entry_twins"]}
    return {
        "run": run, "title": ev.title, "ticks": len(ev.timeline), "tick_seconds": ev.tick_seconds,
        "start_time": ev.manifest["start_time"], "scenario": started["scenario"], "seed": started["seed"],
        "escalation_protocol": started["escalation_protocol"],
        "ai_model": ev.manifest.get("ai_model"), "code_commit": ev.manifest.get("code_commit"),
        "evidence_source": ev.source, "verification": ev.verification,
        "display_ranges": _display_ranges(ev),
        **project_fields,
    }


@app.get("/api/runs/{run}/view")
def view(run: str, tick: int) -> dict:
    """Everything the dashboard shows for one tick, cut off at that tick."""
    ev = evidence(run)
    t = max(0, min(tick, len(ev.timeline) - 1))
    return {
        "state": state_at(ev, t),
        "readings": [r for r in ev.readings if r["tick"] <= t],
        "timeline": ev.timeline[: t + 1],
        "ledger": core_upto(ev, t),
        "explanations": explanations_upto(ev, t),
    }


def _display_ranges(ev: RunEvidence) -> dict:
    """Fixed chart axes for the whole run, so charts never rescale mid-replay."""
    out: dict[str, dict] = {}
    for r in ev.readings:
        key = f"{r['twin_id']}/{r['channel_id']}"
        for v in (r["physical_value"], r["predicted_value"]):
            if isinstance(v, (int, float)) and v == v:
                lo, hi = out.get(key, {}).get("min", v), out.get(key, {}).get("max", v)
                out[key] = {"min": min(lo, v), "max": max(hi, v)}
    gaps = [g.get("gap_pct") for row in ev.timeline for tw in row["classifications"].values()
            for g in tw.values() if g.get("gap_pct") is not None]
    out["gap_pct_max"] = max(gaps) if gaps else 0
    return out


@app.get("/api/runs/{run}/state")
def state(run: str, tick: int | None = None) -> dict:
    ev = evidence(run)
    return state_at(ev, _upto(ev, tick))


@app.get("/api/runs/{run}/timeline")
def timeline(run: str, upto: int | None = None) -> list[dict]:
    ev = evidence(run)
    return ev.timeline[: _upto(ev, upto) + 1]


@app.get("/api/runs/{run}/readings")
def readings(run: str, upto: int | None = None, twin_id: str | None = None) -> list[dict]:
    ev = evidence(run)
    last = _upto(ev, upto)
    return [r for r in ev.readings if r["tick"] <= last and (twin_id is None or r["twin_id"] == twin_id)]


@app.get("/api/runs/{run}/ledger")
def ledger(run: str, upto: int | None = None) -> list[dict]:
    ev = evidence(run)
    return core_upto(ev, _upto(ev, upto))


@app.get("/api/runs/{run}/explanations")
def explanations(run: str, upto: int | None = None) -> list[dict]:
    ev = evidence(run)
    return explanations_upto(ev, _upto(ev, upto))


@app.post("/api/runs/{run}/verify")
def verify(run: str, request: Request) -> dict:
    """Re-fetch every file from the evidence store and re-check it now."""
    if _rate_limited(_verify_calls, _client(request), VERIFY_LIMIT_PER_MINUTE, 60):
        raise HTTPException(429, "too many verification requests; try again in a minute")
    pin = _pinned(run)
    try:
        fresh = verify_run(store_from_env(), run, pin["title"], pin["core_ledger_head_hash"])
    except EvidenceIntegrityError as exc:
        return {"valid": False, "error": str(exc)}
    return fresh.verification


ASK_PER_MINUTE = int(os.environ.get("ASK_PER_MINUTE", "6"))
ASK_PER_DAY = int(os.environ.get("ASK_PER_DAY", "60"))
ASK_GLOBAL_PER_HOUR = int(os.environ.get("ASK_GLOBAL_PER_HOUR", "300"))
_ask_minute: dict[str, deque] = defaultdict(deque)
_ask_day: dict[str, deque] = defaultdict(deque)
_ask_global: dict[str, deque] = defaultdict(deque)
_chat = None


def get_chat():
    global _chat
    if _chat is None:
        _chat = GeminiChat()
    return _chat


class Turn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    text: str = Field(max_length=4000)


class AskRequest(BaseModel):
    tick: int = Field(ge=0)
    question: str = Field(min_length=1, max_length=800)
    history: list[Turn] = Field(default_factory=list, max_length=8)
    motor_only: bool = False


@app.post("/api/runs/{run}/ask")
def ask(run: str, body: AskRequest, request: Request) -> dict:
    """Grounded, read-only Q&A about the evidence up to ``tick``."""
    who = _client(request)
    if _rate_limited(_ask_global, "all", ASK_GLOBAL_PER_HOUR, 3600):
        raise HTTPException(429, "the assistant is busy; please try again later")
    if _rate_limited(_ask_minute, who, ASK_PER_MINUTE, 60) or _rate_limited(_ask_day, who, ASK_PER_DAY, 86400):
        raise HTTPException(429, "question limit reached; please wait a little before asking again")
    ev = evidence(run)
    pin = _pinned(run)
    project = _project_or_404(pin["project_id"]) if pin.get("project_id") else None
    toolbox = Toolbox(ev, body.tick, body.motor_only, project)
    try:
        return assistant_ask(get_chat(), toolbox, body.question, [t.model_dump() for t in body.history])
    except AssistantError as exc:
        raise HTTPException(502, str(exc))
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "the assistant is unavailable right now")


# The built React dashboard: app/static in the container, web/dist in development.
_STATIC = next((d for d in (Path(__file__).parent / "static", Path(__file__).parent.parent / "web" / "dist")
                if (d / "index.html").exists()), None)
if _STATIC:
    app.mount("/", StaticFiles(directory=_STATIC, html=True), name="dashboard")
else:
    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return "<p>Dashboard not built. Run <code>npm run build</code> in <code>web/</code>.</p>"
