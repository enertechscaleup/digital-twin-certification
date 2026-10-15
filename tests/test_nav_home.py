"""The platform's two ways back to the public website: the top-bar logo and the "Home" nav item.
Both must use HOME_URL, be plain same-tab links, and the URL must live in one place only."""

import re
import unittest
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web" / "src" / "platform"
APP = (WEB / "App.jsx").read_text()
COMPONENTS = (WEB / "components.jsx").read_text()
SITE = (WEB / "site.js").read_text()


def topbar():
    m = re.search(r'<header className="topbar">(.*?)</header>', APP, re.S)
    assert m, "top bar not found in App.jsx"
    return m.group(1)


class TestNavHome(unittest.TestCase):
    def test_home_url_is_one_constant(self):
        self.assertIn("export const HOME_URL = 'https://twinevidence.com'", SITE)
        hits = [p for p in WEB.parent.rglob("*") if p.is_file() and "twinevidence.com" in p.read_text(errors="ignore")]
        self.assertEqual(hits, [WEB / "site.js"])

    def test_home_is_first_nav_item_and_a_plain_link(self):
        nav = re.search(r'<nav className="app-nav"[^>]*>(.*?)</nav>', topbar(), re.S).group(1)
        links = re.findall(r"<a [^>]*>[^<]*</a>", nav)
        self.assertEqual(links[0], "<a href={HOME_URL}>Home</a>")  # no target, no aria-current, no onClick
        self.assertEqual(len(links), 4)

    def test_topbar_logo_links_home(self):
        self.assertIn('<Wordmark href={HOME_URL} label="TwinEvidence home" />', topbar())

    def test_wordmark_renders_a_plain_same_tab_link(self):
        anchor = re.search(r"<a className=\"wordmark\"[^>]*>", COMPONENTS).group(0)
        self.assertEqual(anchor, '<a className="wordmark" href={href} aria-label={label}>')

    def test_footer_logo_stays_in_app(self):
        footer = re.search(r'<footer className="footer">(.*?)</footer>', APP, re.S).group(1)
        self.assertIn("<Wordmark />", footer)
        self.assertIn("href = '#projects'", COMPONENTS)


if __name__ == "__main__":
    unittest.main()
