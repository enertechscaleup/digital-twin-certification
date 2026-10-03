"""Tests for twin identity and version lineage (engine/lineage.py) behind the vendor boundary."""

import copy
import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from engine.boundary import RemoteTwin
from engine.lineage import (PROBES_SEALED, REGISTERED, LineageError, assign_identities, load_identities,
                            verify_lineage)
from engine.registry import load_registry
from engine.run import run_assurance
from telemetry.faults import Scenario
from telemetry.models import TwinModel
from tests.test_recalibration import stale_owner
from vendor.endpoint import simulated_vendors
from vendor.recalibrate import recalibrate

ROOT = Path(__file__).resolve().parent.parent
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
MOTOR, SYSTEM = "motor-op-001", "compressor-system-op-001"
# The readings and per-tick timeline files of the three locked runs (their manifests' SHA-256).
LOCKED = {
    "demo_full_cycle": ("0b3371016a9577b7cf0d5d1d304623b5f24810581d691fe7ae3465ab53cab1d9",
                        "e953b34058e2af4ae2ba71519e5d864327994385d2f1e3bf53a656e19c5e3417"),
    "demo_wear_to_nullified": ("5cc1a1c271d1b86822100551479cb780290dbdecc75107fc8f26e13c80a3b1c0",
                               "da22a644f1930e70e6af371a1a943d8a1f2ebd79c8e43713f5bd3072c21217c9"),
    "faults_showcase": ("f2d97670d5732eee443fc97a7839117a5c28b346a6e71eed9fa936297e37dd8a",
                        "eb683aac86eb4995ef4c9f6bb0d9f3436d205cf2bd129a9c9a1a31d90a21f406"),
}


def scenario(name: str) -> Scenario:
    return Scenario.from_dict(json.loads((ROOT / "scenarios" / f"{name}.json").read_text()))


def run(name: str, **vendor_kw):
    return run_assurance(scenario(name), simulated_vendors(**vendor_kw), seed=42, start_time=START,
                         code_commit="commit-under-test")


def registrations(result) -> list[dict]:
    return [e["payload"] for e in result.ledger.entries if e["entry_type"] == REGISTERED]


def jsonl_sha256(rows: list[dict]) -> str:
    return hashlib.sha256("".join(json.dumps(r) + "\n" for r in rows).encode()).hexdigest()


class TestLockedRunsDecisionsUnchanged(unittest.TestCase):
    def test_same_data_and_same_decisions_as_the_locked_runs(self):
        """Behind the vendor boundary, with lineage and joint tests, each scenario still produces
        exactly the locked runs' readings and per-tick statuses: the record grew, the decisions
        did not change."""
        for name, (readings, timeline) in LOCKED.items():
            r = run(name)
            self.assertEqual(jsonl_sha256(r.readings), readings, name)
            self.assertEqual(jsonl_sha256(r.timeline), timeline, name)

    def test_pre_fingerprint_evidence_is_labelled_not_failed(self):
        legacy = [e for e in run("demo_wear_to_nullified").ledger.entries if e["entry_type"] == "run_started"]
        check = verify_lineage(legacy, [])
        self.assertEqual((check.recorded, check.valid), (False, True))


class TestMeasuredFingerprint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = registrations(run("faults_showcase"))[0]

    def test_changes_when_behaviour_changes(self):
        changed = TwinModel("motor", {**TwinModel("motor").params, "vib_base": 0.51})
        other = registrations(run("faults_showcase", twins={"motor": changed}))[0]
        self.assertNotEqual(other["twin"]["fingerprint"], self.base["twin"]["fingerprint"])

    def test_does_not_change_with_the_label_or_the_platform_commit(self):
        relabelled = registrations(run("faults_showcase", twins={"motor": TwinModel("motor", version="9.9.9")}))[0]
        self.assertEqual(relabelled["twin"]["fingerprint"], self.base["twin"]["fingerprint"])
        other = run_assurance(scenario("faults_showcase"), simulated_vendors(), seed=42, start_time=START,
                              code_commit="another-commit")
        self.assertEqual(registrations(other)[0]["twin"]["fingerprint"], self.base["twin"]["fingerprint"])

    def test_measured_is_the_evidence_and_declared_only_a_claim(self):
        p = self.base
        self.assertEqual(p["twin"]["fingerprint"], p["measured"]["fingerprint"])
        self.assertTrue(p["measured"]["authority"].startswith("evidence"))
        self.assertTrue(p["declared"]["authority"].startswith("claim"))
        self.assertNotEqual(p["declared"]["fingerprint"], p["measured"]["fingerprint"])
        self.assertNotIn("params", json.dumps(p))

    def test_probe_set_is_sealed_before_the_twin_is_queried(self):
        entries = run("faults_showcase").ledger.entries
        sealed = next(i for i, e in enumerate(entries) if e["entry_type"] == PROBES_SEALED)
        registered = next(i for i, e in enumerate(entries) if e["entry_type"] == REGISTERED)
        self.assertLess(sealed, registered)
        self.assertEqual(entries[sealed]["payload"]["probe_set_sha256"],
                         entries[registered]["payload"]["measured"]["inputs"]["probe_set_sha256"])

    def test_the_platform_never_records_twin_parameters(self):
        r = run("demo_full_cycle")
        text = json.dumps(r.ledger.entries)
        self.assertNotIn("speed_per_volt", text)
        self.assertNotIn("params", json.dumps([e["payload"].get("submission", {}) for e in r.ledger.entries]))


class TestIdentity(unittest.TestCase):
    def test_every_twin_in_the_project_has_a_permanent_identity(self):
        self.assertEqual(assign_identities(load_registry(), "oil-gas-compressor-train", load_identities()), [])

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
            run_assurance(scenario("faults_showcase"), simulated_vendors(), seed=42, start_time=START, identities=[])

    def test_design_and_operational_stages_share_one_identity(self):
        issued = [e["payload"] for e in run("faults_showcase").ledger.of_type("assurance_issued")
                  if e["payload"]["twin_id"].startswith("motor")]
        self.assertEqual({p["twin_id"] for p in issued}, {"motor-design", "motor-op-001"})
        self.assertEqual(len({p["twin_ref"]["identity"] for p in issued}), 1)


def _refs(obj):
    from engine.lineage import _refs as refs
    return list(refs(obj))


class TestFullCycleLineage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("demo_full_cycle")
        cls.entries = cls.r.ledger.entries
        regs = registrations(cls.r)
        cls.motor = [p for p in regs if p.get("twin_type") == "motor"]
        cls.system = [p for p in regs if p["composition"] == "system"]

    def test_the_ledger_verifies(self):
        check = verify_lineage(self.entries, self.r.readings, self.r.exchange)
        self.assertTrue(check.valid, check.reason)
        self.assertEqual(check.versions, 5)
        self.assertEqual(check.exchanges, len(self.r.exchange))

    def test_every_entry_cites_a_version(self):
        uncited = [e["entry_type"] for e in self.entries
                   if e["entry_type"] not in ("run_started", REGISTERED, PROBES_SEALED) and not _refs(e["payload"])]
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
                self.assertEqual(p["twin_ref"]["fingerprint"], v1 if p["tick"] < at else v2, e["seq"])

    def test_system_gets_a_new_version_and_a_fresh_composition_record(self):
        s1, s2 = self.system
        self.assertEqual(s2["parent_fingerprint"], s1["twin"]["fingerprint"])
        versions = {c["twin_type"]: c["version"] for c in s2["constituents"]}
        self.assertEqual(versions, {"motor": "1.1.0", "compressor": "1.0.0"})
        record = next(e["payload"] for e in self.entries if e["entry_type"] == "composition_reassessment")
        self.assertEqual(record["system_ref"], s2["twin"])
        self.assertEqual({c["twin_type"]: c["version"] for c in record["constituent_refs"]}, versions)

    def test_cascade_reasons_name_the_constituents_version(self):
        status = self.r.ledger.of_type("assurance_status_changed") + self.r.ledger.of_type("assurance_reason_added")
        cascades = [r for e in status if e["payload"]["twin_id"] == SYSTEM
                    for r in e["payload"]["new_reasons"] if r["cause"] == "cascade"]
        self.assertTrue(cascades)
        self.assertTrue(all(r["constituent_ref"]["version"] == "1.0.0" for r in cascades))


class TestRejectedVersions(unittest.TestCase):
    def test_a_rejected_version_stays_in_the_lineage_and_out_of_operation(self):
        r = run("demo_full_cycle", recalibrator=stale_owner)
        check = verify_lineage(r.ledger.entries, r.readings, r.exchange)
        self.assertTrue(check.valid, check.reason)
        stale = next(p for p in registrations(r) if p["twin"]["version"] == "1.1.0-stale")
        rejected = r.ledger.of_type("recalibration_rejected")[0]["payload"]
        self.assertEqual(rejected["candidate_ref"], stale["twin"])
        self.assertEqual(rejected["twin_ref"]["version"], "1.0.0")
        self.assertEqual(len([p for p in registrations(r) if p["composition"] == "system"]), 1)
        self.assertEqual(r.ledger.of_type("composition_test")[-1]["payload"]["trigger"], "initial build")
        self.assertEqual(r.ledger.entries[-1]["payload"]["final_refs"][MOTOR]["version"], "1.0.0")

    def test_a_label_that_now_behaves_differently_is_rejected(self):
        def same_label(twin_type, current, released, envelopes):
            return recalibrate(twin_type, current, released, envelopes, current.version).to_dict()

        r = run("demo_full_cycle", recalibrator=same_label)
        rejected = r.ledger.of_type("recalibration_rejected")[0]["payload"]
        self.assertIn("now behaves differently", rejected["reason"])
        self.assertEqual(len([p for p in registrations(r) if p.get("twin_type") == "motor"]), 1)
        self.assertNotIn("recalibration_submitted", [e["entry_type"] for e in r.ledger.entries])
        self.assertTrue(verify_lineage(r.ledger.entries, r.readings, r.exchange).valid)


class TestTamperedLineageIsCaught(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r = run("demo_full_cycle")

    def check(self, edit) -> str:
        entries, readings, exchange = (copy.deepcopy(x) for x in (self.r.ledger.entries, self.r.readings, self.r.exchange))
        edit(entries, readings, exchange)
        result = verify_lineage(entries, readings, exchange)
        self.assertFalse(result.valid)
        return result.reason

    def first(self, entries, kind):
        return next(e for e in entries if e["entry_type"] == kind)

    def test_a_probe_response_changed_after_sealing(self):
        def edit(_, __, exchange):
            exchange[0]["outputs"]["speed"] += 1
        self.assertIn("does not match its seal", self.check(edit))

    def test_measured_inputs_changed_after_sealing(self):
        def edit(entries, _, __):
            self.first(entries, REGISTERED)["payload"]["measured"]["inputs"]["interface"][0]["tolerance_pct"] = 9
        self.assertIn("does not match the inputs", self.check(edit))

    def test_an_exchange_not_sealed_in_the_ledger(self):
        def edit(_, __, exchange):
            exchange.append({**exchange[0], "batch": "x9999"})
        self.assertIn("not sealed", self.check(edit))

    def test_evidence_cites_an_unregistered_version(self):
        def edit(entries, _, __):
            self.first(entries, "anomaly_opened")["payload"]["twin_ref"]["fingerprint"] = "0" * 64
        self.assertIn("not registered", self.check(edit))

    def test_an_entry_without_a_citation(self):
        def edit(entries, _, __):
            del self.first(entries, "assurance_status_changed")["payload"]["twin_ref"]
        self.assertIn("does not cite", self.check(edit))

    def test_a_reading_from_an_unregistered_version(self):
        def edit(_, readings, __):
            readings[100]["twin_version"] = "1.0.1"
        self.assertIn("does not resolve to a registered version", self.check(edit))

    def test_a_parent_from_another_twin(self):
        def edit(entries, _, __):
            regs = [e for e in entries if e["entry_type"] == REGISTERED]
            regs[3]["payload"]["parent_fingerprint"] = regs[1]["payload"]["twin"]["fingerprint"]
        self.assertIn("parent is not an earlier version of the same twin", self.check(edit))


class TestTheTestedTwinIsTheFingerprintedTwin(unittest.TestCase):
    def test_a_twin_that_answers_verification_differently_from_its_probes_is_caught(self):
        """A twin that recognises the probe set and answers it 'correctly', but behaves
        differently once tested, is caught: verification answers must equal probe answers."""
        class TwoFaced:
            def __init__(self):
                self.calls = 0

            def __call__(self, message):
                req = json.loads(message)
                if req["op"] == "predict":
                    self.calls += 1
                    out = TwinModel("motor").predict(req["inputs"])
                    if self.calls > 41:  # after the probe set, answer differently
                        out = {k: v * 1.001 for k, v in out.items()}
                    return json.dumps({"outputs": out})
                return json.dumps({"version": "1.0.0", "declared_fingerprint": "x", "declared_method": "m"})

        from engine.boundary import InProcessConnection
        vendors = simulated_vendors()
        vendors["motor"] = InProcessConnection(TwoFaced())
        r = run_assurance(scenario("faults_showcase"), vendors, seed=42, start_time=START)
        check = verify_lineage(r.ledger.entries, r.readings, r.exchange)
        self.assertFalse(check.valid)
        self.assertIn("answered differently from the twin fingerprinted", check.reason)


if __name__ == "__main__":
    unittest.main()
