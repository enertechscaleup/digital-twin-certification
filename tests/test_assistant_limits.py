"""The live assistant's per-call timeout, retries and per-question limit, and that the
sealed-explanation pipeline is left without them. Most tests run the real google-genai SDK against a
local HTTP stub that answers each attempt from a script (hang, 5xx, 4xx or a normal answer), so the
SDK's own timeout and retry rules are exercised."""

import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import app.assistant as assistant
import explain.gemini as gemini
from app.assistant import GEMINI_5XX, GEMINI_SLOW, TOO_SLOW, AssistantError, GeminiChat, ask
from app.assistant_tools import Toolbox
from app.evidence import LocalStore, verify_run
from tests.test_app import RUN, build_pack

ANSWER = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}
ERRORS = {503: "UNAVAILABLE", 504: "DEADLINE_EXCEEDED", 400: "INVALID_ARGUMENT", 403: "PERMISSION_DENIED"}


class Stub(BaseHTTPRequestHandler):
    """Answers generateContent. ``plan`` gives each attempt in turn: "ok", "hang" (sleeps past the
    client's timeout, then answers) or an HTTP error status; attempts beyond the plan get "ok"."""
    plan, calls, lock = [], [], threading.Lock()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with Stub.lock:
            Stub.calls.append((time.monotonic(), self.headers.get("X-Server-Timeout")))
            step = Stub.plan[len(Stub.calls) - 1] if len(Stub.calls) <= len(Stub.plan) else "ok"
        if step == "hang":
            time.sleep(2.0)
        status = step if isinstance(step, int) else 200
        body = json.dumps(ANSWER if status == 200 else
                          {"error": {"code": status, "message": "stub", "status": ERRORS[status]}}).encode()
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except OSError:
            pass  # the client already gave up on this attempt

    def log_message(self, *args):
        pass


class TestLiveAssistantLimits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.tmp = tempfile.TemporaryDirectory()
        head = build_pack(Path(cls.tmp.name))
        cls.ev = verify_run(LocalStore(Path(cls.tmp.name)), RUN, "Full assurance cycle", head)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.tmp.cleanup()

    def setUp(self):
        Stub.calls.clear()
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for k in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION", "GOOGLE_API_KEY", "GEMINI_API_KEY"):
            os.environ.pop(k, None)
        self.fast = mock.patch.multiple(assistant, RETRY_WAITS_S=(0.05, 0.1))  # real waits are 1 s, 2 s
        self.fast.start()

    def tearDown(self):
        self.fast.stop()
        self.env.stop()

    def chat(self):
        from google import genai
        client = genai.Client(vertexai=True, api_key="test-key", http_options=genai.types.HttpOptions(
            base_url=f"http://127.0.0.1:{self.server.server_port}/"))
        return GeminiChat(client=client)

    def ask_motor(self, chat, **limits):
        with mock.patch.multiple(assistant, **limits) if limits else mock.patch.multiple(assistant, MIN_ATTEMPT_S=2.0):
            return ask(chat, Toolbox(self.ev, 20, True), "Why is the motor flagged?", [])

    def logged(self, chat):
        with self.assertLogs("twinevidence.assistant", "INFO") as logs:
            assistant._log_model_call(chat, 1)
        return logs.output[0]

    def test_retry_policy_is_three_attempts_on_5xx_with_1s_then_2s_waits(self):
        self.fast.stop()
        try:
            opts = self.chat().request_options(25.0)
        finally:
            self.fast.start()
        r = opts.retry_options
        self.assertEqual((opts.timeout, r.attempts, r.initial_delay, r.max_delay, r.exp_base), (25000, 3, 1.0, 2.0, 2))
        self.assertEqual(r.http_status_codes, [500, 502, 503, 504])  # no 4xx

    def test_5xx_twice_then_success(self):
        Stub.plan = [503, 503, "ok"]
        chat = self.chat()
        _, _, text = chat.generate([chat.user("hi")], timeout_s=5)
        self.assertEqual((text, len(Stub.calls), chat.last_call["attempts"]), ("ok", 3, 3))
        self.assertEqual(chat.last_call["attempt_log"], ["ServerError/503", "ServerError/503", "ok/200"])
        self.assertIn("http attempts 3, sdk retried yes, timeouts 0, attempts [ServerError/503, ServerError/503, ok/200]",
                      self.logged(chat))

    def test_the_real_backoff_is_about_1s_then_2s(self):
        self.fast.stop()
        try:
            Stub.plan = [503, 503, "ok"]
            chat = self.chat()
            chat.generate([chat.user("hi")], timeout_s=5)
        finally:
            self.fast.start()
        (t1, _), (t2, _), (t3, _) = Stub.calls
        self.assertAlmostEqual(t2 - t1, 1.0, delta=0.4)
        self.assertAlmostEqual(t3 - t2, 2.0, delta=0.4)

    def test_5xx_three_times_gives_the_temporary_error_message(self):
        Stub.plan = [503, 503, 503, "ok"]
        with self.assertLogs("twinevidence.assistant", "INFO") as logs, \
                self.assertRaisesRegex(AssistantError, f"^{GEMINI_5XX}$"):
            self.ask_motor(self.chat())
        self.assertEqual(len(Stub.calls), 3)  # never a fourth attempt
        self.assertTrue(any("attempts [ServerError/503, ServerError/503, ServerError/503]" in l for l in logs.output))

    def test_a_4xx_is_not_retried(self):
        for status in (400, 403):
            Stub.calls.clear()
            Stub.plan = [status, "ok"]
            chat = self.chat()
            with self.assertRaises(Exception) as caught:
                chat.generate([chat.user("hi")], timeout_s=5)
            self.assertEqual(type(caught.exception).__name__, "ClientError")
            self.assertEqual(len(Stub.calls), 1)
            self.assertEqual(chat.last_call["attempt_log"], [f"ClientError/{status}"])
        # In a question, a 4xx is not dressed up as a temporary error: it passes on (the endpoint answers 503).
        Stub.calls.clear()
        Stub.plan = [400]
        with self.assertRaises(Exception) as caught:
            self.ask_motor(self.chat())
        self.assertNotIsInstance(caught.exception, AssistantError)

    def test_a_hung_attempt_times_out_and_is_retried(self):
        Stub.plan = ["hang", "ok"]
        chat = self.chat()
        _, _, text = chat.generate([chat.user("hi")], timeout_s=0.5)
        self.assertEqual((text, len(Stub.calls)), ("ok", 2))
        self.assertIn("Timeout", chat.last_call["attempt_log"][0])
        self.assertLess(chat.last_call["seconds"], 2.0)  # did not wait for the hung attempt
        self.assertEqual(Stub.calls[0][1], "1")  # the timeout is also sent to the server as its deadline
        self.assertRegex(self.logged(chat), r"http attempts 2, sdk retried yes, timeouts 1, attempts \[\w*Timeout/-, ok/200\]")

    def test_attempts_that_run_out_of_time_give_the_slow_message(self):
        for plan in (["hang"] * 3, [504] * 3):  # client timeout, or the server's 504 for the same deadline
            Stub.calls.clear()
            Stub.plan = plan + ["ok"]
            with self.assertRaisesRegex(AssistantError, f"^{GEMINI_SLOW}$"):
                self.ask_motor(self.chat(), CALL_TIMEOUT_S=0.5, MIN_ATTEMPT_S=0.1)
            self.assertEqual(len(Stub.calls), 3)

    def test_the_messages_are_distinct(self):
        self.assertEqual(len({GEMINI_5XX, GEMINI_SLOW, TOO_SLOW,
                              "the question needed too many evidence lookups; try a narrower question"}), 4)

    def test_no_new_call_starts_after_the_question_limit(self):
        now, timeouts = [0.0], []

        class Slow:
            model_id = "fake"
            user = model = staticmethod(lambda text: text)
            tool_results = staticmethod(lambda results: results)

            def generate(self, contents, tools=None, timeout_s=None):
                timeouts.append(round(timeout_s, 2))
                now[0] += 60
                return "c", [("get_current_tick", {})], None

        self.fast.stop()  # the budget uses the real waits (1 s + 2 s)
        try:
            with mock.patch.object(assistant, "_clock", lambda: now[0]), \
                    self.assertRaisesRegex(AssistantError, f"^{TOO_SLOW}$"):
                ask(Slow(), Toolbox(self.ev, 5, False), "q", [])
        finally:
            self.fast.start()
        # calls start at 0, 60, 120 and 180 s; at 180 s only 20 s are left: 3 attempts of (20 - 3) / 3 s.
        self.assertEqual(timeouts, [25.0, 25.0, 25.0, 5.67])

    def test_the_sealed_explanation_pipeline_is_unchanged(self):
        seen = {}

        class FakeClient:
            def __init__(self, **kwargs):
                seen["client_kwargs"] = kwargs
                self.models = self

            def generate_content(self, model, contents, config):
                seen["config"] = config
                return mock.Mock(text="{}")

        with mock.patch("google.genai.Client", FakeClient):
            gemini.VertexGemini(project="p")("instruction", "prompt", {"type": "object"})
        self.assertNotIn("http_options", seen["client_kwargs"])
        self.assertIsNone(seen["config"].http_options)  # no timeout, no retry: calls may run as long as they need


if __name__ == "__main__":
    unittest.main()
