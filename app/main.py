"""Dashboard backend: serves pinned, verified evidence runs for replay.

Replay happens in the viewer's browser (one tick every 2 seconds, under the
viewer's control). Every endpoint accepts ``upto`` / ``tick`` so the dashboard
and assistant only ever see what the evidence says up to the tick on screen.
"""

from __future__ import annotations

import os
import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.evidence import RunEvidence, load_runs_config, store_from_env, verify_run
from app.state import core_upto, explanations_upto, state_at
from engine.registry import load_registry
from explain.facts import EvidenceIntegrityError

app = FastAPI(title="Digital Twin Assurance")

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


def _client(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/runs")
def runs() -> dict:
    cfg = load_runs_config()
    return {"default": cfg["default"], "runs": [{"run": r["run"], "title": r["title"],
                                                  "core_ledger_head_hash": r["core_ledger_head_hash"]} for r in cfg["runs"]]}


@app.get("/api/runs/{run}/meta")
def meta(run: str) -> dict:
    ev = evidence(run)
    reg = load_registry()
    started = next(e["payload"] for e in ev.core if e["entry_type"] == "run_started")
    return {
        "run": run, "title": ev.title, "ticks": len(ev.timeline), "tick_seconds": ev.tick_seconds,
        "start_time": ev.manifest["start_time"], "scenario": started["scenario"], "seed": started["seed"],
        "escalation_protocol": started["escalation_protocol"],
        "ai_model": ev.manifest.get("ai_model"), "code_commit": ev.manifest.get("code_commit"),
        "evidence_source": ev.source, "verification": ev.verification,
        "twins": {
            p.operational_twin_id: {
                "twin_type": p.twin_type, "design_twin_id": p.design_twin_id, "vendor": p.vendor,
                "channels": [{"channel_id": c.channel_id, "name": c.name, "unit": c.unit, "direction": c.direction,
                              "envelope": [c.env_min, c.env_max], "tolerance_pct": c.tolerance_pct}
                             for c in p.channels],
            } for p in reg.products.values()
        },
        "system_twin": {
            "twin_id": reg.system.operational_system_twin_id,
            "constituents": [reg.products[t].operational_twin_id for t in reg.system.constituents],
            "outputs_come_from": [reg.products[t].operational_twin_id for t in reg.system.output_constituents],
            "connections": list(reg.system.connections),
        },
    }


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
    now, calls = time.monotonic(), _verify_calls[_client(request)]
    while calls and now - calls[0] > 60:
        calls.popleft()
    if len(calls) >= VERIFY_LIMIT_PER_MINUTE:
        raise HTTPException(429, "too many verification requests; try again in a minute")
    calls.append(now)
    pin = _pinned(run)
    try:
        fresh = verify_run(store_from_env(), run, pin["title"], pin["core_ledger_head_hash"])
    except EvidenceIntegrityError as exc:
        return {"valid": False, "error": str(exc)}
    return fresh.verification


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Digital Twin Assurance</title>
<style>body{font:14px system-ui,sans-serif;margin:16px;max-width:900px}code{font-size:12px}
li{margin:4px 0}.ok{color:#137333}.bad{color:#b3261e}</style></head><body>
<h1 style="font-size:18px">Digital Twin Assurance: evidence API (Phase 3a)</h1>
<p>The dashboard is being built. The evidence runs below are pinned by ledger fingerprint and verified before they are served.</p>
<ul id="runs"></ul>
<script>
async function go(){
  const r=await (await fetch('api/runs')).json();
  document.getElementById('runs').innerHTML=r.runs.map(x=>`<li><b>${x.title}</b> <code>${x.core_ledger_head_hash.slice(0,16)}</code>
   <button onclick="v('${x.run}',this)">Verify evidence now</button> <span></span></li>`).join('');
}
async function v(run,btn){
  const s=btn.nextElementSibling; s.textContent='checking...';
  const res=await fetch('api/runs/'+run+'/verify',{method:'POST'}); const d=await res.json();
  if(!res.ok){s.textContent=d.detail;return}
  s.className=d.valid?'ok':'bad';
  s.textContent=d.valid?`valid: ${d.checks.length} checks passed in ${d.seconds}s from ${d.source}`:'INVALID: '+d.error;
}
go();
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
