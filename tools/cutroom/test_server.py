"""Offline HTTP and provider-boundary tests; never call an external API."""

from __future__ import annotations

import http.client
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from intelligence import CRITERIA, MODEL, LiveSuggestions, decision_state, validate_answer
from server import ROOT, App, make_server


class JevBoundaryTests(unittest.TestCase):
    def test_current_subtitle_is_separate_from_neighbors(self):
        cues = [{"text": "before"}, {"text": "current"}, {"text": "after"}]
        state = decision_state(cues, 1, "goal")
        self.assertEqual(state["current_subtitle"], "current")
        self.assertNotIn("expected", state)

    def test_rejects_missing_usage_and_nonfinite_choice(self):
        value = {
            "model": MODEL,
            "answers": {
                "decision": {
                    "type": "choice",
                    "choice": "keep",
                    "probabilities": {"keep": 0.9, "skip": 0.1},
                    "confidence": 0.8,
                }
            },
            "usage": {"input_tokens": 80},
        }
        self.assertEqual(validate_answer(value)["choice"], "keep")
        value["usage"] = {}
        with self.assertRaises(ValueError):
            validate_answer(value)
        value["usage"] = {"input_tokens": 80}
        value["answers"]["decision"]["confidence"] = float("nan")
        with self.assertRaises(ValueError):
            validate_answer(value)

    def test_error_charges_budget_and_no_retry(self):
        live = LiveSuggestions("test-value-not-a-real-credential", 2)
        cues = [
            {"id": "cue-0001", "text": "synthetic one"},
            {"id": "cue-0002", "text": "synthetic two"},
        ]
        with patch("intelligence.urllib.request.build_opener") as opener:
            opener.return_value.open.side_effect = TimeoutError()
            with self.assertRaises(ValueError):
                live.suggest(cues, "goal")
            self.assertEqual(opener.return_value.open.call_count, 1)
            self.assertEqual(live.remaining, 0)
            with self.assertRaises(ValueError):
                live.suggest(cues, "goal")
            self.assertEqual(opener.return_value.open.call_count, 1)

    def test_api_key_is_not_available_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            app = App(Path(directory))
            self.assertIsNone(app.live)
        self.assertEqual(set(CRITERIA), {"keep", "skip"})

    def test_custom_transcript_requires_explicit_true_consent(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("server.LiveSuggestions") as mocked:
                live = mocked.return_value
                live.suggest.return_value = {"selected_ids": ["cue-0001"], "mode": "live"}
                app = App(Path(directory), live)
                project = {"is_demo": False, "cues": [{"id": "cue-0001", "text": "synthetic"}]}
                for consent in [None, False, "true", 1]:
                    with self.assertRaises(ValueError):
                        app.suggest(project, {"goal": "custom", "mode": "jev", "consent": consent})
                live.suggest.assert_not_called()
                result = app.suggest(project, {"goal": "custom", "mode": "jev", "consent": True})
                self.assertEqual(result["mode"], "live")
                live.suggest.assert_called_once_with(project["cues"], "custom")


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.app = App(Path(cls.temporary.name))
        cls.server = make_server(cls.app, 0)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.temporary.cleanup()

    def request(self, method, path, data=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=60)
        headers = dict(headers or {})
        if isinstance(data, dict):
            data = json.dumps(data).encode()
            headers.setdefault("Content-Type", "application/json")
        connection.request(method, path, body=data, headers=headers)
        response = connection.getresponse()
        body = response.read()
        status, returned = response.status, dict(response.getheaders())
        connection.close()
        return status, returned, body

    def post(self, path, data):
        status, _, body = self.request("POST", path, data)
        self.assertLess(status, 300, body)
        return json.loads(body)

    def test_host_origin_and_paths_are_scoped(self):
        status, _, _ = self.request("GET", "/api/config", headers={"Host": "malicious.invalid"})
        self.assertEqual(status, 403)
        status, _, _ = self.request(
            "POST", "/api/demo", {}, {"Origin": "https://unrelated.invalid"}
        )
        self.assertEqual(status, 403)
        for path in ["/../server.py", "/server.py", "/media/../server.py"]:
            status, _, _ = self.request("GET", path)
            self.assertEqual(status, 404)

    def test_bad_requests_and_fake_video_do_not_create_projects(self):
        before = set(self.app.storage.iterdir())
        status, _, _ = self.request(
            "POST",
            "/api/upload",
            b"not-a-video",
            {"Content-Type": "application/octet-stream", "X-Filename": "private.mp4"},
        )
        self.assertEqual(status, 400)
        self.assertEqual(before, set(self.app.storage.iterdir()))
        status, _, _ = self.request(
            "POST", "/api/demo", b"[]", {"Content-Type": "application/json"}
        )
        self.assertEqual(status, 400)

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg not installed")
    def test_demo_recording_range_and_custom_input_export(self):
        project = self.post("/api/demo", {})
        self.assertTrue(project["has_audio"])
        self.assertEqual(len(project["cues"]), 6)
        recorded = self.post(
            f"/api/project/{project['id']}/suggest",
            {"mode": "jev", "goal": project["suggested_goal"]},
        )
        self.assertEqual(recorded["mode"], "recorded")
        self.assertEqual(recorded["measurement"]["new_requests"], 0)
        status, headers, data = self.request(
            "GET", project["video_url"], headers={"Range": "bytes=0-15"}
        )
        self.assertEqual(status, 206)
        self.assertEqual(len(data), 16)
        self.assertTrue(headers["Content-Range"].startswith("bytes 0-15/"))
        data = (ROOT / "demo" / "walkthrough.mp4").read_bytes()
        status, _, body = self.request(
            "POST",
            "/api/upload",
            data,
            {"Content-Type": "application/octet-stream", "X-Filename": "../../arbitrary.mp4"},
        )
        self.assertEqual(status, 201, body)
        custom = json.loads(body)
        self.assertFalse(custom["is_demo"])
        self.assertEqual(custom["name"], "arbitrary.mp4")
        subtitles = "WEBVTT\n\n00:00.200 --> 00:01.100\n独自の字幕 <script>text</script>\n"
        custom = self.post(f"/api/project/{custom['id']}/subtitles", {"text": subtitles})
        selected = self.post(
            f"/api/project/{custom['id']}/suggest", {"goal": "独自", "mode": "keywords"}
        )
        self.assertEqual(selected["selected_ids"], ["cue-0001"])
        status, _, _ = self.request(
            "POST",
            f"/api/project/{custom['id']}/suggest",
            {"goal": "a custom goal", "mode": "jev", "consent": True},
        )
        self.assertEqual(status, 400)
        export = self.post(
            f"/api/project/{custom['id']}/export", {"selected_ids": ["cue-0001"], "padding": 0.1}
        )
        self.assertTrue(export["has_audio"])
        self.assertAlmostEqual(export["requested_duration"], 1.1, delta=0.1)
        status, _, body = self.request("GET", export["urls"]["bundle"])
        self.assertEqual(status, 200)
        self.assertTrue(body.startswith(b"PK"))


if __name__ == "__main__":
    unittest.main()
