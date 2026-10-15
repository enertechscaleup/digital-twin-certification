"""The "Register project and enable connection" button and the "Status of this prototype" view it opens:
exact wording, one source of truth shared with the Connect telemetry step, nothing collected, stored
or sent, and no wording that claims a registration, a connection or anything live."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web/src/platform"
DATA = (WEB / "prototypeStatus.js").read_text()
VIEW = (WEB / "PrototypeStatus.jsx").read_text()
STEP = (WEB / "ConnectTelemetry.jsx").read_text()
DEMO = json.loads((WEB / "ingestion-demo.json").read_text())


def strings(block: str) -> list[str]:
    return re.findall(r"'((?:[^'\\]|\\.)*)'|`([^`]*)`", block)


def array(name: str) -> str:
    start = DATA.index(f"export const {name} = [")
    return DATA[start:DATA.index("\n]\n", start)]


def texts(name: str) -> list[str]:
    return [a or b for a, b in strings(array(name))]


class TestWording(unittest.TestCase):
    def test_heading_and_first_line(self):
        self.assertIn("export const STATUS_HEADING = 'Status of this prototype'", DATA)
        self.assertIn("export const STATUS_FIRST_LINE = 'Nothing was registered or sent. This prototype has no live registration.'", DATA)
        self.assertIn("<b>{STATUS_FIRST_LINE}</b>", VIEW)
        self.assertLess(VIEW.index("{STATUS_HEADING}</h3>"), VIEW.index("{STATUS_FIRST_LINE}"))

    def test_built_and_demonstrated(self):
        self.assertEqual(texts("BUILT_AND_DEMONSTRATED"), [
            "The evidence engine and its hash-chained ledger",
            "Retention-locked evidence in Cloud Storage",
            "Re-verification on Cloud Run before a run is served",
            "Explanations by Gemini on Vertex AI, and the read-only evidence assistant",
            "Streaming ingestion (Pub/Sub, Dataflow, BigQuery, Cloud Storage) on replayed synthetic data on ${demo.date}",
            "Separate twin and plant feeds (Pub/Sub, Dataflow, BigQuery), joined per tick, on replayed synthetic data on ${twoSource.date}; "
            "both feeds replayed the same sealed run and shared its tick index",
        ])
        self.assertEqual(DEMO["date"], "2026-10-15")

    def test_designed_not_built(self):
        block = array("DESIGNED_NOT_BUILT")
        self.assertIn("A source connection for a real project: push from a customer system, pull from a historian or an OPC UA / "
                      "MQTT gateway, or a vendor twin API", block)
        self.assertNotIn("SEPARATE_FEEDS", block)  # built and proved on 2026-10-15 (two-source replays)
        self.assertIn("PROVENANCE,", block)
        self.assertIn("...ALIGNMENT_DESIGNED,", block)
        self.assertEqual(len(texts("ALIGNMENT_DESIGNED")), 5)

    def test_go_live_steps_in_order_and_none_marked_built(self):
        steps = re.findall(r"\['([^']+)', (true|false), '([^']*)'\]", array("GO_LIVE_STEPS"))
        self.assertEqual([s for s, _, _ in steps], [
            "Register the project on the platform",
            "Create its topic, subscription and publish-only service account",
            "The twin owner and the plant each publish their data",
            "Declare and seal the alignment window",
            "Monitoring starts",
        ])
        self.assertEqual({b for _, b, _ in steps}, {"false"})
        self.assertIn("{built ? 'Built' : 'Not built'}", VIEW)

    def test_links_back_and_home(self):
        self.assertIn(">Back to Connect telemetry</button>", VIEW)
        self.assertIn('<a className="text-link" href={HOME_URL}>TwinEvidence home</a>', VIEW)
        self.assertRegex(VIEW, r'<nav className="crumbs"[^>]*>\s*<button[^\n]*onClick=\{onBack\}>Connect telemetry</button>')


class TestTwoSourceResult(unittest.TestCase):
    two = json.loads((WEB / "ingestion-two-source.json").read_text())

    def test_recorded_key_test_agrees_with_the_pin(self):
        pins = {r["run"]: r for r in json.loads((ROOT / "app/config/runs.json").read_text())["runs"]}
        e = self.two["engine"]
        self.assertEqual(e["pin_head"], pins[self.two["replayed_run"]["run"]]["core_ledger_head_hash"])
        self.assertTrue(self.two["joined_identical_to_sealed"])
        self.assertTrue(e["comparison_copy_head_identical"])
        self.assertEqual(e["head"], e["pin_head"])
        self.assertTrue(e["ingestion_labelled_same_decisions"])
        self.assertFalse(e["ingestion_labelled_head_identical"])
        self.assertEqual(self.two["shared_tick_index"], "Both publishers replayed the same sealed synthetic run and shared its tick index.")

    def test_no_identifiers(self):
        text = (WEB / "ingestion-two-source.json").read_text()
        for pattern in (r"project-[0-9a-f]{8}", r"\b\d{11,12}\b", r"dtc-ingest-[0-9a-f]{8}", r"\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}-\d+",
                        r"iam\.gserviceaccount\.com"):
            self.assertNotRegex(text, pattern)

    def test_built_row_and_two_paths_sentence(self):
        self.assertIn("export const TWO_SOURCE_BUILT_LABEL = `Built and run on replayed synthetic data on ${twoSource.date}`", DATA)
        self.assertIn("[SEPARATE_FEEDS, TWO_SOURCE_BUILT_LABEL,", DATA)
        self.assertIn("[PROVENANCE, DESIGNED_LABEL,", DATA)
        self.assertIn("'Two paths are built: one message carrying both sides, and separate twin and plant messages joined per tick "
                      "(both demonstrated on replayed synthetic data).'", DATA)


class TestOneSourceOfTruth(unittest.TestCase):
    def test_both_views_import_the_lists_and_hold_no_copies(self):
        self.assertIn("import { ALIGNMENT_BUILT, ALIGNMENT_BUILT_LABEL, ALIGNMENT_BUILT_NOTE, ALIGNMENT_DESIGNED, DESIGNED_LABEL, TWO_PATHS, VALUE_SOURCES } from './prototypeStatus.js'", STEP)
        self.assertIn("from './prototypeStatus.js'", VIEW)
        for name in ("ALIGNMENT_BUILT", "ALIGNMENT_DESIGNED"):
            for t in texts(name):
                self.assertNotIn(t, STEP)
                self.assertNotIn(t, VIEW)
        self.assertNotIn("Per-value provenance", STEP)
        self.assertNotIn("Separate twin messages", STEP)

    def test_status_designed_list_holds_what_the_step_lists_as_designed(self):
        # The step shows ALIGNMENT_DESIGNED and VALUE_SOURCES; the status list spreads the first and names provenance.
        self.assertIn("{ALIGNMENT_DESIGNED.map(", STEP)
        self.assertIn("{VALUE_SOURCES.map(", STEP)
        self.assertIn("[PROVENANCE, DESIGNED_LABEL,", array("VALUE_SOURCES"))


class TestNothingCollectedStoredOrSent(unittest.TestCase):
    def test_no_form_storage_or_network(self):
        for code in (VIEW, DATA):
            for banned in ("<form", "<input", "<textarea", "<select", "mailto:", "localStorage", "sessionStorage", "indexedDB",
                           "document.cookie", "fetch(", "XMLHttpRequest", "sendBeacon", "WebSocket", "EventSource", "http://", "https://"):
                self.assertNotIn(banned, code)

    def test_forbidden_phrases(self):
        everything = VIEW + DATA
        self.assertNotIn("Connected", everything)
        self.assertNotIn("Registered", everything)
        first_line = "Nothing was registered or sent. This prototype has no live registration."
        # Mandated wording is exempt: the first line, and the heading "What a real go-live needs, in order".
        rest = everything.replace(first_line, "").replace("What a real go-live needs, in order", "").replace("GO_LIVE_STEPS", "")
        self.assertNotRegex(rest, r"\bregistered\b")
        for word in (r"\blive\b", r"real-time", r"real time"):
            self.assertNotRegex(rest.lower(), word)
        for claim in ("time-synchronised", "synchronised clocks", "real-time alignment", "field-validated", "validated in the field"):
            self.assertNotIn(claim, everything.lower())


if __name__ == "__main__":
    unittest.main()
