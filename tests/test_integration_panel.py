"""The Integration panel of a wizard-made project shows a RECORDED replay result from a committed
file: fixed honest wording, no live status, nothing that calls a cloud service, no identifiers,
and figures that agree with the pins. Also the text fixes that came with it."""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web/src/platform"
PANEL = (WEB / "IntegrationPanel.jsx").read_text()
DEMO_TEXT = (WEB / "ingestion-demo.json").read_text()
DEMO = json.loads(DEMO_TEXT)
PINS = {r["run"]: r for r in json.loads((ROOT / "app/config/runs.json").read_text())["runs"]}


class TestWording(unittest.TestCase):
    def test_required_sentence_with_the_replay_date(self):
        self.assertRegex(DEMO["date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual(DEMO["label"], f"Streaming ingestion: demonstrated on replayed synthetic data on {DEMO['date']}. "
                                        "Not live telemetry. Not tested at scale.")
        self.assertIn("{demo.label}", PANEL)

    def test_wizard_projects_are_configuration_only(self):
        self.assertIn("A project made in the wizard is configuration only.", PANEL)

    def test_no_live_status_and_no_calls(self):
        for banned in ("fetch(", "XMLHttpRequest", "sendBeacon", "http://", "https://", "Connected", "connected to Pub/Sub", "live status:"):
            self.assertNotIn(banned, PANEL)
        self.assertNotRegex(PANEL, r"\bimport\b.*\bapi\.js\b")
        # The only buttons switch which explanation is shown.
        self.assertEqual(re.findall(r"onClick=\{\(\) => (\w+)\(", PANEL), ["setSource", "setSource"])

    def test_both_labels_used_exactly(self):
        self.assertIn("Comparison copy", PANEL)
        self.assertIn("Ingestion-labelled run", PANEL)


class TestPlacement(unittest.TestCase):
    def test_only_on_the_pending_page_of_a_wizard_project(self):
        users = [p.name for p in WEB.rglob("*.jsx") if "<IntegrationPanel" in p.read_text()]
        self.assertEqual(users, ["OperationView.jsx"])
        view = (WEB / "OperationView.jsx").read_text()
        pending = view[view.index("function PendingProject"):]
        self.assertIn("<IntegrationPanel />", pending[:pending.index("\n}\n")])
        self.assertNotIn("IntegrationPanel", (WEB / "EvidenceView.jsx").read_text())


class TestRecordedFile(unittest.TestCase):
    def test_no_project_identifiers(self):
        for pattern in (r"project-[0-9a-f]{8}", r"\b\d{11,12}\b", r"dtc-ingest-[0-9a-f]{8}", r"\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2}-\d+",
                        r"iam\.gserviceaccount\.com", r"dtc-evidence-ledger"):
            self.assertNotRegex(DEMO_TEXT, pattern)

    def test_figures_agree_with_the_pin(self):
        run = DEMO["replayed_run"]["run"]
        self.assertIn(run, PINS)
        cc = DEMO["engine"]["comparison_copy"]
        self.assertEqual(cc["pin_head"], PINS[run]["core_ledger_head_hash"])
        if cc["head_identical"]:
            self.assertEqual(cc["head"], cc["pin_head"])
        self.assertFalse(DEMO["engine"]["ingestion_labelled"]["head_identical"])

    def test_counts_are_consistent(self):
        c = DEMO["counts"]
        self.assertEqual(c["validated_readings"], c["readings"])
        self.assertEqual(c["bigquery_rows"], c["validated_readings"])
        self.assertEqual(c["raw_messages_stored"], c["published"])

    def test_example_message_is_the_engine_shape(self):
        from engine.readings import ALLOWED_FIELDS
        self.assertEqual(tuple(DEMO["example_message"]["data"]), ALLOWED_FIELDS)


class TestTextFixes(unittest.TestCase):
    def test_banner_no_longer_mentions_preview_projects(self):
        app = (WEB / "App.jsx").read_text()
        self.assertNotIn("projects marked preview", app)
        self.assertIn("projects made in the wizard are configuration only, not evidence", app)

    def test_wizard_review_step_says_what_creating_does(self):
        wizard = (WEB / "NewProject.jsx").read_text()
        self.assertNotIn("same rules it uses when loading a project", wizard)
        self.assertNotIn("records the setup", wizard)
        self.assertIn("saves it in this browser only, as configuration", wizard)

    def test_readme_new_project_sentence(self):
        readme = (ROOT / "README.md").read_text()
        self.assertNotIn("shown as previews from mock data", readme)
        self.assertIn("with no mock data and no evidence", readme)


if __name__ == "__main__":
    unittest.main()
