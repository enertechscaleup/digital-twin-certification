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
STATUS_DATA = (WEB / "prototypeStatus.js").read_text()
CHANNELS = RULES["example_project"]["channels"]
SAMPLES = RULES["example_project"]["samples"]
SAMPLE = SAMPLES["both"]


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
    v = [("valid sample, both sides (output channel)", SAMPLE["data"], SAMPLE["attributes"], "valid"),
         ("valid sample, plant only (input channel)", SAMPLES["plant_only"]["data"], SAMPLES["plant_only"]["attributes"], "valid")]
    for reason, data, attrs in invalid_messages(json.loads(SAMPLES["plant_only"]["data"]), "sample"):
        v.append((f"plant-only publisher {reason}", data.decode(), attrs, reason))
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


class TestComparisonRuleFromEngine(unittest.TestCase):
    cmp = RULES["comparison"]

    def test_numbers_are_the_engine_protocol(self):
        from engine.protocol import EscalationProtocol
        proto = EscalationProtocol().to_dict()
        for k, v in self.cmp["protocol"].items():
            self.assertEqual(v, proto[k], k)
        self.assertFalse(proto["envelope_can_nullify"])
        self.assertIn("input-envelope violations never nullify.", self.cmp["rules"][2])

    def test_gap_formula_is_the_engine_function(self):
        from engine.readings import gap_pct
        self.assertEqual(self.cmp["gap_formula"], "gap % = 100 × |physical − predicted| / |predicted|")
        for physical, predicted in ((110, 100), (90, 100), (-5, -4), (3.3, 3.0)):
            self.assertAlmostEqual(gap_pct(physical, predicted), 100 * abs(physical - predicted) / abs(predicted))

    def test_rules_match_the_monitor(self):
        monitor = (ROOT / "engine/monitor.py").read_text()
        # Data quality on the measured value only; gap only on clean outputs with a valid, non-zero prediction.
        self.assertIn('v = None if r is None else r["physical_value"]', monitor)
        self.assertIn('if not is_valid_number(r["predicted_value"]) or r["predicted_value"] == 0:', monitor)
        self.assertIn("if bad_inputs:", monitor)
        self.assertIn("g > c.tolerance_pct", monitor)
        self.assertIn("critical_limit = c.tolerance_pct * self.protocol.nullify_tolerance_multiplier", monitor)
        p = self.cmp["protocol"]
        self.assertTrue(self.cmp["rules"][0].startswith(f"Flagged after {p['flag_after_consecutive']} consecutive readings beyond τ"))
        self.assertIn(f"Nullified after {p['nullify_after_consecutive']} consecutive readings beyond {p['nullify_tolerance_multiplier']:g}τ", self.cmp["rules"][1])
        self.assertIn(f"stuck ×{p['stuck_after_identical']}, a jump above {p['spike_jump_pct']:g}%", self.cmp["rules"][3])

    def test_page_shows_the_exported_rule_not_hand_written_text(self):
        self.assertIn("RULES.comparison", STEP)
        self.assertIn("{cmp.gap_formula}", STEP)
        self.assertIn("cmp.rules.map", STEP)
        self.assertNotIn("consecutive readings beyond", STEP)

    def test_example_tolerances_come_from_the_registry(self):
        from engine.registry import load_registry
        from projects import load_project
        reg = load_registry(load_project(ROOT / "projects/fulfilment_cell.json"))
        want = {(p.operational_twin_id, c.channel_id): (c.tolerance_pct if c.direction == "output" else None)
                for p in reg.products.values() for c in p.channels}
        self.assertEqual({(c["twin_id"], c["channel_id"]): c["tolerance_pct"] for c in CHANNELS}, want)


class TestTwinAndPlantStreams(unittest.TestCase):
    def test_two_named_streams_and_what_each_carries(self):
        self.assertIn('<div className="h4">Twin stream</div>', STEP)
        self.assertIn('<div className="h4">Plant stream</div>', STEP)
        self.assertIn("What the platform does today: the twin is fed the same values as the plant’s measured inputs.", STEP)
        self.assertIn("<p className=\"hint\"><b>{TWO_PATHS}</b></p>", STEP)

    def test_input_shows_one_value_output_two(self):
        self.assertIn("data-values={output ? 2 : 1}", STEP)
        self.assertIn("{output ? 'predicted_value (twin_version)' : '— (fed the measured input)'}", STEP)
        self.assertIsNone(json.loads(SAMPLES["plant_only"]["data"])["predicted_value"])
        self.assertEqual(json.loads(SAMPLES["plant_only"]["data"])["direction"], "input")
        both = json.loads(SAMPLES["both"]["data"])
        self.assertEqual(both["direction"], "output")
        self.assertIsNotNone(both["predicted_value"])

    def test_synthetic_plant_label_next_to_the_plant_stream(self):
        label = "The plant data in this demonstration is synthetic. It has never been compared with a real physical system."
        self.assertIn(label, STEP)
        plant = STEP[STEP.index('data-stream="plant"'):]
        self.assertIn("{SYNTHETIC_PLANT}", plant[:plant.index("</div>\n          </div>")])

    def test_alignment_sentence_and_rows(self):
        self.assertIn("The platform aligns twin and plant values on a shared tick index and evaluates a tick only when it is complete. "
                      "Aligning two independent systems in time (clock synchronisation, resampling, lag compensation) is designed, not built.", STEP)
        built = STATUS_DATA[STATUS_DATA.index("export const ALIGNMENT_BUILT"):STATUS_DATA.index("export const ALIGNMENT_DESIGNED")]
        designed = STATUS_DATA[STATUS_DATA.index("export const ALIGNMENT_DESIGNED"):STATUS_DATA.index("export const SEPARATE_FEEDS")]
        self.assertEqual(built.count("\n  '"), 5)
        self.assertIn("r1015e", built)
        for item in ("Clock synchronisation", "Resampling", "Lag compensation", "An alignment window per channel", "never guessed"):
            self.assertIn(item, designed)
        self.assertIn("export const PROVENANCE = 'Per-value provenance'", STATUS_DATA)
        self.assertIn("export const SEPARATE_FEEDS = 'Separate twin messages and plant messages, joined per tick in the pipeline'", STATUS_DATA)
        self.assertIn("export const DESIGNED_LABEL = 'Not built, designed only'", STATUS_DATA)
        self.assertIn("<td>{DESIGNED_LABEL}</td>", STEP)

    def test_designed_items_have_design_notes(self):
        doc = (ROOT / "docs/ingestion.md").read_text()
        for item in ("Per-value provenance", "Separate twin messages and plant messages", "Clock synchronisation"):
            self.assertIn(item, doc)

    def test_forbidden_phrases(self):
        for phrase in ("Connected", "time-synchronised", "time synchronised", "synchronised clocks", "real-time alignment",
                       "real time alignment", "validated in the field", "field-validated", "field validation", "field-tested"):
            self.assertNotIn(phrase.lower(), STEP.lower())


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

    def test_register_button_opens_the_status_view_and_the_note_stays(self):
        button = re.search(r"<button [^\n]*>Register project and enable connection</button>", STEP)
        self.assertIsNotNone(button)
        self.assertNotRegex(button.group(0), r"\bdisabled\b")
        self.assertIn("onClick={() => setView('status')}", button.group(0))
        self.assertIn("if (view === 'status') return <div className=\"panel\">{head}<PrototypeStatus onBack={() => setView('connect')} /></div>", STEP)
        self.assertNotIn(">Enable connection<", STEP)
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
