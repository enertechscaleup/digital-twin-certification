"""Gemini-generated supplementary artifacts.

Gemini never decides pass, flag, or nullify. It receives a grounded fact pack
(see ``facts.py``) about an event the deterministic engine has already
recorded, and returns a structured explanation. Every artifact states that it
is supplementary, carries the hash of the event it explains, and records the
exact model and a hash of the facts it was given.

Three artifact types, per the design doc's Stage 1 rows:
* ``status_explanation`` -- why a product twin's status changed, reasoning
  across correlated channels.
* ``data_quality_suggestion`` -- an independent second opinion on whether a
  data-quality anomaly is a sensor fault, for a human to confirm.
* ``impact_narrative`` -- plain-language impact when the system twin's status
  changes, traced to the constituent driving it.
"""

from __future__ import annotations

import json
import os
from typing import Callable, Protocol

from engine.ledger import sha256_hex
from engine.registry import Registry
from explain.facts import check_evidence, fact_pack

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "")
DEFAULT_LOCATION = os.environ.get("GEMINI_LOCATION", "us-central1")
SUPPLEMENTARY_NOTICE = "Supplementary AI artifact. Not used in any assurance decision."

SYSTEM_INSTRUCTION = """You write explanations for an independent digital twin assurance platform.

Rules you must follow:
1. Use only the facts in the JSON you are given. Do not invent readings, causes, components, or history.
   If the facts do not support a conclusion, say so plainly.
2. The platform's deterministic engine has already made every status decision (assured, flagged, nullified)
   and every classification. Never contradict, re-decide, or soften them. You explain; you do not judge.
3. The platform assures predictive fidelity within validated conditions. Never state or imply that the
   physical equipment is safe or unsafe to operate, and do not give operating instructions. You may suggest
   what a human could investigate.
4. Reason across correlated channels and connected twins where the facts show a relationship
   (for example, one twin's output feeding another twin's input).
5. Cite specific ticks, channels, values, and gap percentages from the facts. Use the units given.
6. Plain English for a non-specialist operator. Short sentences. No markdown.
"""

TASKS = {
    "status_explanation": (
        "Explain why the subject product twin's assurance status changed (or gained a new reason) at this tick. "
        "Describe the pattern in the readings that led to it and any related behaviour on correlated channels "
        "or connected twins."
    ),
    "data_quality_suggestion": (
        "The engine classified the subject reading as a data-quality anomaly (a sensor or reading problem). "
        "Give an independent second opinion on which kind of anomaly this looks like, based only on the facts. "
        "This is a suggestion a human will confirm or reject."
    ),
    "impact_narrative": (
        "The subject system twin's assurance status changed or gained a new reason. Write a plain-language impact "
        "narrative for the system owner: which constituent twin is driving it, why, how it shows up in the "
        "system's outputs, and what a human might investigate first."
    ),
}

CLASSIFICATIONS = ["sensor_fault", "twin_prediction_fault", "operating_outside_envelope", "unclear"]

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "description": "One sentence, under 20 words."},
        "explanation": {"type": "string", "description": "Three to six sentences."},
        "evidence_cited": {"type": "array", "items": {"type": "string"},
                           "description": "Specific facts relied on, e.g. 'tick 19 motor speed gap 5.7%'."},
        "suggested_classification": {"type": "string", "enum": CLASSIFICATIONS,
                                     "description": "Your independent reading of the likely category."},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "suggested_investigation": {"type": "string", "description": "What a human could check next."},
        "limitations": {"type": "string", "description": "What the facts cannot tell us."},
    },
    "required": ["headline", "explanation", "evidence_cited", "suggested_classification",
                 "confidence", "suggested_investigation", "limitations"],
}


class Generator(Protocol):
    """Anything that turns (system instruction, prompt, schema) into a JSON string."""
    model_id: str

    def __call__(self, system_instruction: str, prompt: str, schema: dict) -> str: ...


class VertexGemini:
    """Calls Gemini on Vertex AI via the google-genai SDK."""

    def __init__(self, model_id: str = DEFAULT_MODEL, project: str | None = None, location: str = DEFAULT_LOCATION):
        if not model_id:
            raise ValueError("set GEMINI_MODEL (or pass model_id) to a pinned Gemini model ID")
        from google import genai  # imported here so the rest of the package works without it

        self.model_id = model_id
        self._types = genai.types
        self._client = genai.Client(vertexai=True, project=project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
                                    location=location)

    def __call__(self, system_instruction: str, prompt: str, schema: dict) -> str:
        response = self._client.models.generate_content(
            model=self.model_id,
            contents=prompt,
            config=self._types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.0,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        return response.text


def artifact_type_for(entry: dict, registry: Registry) -> str | None:
    t, p = entry["entry_type"], entry["payload"]
    if t in ("assurance_status_changed", "assurance_reason_added"):
        return "impact_narrative" if p["twin_id"] == registry.system.operational_system_twin_id else "status_explanation"
    if t == "anomaly_opened" and p["type"] == "data_quality":
        return "data_quality_suggestion"
    return None


def generate_artifacts(ledger: list[dict], readings: list[dict], timeline: list[dict], registry: Registry,
                       generate: Generator, on_artifact: Callable[[dict], None] | None = None) -> list[dict]:
    check_evidence(ledger, readings)  # refuse to explain evidence that has been altered
    artifacts = []
    for entry in ledger:
        kind = artifact_type_for(entry, registry)
        if kind is None:
            continue
        facts = fact_pack(entry, ledger, readings, timeline, registry)
        prompt = f"TASK: {TASKS[kind]}\n\nFACTS (JSON):\n{json.dumps(facts, indent=1)}"
        raw = generate(SYSTEM_INSTRUCTION, prompt, RESPONSE_SCHEMA)
        try:
            response, parse_error = json.loads(raw), None
        except json.JSONDecodeError as exc:
            response, parse_error = None, str(exc)
        artifact = {
            "artifact_type": kind,
            "notice": SUPPLEMENTARY_NOTICE,
            "explains_ledger_seq": entry["seq"],
            "explains_entry_hash": entry["entry_hash"],
            "model_id": generate.model_id,
            "temperature": 0.0,
            "system_instruction_sha256": sha256_hex(SYSTEM_INSTRUCTION),
            "facts_sha256": sha256_hex(facts),
            "response": response,
            "raw_response": raw if parse_error else None,
            "parse_error": parse_error,
        }
        artifacts.append(artifact)
        if on_artifact:
            on_artifact(artifact)
    return artifacts
