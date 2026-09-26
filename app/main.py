"""Minimal Cloud Run skeleton: a live view of the telemetry generator.

Stateless by design. Cloud Run pauses CPU between requests, so a background
generator loop would stall. Instead every request works out the current tick
from the clock and replays the (deterministic) scenario up to that tick.
Every instance therefore serves identical data with no shared state.

The scenario loops: each cycle lasts ``ticks x tick_seconds`` and restarts
from tick 0 with a start time aligned to the cycle boundary.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from telemetry.faults import Scenario
from telemetry.generator import GENERATOR_VERSION, Reading, TelemetryGenerator

ROOT = Path(__file__).resolve().parent.parent
SCENARIO_NAME = os.environ.get("SCENARIO", "healthy")
SEED = int(os.environ.get("SEED", "42"))
EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)

app = FastAPI(title="Digital Twin Certification — telemetry skeleton")


@lru_cache(maxsize=1)
def _scenario() -> Scenario:
    return Scenario.from_dict(json.loads((ROOT / "scenarios" / f"{SCENARIO_NAME}.json").read_text()))


@lru_cache(maxsize=4)
def _cycle(cycle_start: datetime) -> tuple[tuple[Reading, ...], ...]:
    gen = TelemetryGenerator(seed=SEED, start_time=cycle_start)
    return tuple(tuple(batch) for batch in gen.field_run(_scenario()))


def _current() -> tuple[int, list[Reading]]:
    scenario = _scenario()
    tick_seconds = TelemetryGenerator(seed=SEED, start_time=EPOCH).tick_seconds
    elapsed = (datetime.now(timezone.utc) - EPOCH).total_seconds()
    cycle_seconds = scenario.ticks * tick_seconds
    cycle_start = EPOCH + timedelta(seconds=(elapsed // cycle_seconds) * cycle_seconds)
    tick = int((elapsed % cycle_seconds) // tick_seconds)
    return tick, list(_cycle(cycle_start)[tick])


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/latest")
def latest() -> dict:
    tick, batch = _current()
    return {
        "scenario": SCENARIO_NAME,
        "seed": SEED,
        "generator_version": GENERATOR_VERSION,
        "tick": tick,
        "readings": [r.__dict__ for r in batch],
    }


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Twin Telemetry Skeleton</title>
<style>body{font:14px system-ui,sans-serif;margin:16px}table{border-collapse:collapse}
td,th{border:1px solid #ccc;padding:4px 8px;text-align:right}th{background:#f4f4f4}
td:nth-child(-n+3){text-align:left}.note{color:#666}</style></head><body>
<h1 style="font-size:18px">Digital Twin Certification: live telemetry (Phase 1 skeleton)</h1>
<p class="note">Synthetic data. Refreshes every 2 seconds. Placeholder only; not the dashboard.</p>
<p id="meta"></p><table id="t"></table>
<script>
async function refresh(){
  try{
    const d=await (await fetch('api/latest')).json();
    document.getElementById('meta').textContent=
      `scenario ${d.scenario} · seed ${d.seed} · tick ${d.tick} · ${d.readings[0].timestamp}`;
    const f=v=>v==null?'—':v;
    document.getElementById('t').innerHTML='<tr><th>twin</th><th>channel</th><th>direction</th><th>physical</th><th>predicted</th><th>unit</th></tr>'+
      d.readings.map(r=>`<tr><td>${r.twin_id}</td><td>${r.channel_id}</td><td>${r.direction}</td><td>${f(r.physical_value)}</td><td>${f(r.predicted_value)}</td><td>${r.unit}</td></tr>`).join('');
  }catch(e){document.getElementById('meta').textContent='error: '+e;}
}
refresh();setInterval(refresh,2000);
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return PAGE
