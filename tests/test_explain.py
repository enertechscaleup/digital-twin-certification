"""Tests for the Gemini explanation layer, using a fake model (no network)."""

import ast
import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.registry import load_registry
from engine.run import run_assurance
from explain.facts import EvidenceIntegrityError
from explain.gemini import RESPONSE_SCHEMA, SUPPLEMENTARY_NOTICE, generate_artifacts
from telemetry.faults import Scenario

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)


class FakeGemini:
    model_id = "fake-model"

    def __init__(self, reply=None):
        self.prompts = []
        self.reply = reply

    def __call__(self, system_instruction, prompt, schema):
        self.prompts.append(prompt)
        if self.reply is not None:
            return self.reply
        return json.dumps({k: ([] if v["type"] == "array" else "unclear" if "enum" in v else "x")
                           for k, v in schema["properties"].items()})


def wear_run():
    s = Scenario.from_dict(json.loads((ROOT / "scenarios" / "demo_wear_to_nullified.json").read_text()))
    r = run_assurance(s, seed=42, start_time=START)
    return r.ledger.entries, r.readings, r.timeline


class TestExplain(unittest.TestCase):
    def test_one_artifact_per_explainable_event(self):
        ledger, readings, timeline = wear_run()
        fake = FakeGemini()
        artifacts = generate_artifacts(ledger, readings, timeline, load_registry(), fake)
        kinds = [a["artifact_type"] for a in artifacts]
        self.assertEqual(kinds.count("impact_narrative"), 2)  # system twin: flagged, then cascade reason
        self.assertEqual(kinds.count("status_explanation"), 5)  # motor x4, compressor x1
        for a in artifacts:
            self.assertEqual(a["notice"], SUPPLEMENTARY_NOTICE)
            self.assertEqual(a["explains_entry_hash"], ledger[a["explains_ledger_seq"]]["entry_hash"])

    def test_facts_are_grounded_and_exclude_ground_truth(self):
        ledger, readings, timeline = wear_run()
        fake = FakeGemini()
        generate_artifacts(ledger, readings, timeline, load_registry(), fake)
        prompt = fake.prompts[0]
        self.assertNotIn("injected_faults", prompt)
        self.assertNotIn("wear_drift", prompt)
        self.assertIn('"connections"', prompt)
        self.assertIn('"readings_window"', prompt)

    def test_tampered_readings_are_refused(self):
        ledger, readings, timeline = wear_run()
        bad = copy.deepcopy(readings)
        bad[100]["physical_value"] += 1
        with self.assertRaises(EvidenceIntegrityError):
            generate_artifacts(ledger, bad, timeline, load_registry(), FakeGemini())

    def test_tampered_ledger_is_refused(self):
        ledger, readings, timeline = wear_run()
        bad = copy.deepcopy(ledger)
        bad[15]["payload"]["tick"] = 1
        with self.assertRaises(EvidenceIntegrityError):
            generate_artifacts(bad, readings, timeline, load_registry(), FakeGemini())

    def test_unparseable_reply_is_recorded_not_crashed(self):
        ledger, readings, timeline = wear_run()
        artifacts = generate_artifacts(ledger, readings, timeline, load_registry(), FakeGemini("not json"))
        self.assertIsNone(artifacts[0]["response"])
        self.assertEqual(artifacts[0]["raw_response"], "not json")

    def test_engine_never_imports_ai_code(self):
        for path in (ROOT / "engine").glob("*.py"):
            tree = ast.parse(path.read_text())
            names = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)]
            names += [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
            for name in names:
                self.assertFalse(name.startswith(("explain", "google")), f"{path.name} imports {name}")

    def test_schema_requires_every_field(self):
        self.assertEqual(set(RESPONSE_SCHEMA["required"]), set(RESPONSE_SCHEMA["properties"]))


if __name__ == "__main__":
    unittest.main()
