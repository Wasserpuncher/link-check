"""Hermetic tests for link-check — a throwaway HTTP server on localhost,
no network access required. Standard library only (unittest)."""
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from link_check import extract_urls, check_url, check_text


class _Handler(BaseHTTPRequestHandler):
    def _respond(self):
        if self.path == "/gone":
            self.send_response(404)
        elif self.path == "/boom":
            self.send_response(500)
        elif self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", f"http://{self.headers['Host']}/ok")
        elif self.path == "/nohead" and self.command == "HEAD":
            self.send_response(405)  # refuse HEAD, force GET fallback
        else:
            self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = _respond
    do_HEAD = _respond

    def log_message(self, *a):  # keep test output quiet
        pass


class LinkCheckTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    # --- URL extraction ---
    def test_extract_markdown_html_and_bare(self):
        text = (
            "A [link](http://a.example/one) and "
            "<a href='https://b.example/two'>x</a> and "
            "an image <img src=\"http://c.example/three.png\"> and "
            "a bare https://d.example/four, end."
        )
        urls = extract_urls(text)
        self.assertIn("http://a.example/one", urls)
        self.assertIn("https://b.example/two", urls)
        self.assertIn("http://c.example/three.png", urls)
        self.assertIn("https://d.example/four", urls)  # trailing comma trimmed

    def test_extract_dedupes(self):
        text = "same [x](http://a.example/x) and bare http://a.example/x here"
        self.assertEqual(extract_urls(text).count("http://a.example/x"), 1)

    def test_extract_ignores_non_http(self):
        text = "mail me at mailto:kai@example.com or see #anchor or /relative/path"
        self.assertEqual(extract_urls(text), [])

    def test_skips_fenced_code_by_default(self):
        text = (
            "Real [link](http://real.example/x).\n\n"
            "```\nexample output: http://inside.example/code\n```\n"
        )
        urls = extract_urls(text)
        self.assertIn("http://real.example/x", urls)
        self.assertNotIn("http://inside.example/code", urls)

    def test_include_code_checks_fenced_urls(self):
        text = "```\nsee http://inside.example/code\n```"
        self.assertIn("http://inside.example/code", extract_urls(text, skip_code=False))

    def test_decodes_html_entities(self):
        # &amp; in an href is really & — the URL a browser would request
        text = '<a href="http://api.example/v1?lat=1&amp;lon=2&amp;days=8">x</a>'
        self.assertIn("http://api.example/v1?lat=1&lon=2&days=8", extract_urls(text))

    def test_keeps_balanced_parens_but_trims_delimiter(self):
        # a URL that legitimately contains () must survive
        self.assertIn(
            "https://de.wikipedia.org/wiki/Front_(Meteorologie)",
            extract_urls("see https://de.wikipedia.org/wiki/Front_(Meteorologie) now"),
        )
        # a trailing ) that is only a delimiter must be trimmed
        self.assertIn(
            "https://example.com/x",
            extract_urls("(https://example.com/x)"),
        )

    # --- live checking against the local server ---
    def test_ok(self):
        self.assertTrue(check_url(self.base + "/ok").ok)

    def test_404_is_broken(self):
        r = check_url(self.base + "/gone")
        self.assertFalse(r.ok)
        self.assertEqual(r.status, "404")

    def test_500_is_broken(self):
        self.assertFalse(check_url(self.base + "/boom").ok)

    def test_redirect_is_ok(self):
        self.assertTrue(check_url(self.base + "/redirect").ok)

    def test_head_refused_falls_back_to_get(self):
        # server answers HEAD with 405 but GET with 200 → must count as OK
        self.assertTrue(check_url(self.base + "/nohead").ok)

    def test_allow_list_accepts_code(self):
        r = check_url(self.base + "/gone", allow=frozenset({404}))
        self.assertTrue(r.ok)

    def test_unreachable_is_broken(self):
        # nothing is listening on this port
        self.assertFalse(check_url("http://127.0.0.1:1/never").ok)

    def test_check_text_reports_the_broken_one(self):
        text = f"[good]({self.base}/ok) and [bad]({self.base}/gone)"
        results = check_text(text, workers=4)
        by_url = {r.url: r.ok for r in results}
        self.assertTrue(by_url[self.base + "/ok"])
        self.assertFalse(by_url[self.base + "/gone"])


if __name__ == "__main__":
    unittest.main()
