"""The live assistant's per-call timeout, single retry and per-question limit, and that the
sealed-explanation pipeline is left without them. The timeout tests run the real google-genai SDK
against a local HTTP stub that hangs, so the SDK's own timeout and retry are exercised."""

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
from app.assistant import AssistantError, GeminiChat, ask
from app.assistant_tools import Toolbox
from app.evidence import LocalStore, verify_run
from tests.test_app import RUN, build_pack

ANSWER = {"candidates": [{"content": {"role": "model", "parts": [{"text": "ok"}]}, "finishReason": "STOP"}]}


class Stub(BaseHTTPRequestHandler):
    """Answers generateContent; the attempts listed in ``hang`` sleep past the client's timeout."""
    hang, calls, lock = set(), [], threading.Lock()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        with Stub.lock:
            Stub.calls.append(self.path)
            n = len(Stub.calls)
        if n in Stub.hang:
            time.sleep(2.0)
        body = json.dumps(ANSWER).encode()
        try:
            self.send_response(200)
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

    def tearDown(self):
        self.env.stop()

    def chat(self):
        from google import genai
        client = genai.Client(vertexai=True, api_key="test-key", http_options=genai.types.HttpOptions(
            base_url=f"http://127.0.0.1:{self.server.server_port}/"))
        return GeminiChat(client=client)

    def test_a_hung_first_attempt_times_out_and_is_retried_once(self):
        Stub.hang = {1}
        chat = self.chat()
        _, calls, text = chat.generate([chat.user("hi")], timeout_s=0.5)
        self.assertEqual((text, calls), ("ok", []))
        self.assertEqual(len(Stub.calls), 2)
        self.assertEqual(chat.last_call["attempts"], 2)
        self.assertEqual(len(chat.last_call["attempt_errors"]), 1)
        self.assertIn("Timeout", chat.last_call["attempt_errors"][0])
        self.assertLess(chat.last_call["seconds"], 2.0)  # did not wait for the hung attempt
        with self.assertLogs("twinevidence.assistant", "INFO") as logs:
            assistant._log_model_call(chat, 1)
        self.assertRegex(logs.output[0], r"http attempts 2, sdk retried yes, timeouts 1, failed attempts \w*Timeout")
        self.assertIn("attempt timeout 0.5 s", logs.output[0])

    def test_at_most_one_retry_then_a_readable_reply(self):
        Stub.hang = {1, 2, 3}
        chat = self.chat()
        with mock.patch.multiple(assistant, CALL_TIMEOUT_S=0.5, MIN_ATTEMPT_S=0.1), \
                self.assertLogs("twinevidence.assistant", "INFO") as logs, \
                self.assertRaisesRegex(AssistantError, "^Gemini did not answer in time; please try again$"):
            ask(chat, Toolbox(self.ev, 20, True), "Why is the motor flagged?", [])
        self.assertEqual(len(Stub.calls), 2)  # the first attempt and one retry, never a third
        self.assertTrue(any("timeouts 2" in l for l in logs.output))
        self.assertTrue(any("outcome error" in l and "Timeout" in l for l in logs.output))

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

        with mock.patch.object(assistant, "_clock", lambda: now[0]), \
                self.assertRaisesRegex(AssistantError, "took too long to answer from the evidence; try a narrower question"):
            ask(Slow(), Toolbox(self.ev, 5, False), "q", [])
        # calls start at 0, 60, 120 and 180 s; at 180 s only 20 s are left, so both attempts get 9.75 s.
        self.assertEqual(timeouts, [25.0, 25.0, 25.0, 9.75])

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
        self.assertNotIn("assistant", gemini.VertexGemini.__module__)


if __name__ == "__main__":
    unittest.main()
