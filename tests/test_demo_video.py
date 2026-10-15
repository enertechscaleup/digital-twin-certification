"""The demo video: the media route (fixed objects, range requests capped per response, 503 when
storage is unavailable) and the pages that link to it (header item, Projects call-to-action, the
player page). No bucket, project or console identifier may appear in the app's source."""

import io
import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from app import main, media

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web/src/platform"


class FakeBlob:
    def __init__(self, data: bytes):
        self.data, self.size, self.generation = data, None, 7

    def reload(self):
        self.size = len(self.data)

    def open(self, mode, chunk_size=None):
        return io.BytesIO(self.data)


class FakeBucket:
    def __init__(self, objects):
        self.objects = objects

    def blob(self, name):
        if name not in self.objects:
            raise KeyError(name)
        return FakeBlob(self.objects[name])


VIDEO = bytes(range(256)) * 400  # 102,400 bytes
POSTER = b"\xff\xd8poster\xff\xd9"


class TestMediaRoute(unittest.TestCase):
    def setUp(self):
        media._meta.clear()
        bucket = FakeBucket({"demo/twinevidence-demo.mp4": VIDEO, "demo/twinevidence-demo-poster.jpg": POSTER})
        self.patches = [mock.patch.object(media, "_bucket", lambda: bucket), mock.patch.object(media, "CHUNK", 10_000)]
        for p in self.patches:
            p.start()
        self.client = TestClient(main.app)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        media._meta.clear()

    def test_range_is_answered_with_206_and_capped(self):
        r = self.client.get("/media/demo.mp4", headers={"Range": "bytes=0-"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers["content-range"], f"bytes 0-9999/{len(VIDEO)}")
        self.assertEqual(r.headers["content-length"], "10000")
        self.assertEqual(r.headers["accept-ranges"], "bytes")
        self.assertEqual(r.headers["content-type"], "video/mp4")
        self.assertIn("max-age", r.headers["cache-control"])
        self.assertEqual(r.content, VIDEO[:10000])

    def test_seek_to_the_middle(self):
        mid = len(VIDEO) // 2
        r = self.client.get("/media/demo.mp4", headers={"Range": f"bytes={mid}-{mid + 99}"})
        self.assertEqual(r.status_code, 206)
        self.assertEqual(r.headers["content-range"], f"bytes {mid}-{mid + 99}/{len(VIDEO)}")
        self.assertEqual(r.content, VIDEO[mid:mid + 100])

    def test_suffix_range_and_end_of_file(self):
        r = self.client.get("/media/demo.mp4", headers={"Range": "bytes=-500"})
        self.assertEqual((r.status_code, r.content), (206, VIDEO[-500:]))
        r = self.client.get("/media/demo.mp4", headers={"Range": f"bytes={len(VIDEO) - 10}-{len(VIDEO) + 50}"})
        self.assertEqual((r.status_code, r.content), (206, VIDEO[-10:]))

    def test_unsatisfiable_range(self):
        r = self.client.get("/media/demo.mp4", headers={"Range": f"bytes={len(VIDEO)}-"})
        self.assertEqual(r.status_code, 416)
        self.assertEqual(r.headers["content-range"], f"bytes */{len(VIDEO)}")

    def test_whole_file_without_range(self):
        r = self.client.get("/media/demo.mp4")
        self.assertEqual((r.status_code, r.content), (200, VIDEO))  # streamed (larger than one chunk)
        r = self.client.get("/media/demo-poster.jpg")
        self.assertEqual((r.status_code, r.headers["content-type"], r.content), (200, "image/jpeg", POSTER))
        self.assertEqual(r.headers["content-length"], str(len(POSTER)))

    def test_head(self):
        r = self.client.head("/media/demo.mp4", headers={"Range": "bytes=0-99"})
        self.assertEqual((r.status_code, r.headers["content-length"], r.content), (206, "100", b""))

    def test_only_the_two_objects(self):
        routes = sorted(r.path for r in media.router.routes)
        self.assertEqual(routes, ["/media/demo-poster.jpg", "/media/demo.mp4"])
        self.assertNotEqual(self.client.get("/media/other.mp4").status_code, 200)
        self.assertNotEqual(self.client.get("/media/../demo/twinevidence-demo.mp4").status_code, 206)

    def test_503_when_storage_is_unavailable(self):
        with mock.patch.object(media, "_bucket", lambda: None):
            media._meta.clear()
            r = self.client.get("/media/demo.mp4", headers={"Range": "bytes=0-"})
            self.assertEqual(r.status_code, 503)
        broken = FakeBucket({})
        with mock.patch.object(media, "_bucket", lambda: broken):
            media._meta.clear()
            self.assertEqual(self.client.get("/media/demo-poster.jpg").status_code, 503)


class TestPages(unittest.TestCase):
    APP = (WEB / "App.jsx").read_text()
    PLAYER = (WEB / "DemoVideo.jsx").read_text()
    PROJECTS = (WEB / "ProjectsView.jsx").read_text()
    SITE = (WEB / "site.js").read_text()

    def test_header_item_on_every_page(self):
        nav = self.APP[self.APP.index('<nav className="app-nav"'):self.APP.index("</nav>")]
        self.assertIn(">Demo video</a>", nav)
        self.assertIn("href={DEMO_ROUTE}", nav)
        self.assertIn("export const DEMO_ROUTE = '#demo'", self.SITE)
        self.assertIn("route === 'demo' ? <DemoVideo />", self.APP)

    def test_player(self):
        video = self.PLAYER[self.PLAYER.index("<video"):self.PLAYER.index("</video>")]
        for attr in ("controls", "playsInline", 'preload="metadata"', "poster={DEMO_VIDEO.poster}", "src={DEMO_VIDEO.src}"):
            self.assertIn(attr, video)
        self.assertNotIn("autoPlay", video)
        self.assertIn("About 4 minutes. All data in this demonstration is synthetic.", self.PLAYER)
        self.assertIn("export const DEMO_VIDEO = { src: '/media/demo.mp4', poster: '/media/demo-poster.jpg' }", self.SITE)

    def test_call_to_action_on_projects(self):
        self.assertIn("New here? Watch the 4-minute demo video", self.PROJECTS)
        self.assertIn('<a className="demo-cta" href={DEMO_ROUTE}>', self.PROJECTS)

    def test_no_identifiers_or_forbidden_wording(self):
        sources = [self.APP, self.PLAYER, self.PROJECTS, self.SITE, (ROOT / "app/media.py").read_text()]
        for text in sources:
            self.assertIsNone(re.search(r"twinevidence-demo-video|46053a8a|project-[0-9a-f]{6}|console\.cloud|storage\.googleapis", text))
        new = self.PLAYER + self.PROJECTS[self.PROJECTS.index("demo-cta"):self.PROJECTS.index("proj-h")]
        for word in ("live", "real-time", "connected"):
            self.assertNotIn(word, new.lower())


if __name__ == "__main__":
    unittest.main()
