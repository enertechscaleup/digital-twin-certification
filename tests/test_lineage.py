"""Tests for twin identity and version lineage (engine/lineage.py)."""

import copy
import json
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from engine.ledger import sha256_hex, verify_chain
from engine.lineage import (REGISTERED, LineageError, assign_identities, legacy_projection, load_identities,
                            product_fingerprint_inputs, verify_lineage)
from engine.registry import load_registry
from engine.run import run_assurance
from telemetry.faults import Scenario
from telemetry.models import TwinModel
from tests.test_recalibration import stale_owner
from vendor.advise import recommend
from vendor.recalibrate import owner_for_platform, recalibrate

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
SCENARIOS = ("demo_full_cycle", "demo_wear_to_nullified", "faults_showcase")
MOTOR, SYSTEM = "motor-op-001", "compressor-system-op-001"


def scenario(name: str) -> Scenario:
    return Scenario.from_dict(json.loads((ROOT / "scenarios" / f"{name}.json").read_text()))


def run(name: str, recalibrator=owner_for_platform, **kw):
    return run_assurance(scenario(name), seed=42, start_time=START, recalibrator=recalibrator, advisor=recommend,
                         code_commit="commit-under-test", **kw)


def registrations(result) -> list[dict]:
    return [e["payload"] for e in result.ledger.entries if e["entry_type"] == REGISTERED]


def fingerprint(product, model) -> str:
    return sha256_hex(product_fingerprint_inputs(product, model))


class TestLockedRunsAreUntouched(unittest.TestCase):
    def test_lineage_is_purely_additive(self):
        """Taking lineage back out of a regenerated run reproduces the pinned, locked evidence
        hash for hash: no existing entry, value or order changed; lineage only added."""
        pins = {r["run"]: r["core_ledger_head_hash"]
                for r in json.loads((ROOT / "app" / "config" / "runs.json").read_text())["runs"]}
        for name in SCENARIOS:
            legacy = legacy_projection(run(name).ledger.entries)
            self.assertTrue(verify_chain(legacy).valid)
            self.assertEqual(legacy[-1]["entry_hash"], pins[f"assurance-{name}-seed42"], name)

    def test_pre_fingerprint_evidence_is_labelled_not_failed(self):
        legacy = legacy_projection(run("demo_wear_to_nullified").ledger.entries)
        check = verify_lineage(legacy, [])
        self.assertEqual((check.recorded, check.valid), (False, True))


class TestFingerprint(unittest.TestCase):
    def setUp(self):
        self.motor = load_registry().products["motor"]
        self.model = TwinModel("motor")
        self.fp = fingerprint(self.motor, self.model)

    def test_changes_with_anything_that_determines_behaviour(self):
        params = TwinModel("motor", {**self.model.params, "speed_per_volt": 3.7})
        out = self.motor.outputs[0]
        ranged = replace(self.motor, channels=tuple(replace(c, env_max=c.env_max + 1) if c == out else c
                                                    for c in self.motor.channels))
        tolerant = replace(self.motor, channels=tuple(replace(c, tolerance_pct=6) if c == out else c
                                                      for c in self.motor.channels))

        class OtherFormula(TwinModel):
            formula_id = "synthetic-motor/2"

        for changed in (fingerprint(self.motor, params), fingerprint(ranged, self.model),
                        fingerprint(tolerant, self.model), fingerprint(self.motor, OtherFormula("motor"))):
            self.assertNotEqual(changed, self.fp)

    def test_ignores_what_does_not(self):
        renamed = replace(self.motor, channels=tuple(replace(c, name="x") for c in self.motor.channels),
                          vendor="someone else", asset_id="another-asset")
        relabelled = TwinModel("motor", version="9.9.9")
        self.assertEqual(fingerprint(renamed, self.model), self.fp)
        self.assertEqual(fingerprint(self.motor, relabelled), self.fp)

    def test_code_commit_is_sealed_beside_the_fingerprint_not_inside_it(self):
        a = registrations(run("faults_showcase"))[0]
        b = registrations(run_assurance(scenario("faults_showcase"), seed=42, start_time=START,
                                        code_commit="another-commit"))[0]
        self.assertEqual(a["twin"]["fingerprint"], b["twin"]["fingerprint"])
        self.assertEqual((a["code_commit"], b["code_commit"]), ("commit-under-test", "another-commit"))


class TestIdentity(unittest.TestCase):
    def test_every_twin_in_the_project_has_a_permanent_identity(self):
        reg = load_registry()
        self.assertEqual(assign_identities(reg, "oil-gas-compressor-train", load_identities()), [])

    def test_new_twins_get_random_identities_and_existing_ones_never_change(self):
        reg = load_registry()
        a = assign_identities(reg, "oil-gas-compressor-train", [], today="2026-10-03")
        b = assign_identities(reg, "oil-gas-compressor-train", [], today="2026-10-03")
        self.assertEqual(len(a), 3)
        self.assertTrue(all(x["identity"] != y["identity"] for x, y in zip(a, b)), "identity must be random")
        existing = load_identities()[:1]
        new = assign_identities(reg, "oil-gas-compressor-train", existing)
        self.assertNotIn(existing[0]["identity"], [n["identity"] for n in new])
        self.assertEqual(len(new), 2)

    def test_a_run_refuses_twins_without_an_identity(self):
        with self.assertRaises(LineageError):
            run_assurance(scenario("faults_showcase"), seed=42, start_time=START, identities=[])

    def test_design_and_operational_stages_share_one_identity(self):
        r = run("faults_showcase")
        issued = [e["payload"] for e in r.ledger.of_type("assurance_issued") if e["payload"]["twin_id"].startswith("motor")]
        self.assertEqual({p["twin_id"] for p in issued}, {"motor-design", "motor-op-001"})
        self.assertEqual(len({p["twin_ref"]["identity"] for p in issued}), 1)


class TestFullCycleLineage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("demo_full_cycle")
        cls.entries = cls.r.ledger.entries
        regs = registrations(cls.r)
        cls.motor = [p for p in regs if p.get("twin_type") == "motor"]
        cls.system = [p for p in regs if p["composition"] == "system"]

    def test_the_ledger_verifies(self):
        check = verify_lineage(self.entries, self.r.readings)
        self.assertTrue(check.valid, check.reason)
        self.assertEqual(check.versions, 5)

    def test_every_entry_cites_a_version(self):
        uncited = [e["entry_type"] for e in self.entries
                   if e["entry_type"] not in ("run_started", REGISTERED) and "identity" not in json.dumps(e["payload"])]
        self.assertEqual(uncited, [])

    def test_versions_are_sealed_before_any_evidence_about_them(self):
        first_ref = {}
        for e in self.entries:
            for fp in {r["fingerprint"] for r in _refs(e["payload"])}:
                first_ref.setdefault(fp, e)
        for e in self.entries:
            if e["entry_type"] == REGISTERED:
                self.assertIs(first_ref[e["payload"]["twin"]["fingerprint"]], e)

    def test_recalibration_adds_a_child_version_registered_on_submission(self):
        v1, v2 = self.motor
        self.assertEqual((v1["twin"]["version"], v2["twin"]["version"]), ("1.0.0", "1.1.0"))
        self.assertIsNone(v1["parent_fingerprint"])
        self.assertEqual(v2["parent_fingerprint"], v1["twin"]["fingerprint"])
        self.assertEqual(v1["twin"]["identity"], v2["twin"]["identity"])
        kinds = [e["entry_type"] for e in self.entries]
        reg = next(i for i, e in enumerate(self.entries)
                   if e["entry_type"] == REGISTERED and e["payload"]["twin"]["version"] == "1.1.0")
        self.assertEqual(kinds[reg + 1:reg + 3], ["recalibration_submitted", "verification"])
        self.assertEqual(self.entries[reg + 2]["payload"]["twin_ref"]["version"], "1.1.0")

    def test_old_versions_history_stays_attributable_to_it(self):
        v1, v2 = (p["twin"]["fingerprint"] for p in self.motor)
        at = next(e["payload"]["at_tick"] for e in self.entries if e["entry_type"] == "recalibration_requested")
        for e in self.entries:
            p = e["payload"]
            if p.get("twin_id") == MOTOR and e["entry_type"] in ("assurance_status_changed", "anomaly_opened"):
                expected = v1 if p["tick"] < at else v2
                self.assertEqual(p["twin_ref"]["fingerprint"], expected, e["seq"])

    def test_system_gets_a_new_version_and_a_fresh_composition_record(self):
        s1, s2 = self.system
        self.assertEqual(s2["parent_fingerprint"], s1["twin"]["fingerprint"])
        motor_in = {c["twin_type"]: c["version"] for c in s2["constituents"]}
        self.assertEqual(motor_in, {"motor": "1.1.0", "compressor": "1.0.0"})
        record = next(e["payload"] for e in self.entries if e["entry_type"] == "composition_reassessment")
        self.assertEqual(record["system_ref"], s2["twin"])
        self.assertEqual({c["twin_type"]: c["version"] for c in record["constituent_refs"]}, motor_in)

    def test_composition_records_cite_every_constituent_by_exact_version(self):
        for e in self.r.ledger.of_type("composition_assured"):
            refs = e["payload"]["constituent_refs"]
            self.assertEqual([c["twin_type"] for c in refs], ["motor", "compressor"])
            self.assertTrue(all(len(c["fingerprint"]) == 64 and c["identity"] and c["version"] for c in refs))

    def test_cascade_reasons_name_the_constituents_version(self):
        status = self.r.ledger.of_type("assurance_status_changed") + self.r.ledger.of_type("assurance_reason_added")
        cascades = [r for e in status if e["payload"]["twin_id"] == SYSTEM
                    for r in e["payload"]["new_reasons"] if r["cause"] == "cascade"]
        self.assertTrue(cascades)
        self.assertTrue(all(r["constituent_ref"]["version"] == "1.0.0" for r in cascades))


def _refs(obj):
    from engine.lineage import _refs as refs
    return list(refs(obj))


class TestRejectedVersions(unittest.TestCase):
    def test_a_rejected_version_stays_in_the_lineage_and_out_of_operation(self):
        r = run("demo_full_cycle", recalibrator=stale_owner)
        check = verify_lineage(r.ledger.entries, r.readings)
        self.assertTrue(check.valid, check.reason)
        stale = next(p for p in registrations(r) if p["twin"]["version"] == "1.1.0-stale")
        rejected = r.ledger.of_type("recalibration_rejected")[0]["payload"]
        self.assertEqual(rejected["candidate_ref"], stale["twin"])
        self.assertEqual(rejected["twin_ref"]["version"], "1.0.0")
        self.assertEqual(len([p for p in registrations(r) if p["composition"] == "system"]), 1)
        self.assertEqual(r.ledger.entries[-1]["payload"]["final_refs"][MOTOR]["version"], "1.0.0")

    def test_reusing_a_version_label_for_different_content_is_rejected(self):
        def same_label(twin_type, current, released, envelopes):
            return recalibrate(twin_type, current, released, envelopes, current.version).to_dict()

        r = run("demo_full_cycle", recalibrator=same_label)
        rejected = r.ledger.of_type("recalibration_rejected")[0]["payload"]
        self.assertIn("already registered with different content", rejected["reason"])
        self.assertEqual(len([p for p in registrations(r) if p.get("twin_type") == "motor"]), 1)
        self.assertNotIn("recalibration_submitted", [e["entry_type"] for e in r.ledger.entries])
        self.assertTrue(verify_lineage(r.ledger.entries, r.readings).valid)


class TestTamperedLineageIsCaught(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("demo_full_cycle")

    def check(self, edit, readings=None) -> str:
        entries = copy.deepcopy(self.r.ledger.entries)
        rows = copy.deepcopy(self.r.readings if readings is None else readings)
        edit(entries, rows)
        result = verify_lineage(entries, rows)
        self.assertFalse(result.valid)
        return result.reason

    def first(self, entries, kind, **match):
        return next(e for e in entries if e["entry_type"] == kind
                    and all(e["payload"].get(k) == v for k, v in match.items()))

    def test_fingerprint_inputs_changed_after_sealing(self):
        def edit(entries, _):
            self.first(entries, REGISTERED)["payload"]["fingerprint_inputs"]["params"]["speed_per_volt"] = 4.0
        self.assertIn("does not match the inputs", self.check(edit))

    def test_evidence_cites_an_unregistered_version(self):
        def edit(entries, _):
            self.first(entries, "anomaly_opened")["payload"]["twin_ref"]["fingerprint"] = "0" * 64
        self.assertIn("not registered", self.check(edit))

    def test_tested_parameters_differ_from_the_fingerprinted_version(self):
        def edit(entries, _):
            self.first(entries, "verification")["payload"]["twin_params"]["speed_per_volt"] = 4.0
        self.assertIn("tested parameters differ", self.check(edit))

    def test_an_entry_without_a_citation(self):
        def edit(entries, _):
            del self.first(entries, "assurance_status_changed")["payload"]["twin_ref"]
        self.assertIn("does not cite", self.check(edit))

    def test_a_reading_from_an_unregistered_version(self):
        def edit(_, rows):
            rows[100]["twin_version"] = "1.0.1"
        self.assertIn("does not resolve to a registered version", self.check(edit))

    def test_a_parent_from_another_twin(self):
        def edit(entries, _):
            regs = [e for e in entries if e["entry_type"] == REGISTERED]
            regs[3]["payload"]["parent_fingerprint"] = regs[1]["payload"]["twin"]["fingerprint"]  # motor 1.1.0 <- compressor
        self.assertIn("parent is not an earlier version of the same twin", self.check(edit))


if __name__ == "__main__":
    unittest.main()
