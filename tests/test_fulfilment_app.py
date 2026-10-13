"""The Fulfilment cell in the app: served beside the compressor train through the same
loading and verification path, with each project's own opening view and run labels.
The compressor train is checked to be served exactly as before."""

import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.evidence import load_runs_config
from tests.test_app import RUN as COMPRESSOR_RUN, build_pack
from tests.test_sealed_explanations import RUN as CELL_RUN, cell_run, write_pack

ROOT = Path(__file__).resolve().parent.parent
PINNED = {"assurance-demo_full_cycle-seed42": "f8a4f238a88a7161ae71eacb85e36f436a42f8797db9ec04cd63e31caee3e27e",
          "assurance-demo_wear_to_nullified-seed42": "8568b4a5491bbb2fcfd53cd7d1ae86aee7c8211986f053f211de5e14fc869708",
          "assurance-faults_showcase-seed42": "f48b3e89b3ead0dc40dfd9be48d1d0ae9dc23de228a6089b4a88466c7feac028"}
MOCK_NAMES = ("FleetFlow", "fleetflow", "BeltLine", "beltline", "AMR-600", "amr-600", "PS-2 pick", "vendor-e/ps-2")


class TestBothProjects(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        build_pack(d)
        compressor = json.loads((d / "runs.json").read_text())
        write_pack(d, cell_run())
        cell = json.loads((d / "runs.json").read_text())
        (d / "runs.json").write_text(json.dumps({"default": compressor["default"],
                                                 "runs": compressor["runs"] + cell["runs"]}))
        os.environ["EVIDENCE_SOURCE"], os.environ["EVIDENCE_DIR"] = "local", str(d)
        os.environ["RUNS_CONFIG"] = str(d / "runs.json")
        main._cache.clear()
        cls.client = TestClient(main.app)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        os.environ.pop("RUNS_CONFIG", None)
        main._cache.clear()

    def get(self, url):
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.json()

    def test_both_projects_are_listed_and_each_serves_its_own_runs(self):
        ids = {p["project_id"] for p in self.get("/api/projects")["projects"]}
        self.assertEqual(ids, {"oil-gas-compressor-train", "amr-fulfilment-cell"})
        cell_runs = [r["run"] for r in self.get("/api/projects/amr-fulfilment-cell/runs")["runs"]]
        self.assertEqual(cell_runs, [CELL_RUN])
        self.assertNotIn(CELL_RUN, [r["run"] for r in self.get("/api/projects/oil-gas-compressor-train/runs")["runs"]])

    def test_each_project_opens_in_its_own_view(self):
        cell, compressor = self.get("/api/projects/amr-fulfilment-cell"), self.get("/api/projects/oil-gas-compressor-train")
        self.assertEqual((cell["opens_in"], cell["evidence_panels"]), ("system", "extended"))
        self.assertEqual((compressor["opens_in"], compressor["evidence_panels"]), ("entry", "standard"))
        self.assertEqual(cell["entry_twins"], ["dispatcher-op-001"])

    def test_the_cell_run_passes_every_check_through_the_app(self):
        m = self.get(f"/api/runs/{CELL_RUN}/meta")
        v = m["verification"]
        self.assertTrue(v["valid"])
        self.assertEqual(sum(c["passed"] for c in v["checks"]), 11)
        self.assertEqual(len(v["checks"]), 11)
        self.assertEqual(m["ai_explanations"]["status"], "available")

    def test_run_label_comes_from_the_scenario_file(self):
        label = self.get(f"/api/runs/{CELL_RUN}/meta")["label"]
        self.assertEqual(label, json.loads((ROOT / "scenarios" / "amr_full_cycle.json").read_text())["label"])
        for name in ("amr_wear_to_nullified", "amr_faults_showcase"):
            self.assertTrue(main.scenario_label(name).startswith("Synthetic data."))
        self.assertIn("deliberately introduced", main.scenario_label("amr_faults_showcase"))
        self.assertIsNone(self.get(f"/api/runs/{COMPRESSOR_RUN}/meta")["label"])  # the compressor train shows no new line

    def test_the_cascade_view_follows_the_ledger(self):
        cascade = self.get(f"/api/runs/{CELL_RUN}/view?tick=79")["cascade"]
        self.assertEqual([c["seq"] for c in cascade], [63, 68])
        chain = [b["ledger_seq"] for b in cascade[1]["chain"]]
        self.assertTrue({39, 41, 42, 62, 63, 66, 67, 68} <= set(chain))
        self.assertEqual(self.get(f"/api/runs/{CELL_RUN}/view?tick=50")["cascade"], [])  # nothing beyond the tick on screen
        self.assertEqual(self.get(f"/api/runs/{COMPRESSOR_RUN}/view?tick=79")["cascade"], [])  # standard panels only

    def test_no_mock_names_and_no_banned_term_in_served_content(self):
        served = json.dumps([self.get("/api/projects"), self.get("/api/registry"),
                             self.get("/api/projects/amr-fulfilment-cell"), self.get(f"/api/runs/{CELL_RUN}/meta"),
                             self.get(f"/api/runs/{CELL_RUN}/view?tick=79")])
        for name in MOCK_NAMES:
            self.assertNotIn(name, served)
        self.assertNotIn("lidar", served.lower())
        ids = {e["registry_id"] for e in self.get("/api/registry")["entries"]}
        self.assertTrue({"vendor-c/dispatch-d1", "vendor-d/robot-r2", "vendor-e/pick-p4"} <= ids)

    def test_web_sources_and_build_carry_no_mock_names(self):
        files = [p for p in (ROOT / "web" / "src").rglob("*") if p.suffix in (".js", ".jsx", ".css")]
        dist = ROOT / "web" / "dist"
        files += [p for p in dist.rglob("*") if p.suffix in (".js", ".html", ".css")] if dist.exists() else []
        for p in files:
            text = p.read_text(encoding="utf-8")
            for name in MOCK_NAMES:
                self.assertNotIn(name, text, f"{name} in {p}")
            self.assertIsNone(re.search(r"lidar", text, re.IGNORECASE), f"lidar in {p}")
        projects = (ROOT / "web" / "src" / "platform" / "model" / "projects.js").read_text()
        self.assertIn("export const PREVIEW_PROJECTS = []", projects)

    def test_the_compressor_train_is_served_as_before(self):
        self.assertEqual({r["run"]: r["core_ledger_head_hash"] for r in load_runs_config_from_repo()["runs"]}, PINNED)
        self.assertEqual(self.client.get("/").status_code, 200)
        detail = self.get("/api/projects/oil-gas-compressor-train")
        self.assertEqual(detail["entry_twins"], ["motor-op-001"])
        m = self.get(f"/api/runs/{COMPRESSOR_RUN}/meta")
        self.assertTrue(m["verification"]["valid"])
        self.assertEqual(self.get(f"/api/runs/{COMPRESSOR_RUN}/view?tick=40")["state"]["twins"]["motor-op-001"]["status"], "nullified")


def load_runs_config_from_repo() -> dict:
    """The served pins in app/config/runs.json, whatever RUNS_CONFIG points at."""
    saved = os.environ.pop("RUNS_CONFIG", None)
    try:
        return load_runs_config()
    finally:
        if saved is not None:
            os.environ["RUNS_CONFIG"] = saved


if __name__ == "__main__":
    unittest.main()
