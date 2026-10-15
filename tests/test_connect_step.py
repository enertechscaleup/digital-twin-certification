"""The "Connect telemetry" step: its browser validator must give the same verdict as the Dataflow
pipeline's classify() for every message (drift test), its rules file must be exactly what
ingest/export_rules.py exports, and its labels and disabled button must stay as agreed."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "ingest")]
import export_rules  # noqa: E402
import pipeline  # noqa: E402
from publisher import invalid_messages  # noqa: E402

WEB = ROOT / "web/src/platform"
RULES = json.loads((WEB / "ingestion-rules.json").read_text())
STEP = (WEB / "ConnectTelemetry.jsx").read_text()
VALIDATOR = (WEB / "ingestValidate.js").read_text()
CHANNELS = RULES["example_project"]["channels"]
SAMPLE = RULES["example_project"]["sample"]


def attrs_for(data: str, row: dict | None = None, **over) -> dict:
    row = row if row is not None else json.loads(SAMPLE["data"])
    a = {"schema": RULES["schema"], "source": "sample", "replay_id": "sample", "event_ts": "2026-10-01T00:00:00Z",
         "content_sha256": hashlib.sha256(data.encode()).hexdigest(),
         "reading_key": pipeline.reading_key("sample", str(row.get("run_id")), row.get("tick"), str(row.get("twin_id")), str(row.get("channel_id")))}
    a.update(over)
    return {k: v for k, v in a.items() if v is not None}


def variant(**changes) -> tuple[str, dict]:
    row = {**json.loads(SAMPLE["data"]), **changes}
    data = json.dumps(row)
    return data, attrs_for(data, row)


def vectors() -> list[tuple[str, str, dict, str]]:
    """(name, data text, attributes, expected verdict)."""
    v = [("valid sample", SAMPLE["data"], SAMPLE["attributes"], "valid")]
    for reason, data, attrs in invalid_messages(json.loads(SAMPLE["data"]), "sample"):
        v.append((f"publisher {reason}", data.decode(), attrs, reason))
    d, a = variant(physical_value=None)
    v.append(("dropout (null value) passes", d, a, "valid"))
    d, a = variant(physical_value=1e9)
    v.append(("spike passes (values are never judged)", d, a, "valid"))
    for name, changes, expected in [
        ("tick 3.0", None, "bad_type"), ("tick true", {"tick": True}, "bad_type"), ("tick -1", {"tick": -1}, "bad_type"),
        ("operational_hours null", {"operational_hours": None}, "bad_type"), ("empty run_id", {"run_id": ""}, "bad_type"),
        ("timestamp with a final newline (Python $)", {"timestamp": "2026-10-01T00:00:00Z\n"}, "valid"),
        ("timestamp with two final newlines", {"timestamp": "2026-10-01T00:00:00Z\n\n"}, "bad_type"),
        ("timestamp in Arabic-Indic digits (Python \\d)", {"timestamp": "٢٠٢٦-10-01T00:00:00Z"}, "valid"),
        ("timestamp without Z", {"timestamp": "2026-10-01T00:00:00"}, "bad_type"),
        ("direction differs", {"direction": "input"}, "unknown_channel"), ("unit differs", {"unit": "m/s"}, "unknown_channel"),
        ("kind bench", {"kind": "bench"}, "wrong_kind"), ("test_point set", {"test_point": 1}, "wrong_kind"),
    ]:
        if changes is None:
            d = SAMPLE["data"].replace('"tick": 0', '"tick": 0.0')
            a = attrs_for(d)
        else:
            d, a = variant(**changes)
        v.append((name, d, a, expected))
    nan = SAMPLE["data"].replace('"physical_value": 75.0', '"physical_value": NaN')
    v.append(("NaN token", nan, attrs_for(nan), "malformed_json"))
    v.append(("top-level array", "[1, 2]", attrs_for("[1, 2]"), "malformed_json"))
    v.append(("schema wrong", SAMPLE["data"], {**SAMPLE["attributes"], "schema": "other/1"}, "bad_attributes"))
    v.append(("replay_id missing", SAMPLE["data"], {k: x for k, x in SAMPLE["attributes"].items() if k != "replay_id"}, "bad_attributes"))
    v.append(("control message", "{}", {"kind": "control"}, "control"))
    return v


def python_verdict(data: str, attrs: dict) -> str:
    spec = {(c["twin_id"], c["channel_id"]): (c["direction"], c["unit"]) for c in CHANNELS}
    kind, result = pipeline.classify(data.encode(), attrs, spec)
    return result if kind == "invalid" else kind


def browser_verdicts(vs) -> list[str]:
    script = f"""
import {{ classify }} from {json.dumps((WEB / 'ingestValidate.js').as_uri())}
import {{ readFileSync }} from 'node:fs'
const rules = JSON.parse(readFileSync({json.dumps(str(WEB / 'ingestion-rules.json'))}, 'utf8'))
const vs = JSON.parse(readFileSync(process.argv[1], 'utf8'))
const out = []
for (const [data, attrs] of vs) {{ const r = await classify(data, attrs, rules.example_project.channels, rules); out.push(r.kind === 'invalid' ? r.reason : r.kind) }}
console.log(JSON.stringify(out))
"""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump([[d, a] for _, d, a, _ in vs], fh)
    run = subprocess.run(["node", "--input-type=module", "-e", script, fh.name], capture_output=True, text=True, check=True)
    return json.loads(run.stdout)


class TestRulesHaveOneSource(unittest.TestCase):
    def test_rules_file_is_exactly_the_export(self):
        self.assertEqual((WEB / "ingestion-rules.json").read_text(), export_rules.text(),
                         "web/src/platform/ingestion-rules.json drifted: run python ingest/export_rules.py")

    def test_fields_and_reasons_come_from_engine_and_pipeline(self):
        from engine.readings import ALLOWED_FIELDS
        self.assertEqual(RULES["allowed_fields"], list(ALLOWED_FIELDS))
        self.assertEqual([r["code"] for r in RULES["reject_reasons"]], [c for c, _ in pipeline.REJECT_REASONS])
        self.assertEqual(RULES["timestamp_pattern"], pipeline.TIMESTAMP.pattern)

    def test_every_code_the_validators_return_is_listed(self):
        codes = {c for c, _ in pipeline.REJECT_REASONS}
        returned = set(re.findall(r'"invalid", "(\w+)"', (ROOT / "ingest/pipeline.py").read_text()))
        returned |= set(re.findall(r'reject_reason": "(\w+)"', (ROOT / "ingest/pipeline.py").read_text()))
        self.assertTrue(returned <= codes, returned - codes)
        self.assertEqual(set(re.findall(r"reason: '(\w+)'", VALIDATOR)) | {"conflicting_duplicate"}, codes)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestBrowserValidatorMatchesPipeline(unittest.TestCase):
    def test_same_verdict_on_every_message(self):
        vs = vectors()
        browser = browser_verdicts(vs)
        for (name, data, attrs, expected), got in zip(vs, browser):
            with self.subTest(name):
                self.assertEqual(python_verdict(data, attrs), expected, "pipeline")
                self.assertEqual(got, expected, "browser")

    def test_every_single_message_reason_is_exercised(self):
        exercised = {e for _, _, _, e in vectors()}
        single = {c for c, _ in pipeline.REJECT_REASONS} - {"conflicting_duplicate"}
        self.assertTrue(single <= exercised, single - exercised)


class TestStepLabels(unittest.TestCase):
    def test_three_sources_with_status_labels(self):
        for label in ("Push to Pub/Sub", "Pull from a historian or an OPC UA / MQTT gateway", "Vendor twin API"):
            self.assertIn(label, STEP)
        self.assertIn("Demonstrated on replayed synthetic data", STEP)
        self.assertEqual(STEP.count("Designed, not built"), 2)

    def test_topic_contract_access_and_example_label(self):
        self.assertIn("would be created on connection", STEP)
        self.assertIn("publish-only service account", STEP)
        self.assertIn("RULES.example_project.label", STEP)
        self.assertEqual(RULES["example_project"]["label"], "Example project")

    def test_enable_connection_is_disabled_with_the_agreed_text(self):
        button = re.search(r"<button[^>]*>\s*Enable connection\s*</button>", STEP)
        self.assertIsNotNone(button)
        self.assertRegex(button.group(0), r"\bdisabled\b")
        self.assertIn("Not enabled in this prototype. Connecting a live source needs a project registered on the platform, "
                      "and the wizard saves configuration in this browser only.", STEP)

    def test_no_network_no_connected_no_secrets(self):
        for code in (STEP, VALIDATOR):
            for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "http://", "https://",
                           "Connected", "-----BEGIN", "private_key", "iam.gserviceaccount.com"):
                self.assertNotIn(banned, code)
        self.assertNotRegex(json.dumps(RULES), r"project-[0-9a-f]{8}|\b\d{11,12}\b")


if __name__ == "__main__":
    unittest.main()
