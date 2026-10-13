"""Tests for the grounded assistant, with a scripted fake model (no network)."""

import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

import app.main as main
from app.assistant import MAX_TOOL_ROUNDS, AssistantError, ask
from app.assistant_tools import Toolbox, ToolError
from projects import load_project
from app.evidence import verify_run, LocalStore
from tests.test_app import RUN, build_pack


class Chat:
    """A scripted stand-in for Gemini. Each step is either a list of tool
    calls [(name, args), ...] or a final answer string."""
    model_id = "fake-model"

    def __init__(self, script):
        self.script = list(script)
        self.seen = []  # tool results handed back to the model, per round

    def user(self, text): return ("user", text)
    def model(self, text): return ("model", text)

    def tool_results(self, results):
        self.seen.append(results)
        return ("tool", results)

    def generate(self, contents):
        step = self.script.pop(0)
        if isinstance(step, str):
            return ("model", step), [], step
        return ("model", step), step, None


class TestAssistant(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = Path(cls.tmp.name)
        head = build_pack(d)
        cls.ev = verify_run(LocalStore(d), RUN, "Full assurance cycle", head)
        os.environ["EVIDENCE_SOURCE"], os.environ["EVIDENCE_DIR"] = "local", str(d)
        os.environ["RUNS_CONFIG"] = str(d / "runs.json")
        main._cache.clear()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()
        os.environ.pop("RUNS_CONFIG", None)
        main._cache.clear()
        main._chat = None

    # -- tools -----------------------------------------------------------

    def test_tools_never_see_past_the_tick(self):
        tb = Toolbox(self.ev, 30, motor_only=False)
        self.assertTrue(all(e["tick"] <= 30 for e in tb.get_ledger_entries(limit=100)["entries"]))
        r = tb.get_readings("motor-op-001", "speed", 0, 79)
        self.assertEqual(r["ticks"][1], 30)
        self.assertEqual(max(x["tick"] for x in r["readings"]), 30)
        self.assertEqual(tb.get_status("motor-op-001")["twins"]["motor-op-001"]["status"], "flagged")
        self.assertEqual(tb.get_recalibration()["steps"], [])

    def test_motor_only_view_hides_the_rest(self):
        tb = Toolbox(self.ev, 70, motor_only=True)
        self.assertEqual(set(tb.get_status()["twins"]), {"motor-op-001"})
        self.assertEqual(set(tb.get_twin_definitions()["twins"]), {"motor-op-001"})
        self.assertNotIn("system_twin", tb.get_twin_definitions())
        with self.assertRaises(ToolError):
            tb.get_readings("compressor-op-001", "pressure", 0, 10)
        self.assertTrue(all(a["twin_id"] == "motor-op-001" for a in tb.get_anomalies()["anomalies"]))
        steps = tb.get_recalibration()["steps"]
        self.assertNotIn("composition_reassessment", [s["entry_type"] for s in steps])

    def test_solo_view_is_derived_from_the_projects_own_entry_twins_not_a_hardcoded_id(self):
        # Same result as the motor-only test above, but proving it comes from the project's
        # connections (via an explicitly passed project), not a fixed set of ids in the code.
        project = load_project()
        tb = Toolbox(self.ev, 70, motor_only=True, project=project)
        self.assertEqual(tb._solo_ids, {"motor-op-001"})
        self.assertEqual(set(tb.get_status()["twins"]), {"motor-op-001"})

    def test_unknown_tool_and_bad_arguments_are_refused(self):
        tb = Toolbox(self.ev, 10, motor_only=False)
        with self.assertRaises(ToolError):
            tb.call("delete_ledger", {})
        with self.assertRaises(ToolError):
            tb.call("call", {"name": "get_status"})
        with self.assertRaises(ToolError):
            tb.call("get_status", {"bogus": 1})

    # -- conversation loop ----------------------------------------------

    def test_answer_is_grounded_in_recorded_tool_calls(self):
        chat = Chat([[("get_status", {"twin_id": "compressor-system-op-001"})], "It is flagged because ... (#19)."])
        out = ask(chat, Toolbox(self.ev, 65, False), "Why is the system flagged?", [])
        self.assertEqual(out["tool_calls"], [{"name": "get_status", "args": {"twin_id": "compressor-system-op-001"}}])
        result = chat.seen[0][0][1]
        self.assertEqual(result["twins"]["compressor-system-op-001"]["status"], "flagged")
        self.assertEqual(out["tick"], 65)
        self.assertIn("never used in any assurance decision", out["notice"])

    def test_tool_errors_are_returned_to_the_model_not_raised(self):
        chat = Chat([[("get_readings", {"twin_id": "compressor-op-001", "channel_id": "x", "from_tick": 0, "to_tick": 5})],
                     "I cannot see that."])
        out = ask(chat, Toolbox(self.ev, 20, True), "Show compressor data", [])
        self.assertIn("error", chat.seen[0][0][1])
        self.assertEqual(out["answer"], "I cannot see that.")

    def test_runaway_tool_loops_are_stopped(self):
        chat = Chat([[("get_current_tick", {})]] * 10)
        with self.assertRaises(AssistantError):
            ask(chat, Toolbox(self.ev, 5, False), "loop", [])

    def test_tool_round_cap_is_eight(self):
        self.assertEqual(MAX_TOOL_ROUNDS, 8)
        # 7 rounds of lookups, then an answer on the 8th model call: answered.
        chat = Chat([[("get_current_tick", {})]] * 7 + ["Done."])
        out = ask(chat, Toolbox(self.ev, 5, False), "deep question", [])
        self.assertEqual((out["answer"], out["model_calls"], out["tool_rounds"]), ("Done.", 8, 7))
        # Still asking for lookups on the 8th call: stopped there, with the readable reply.
        chat = Chat([[("get_current_tick", {})]] * 8 + ["never reached"])
        with self.assertRaisesRegex(AssistantError, "too many evidence lookups; try a narrower question"):
            ask(chat, Toolbox(self.ev, 5, False), "deeper question", [])
        self.assertEqual(chat.script, ["never reached"])

    # -- endpoint ---------------------------------------------------------

    def test_endpoint_validation_and_rate_limit(self):
        client = TestClient(main.app)
        for store in (main._ask_minute, main._ask_day, main._ask_global):
            store.clear()
        main._chat = Chat(["ok"] * 20)
        self.assertEqual(client.post(f"/api/runs/{RUN}/ask", json={"tick": 5, "question": "x" * 801}).status_code, 422)
        for _ in range(main.ASK_PER_MINUTE):
            r = client.post(f"/api/runs/{RUN}/ask", json={"tick": 5, "question": "hello"})
            self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(client.post(f"/api/runs/{RUN}/ask", json={"tick": 5, "question": "hello"}).status_code, 429)
        for store in (main._ask_minute, main._ask_day, main._ask_global):
            store.clear()


if __name__ == "__main__":
    unittest.main()
