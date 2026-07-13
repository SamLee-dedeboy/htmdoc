#!/usr/bin/env python3
"""Tests for htmdoc.py — the save server. Stdlib only (unittest), no deps.

    python3 -m unittest -v test_htmdoc

Two groups: pure-function unit tests (path safety, injection, history) and
end-to-end HTTP tests (a real server on an ephemeral port) covering the
save/restore round-trip and the Origin/Host security guards.
"""
import json
import os
import shutil
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import htmdoc


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class UnitTests(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self._root, self._token = htmdoc.ROOT, htmdoc.TOKEN
        htmdoc.ROOT = self.tmp
        htmdoc.TOKEN = ""

    def tearDown(self):
        htmdoc.ROOT, htmdoc.TOKEN = self._root, self._token
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_is_html(self):
        self.assertTrue(htmdoc.is_html("a.html"))
        self.assertTrue(htmdoc.is_html("A.HTM"))
        self.assertFalse(htmdoc.is_html("a.txt"))
        self.assertFalse(htmdoc.is_html("a.html.bak"))

    def test_normalize_client_path(self):
        # Windows file:// pathnames arrive as /C:/... — the leading slash goes.
        self.assertEqual(htmdoc.normalize_client_path("/C:/Users/x/f.html"),
                         "C:/Users/x/f.html")
        self.assertEqual(htmdoc.normalize_client_path("/c:\\Users\\f.html"),
                         "c:\\Users\\f.html")
        # POSIX absolute and server-relative paths are left untouched.
        self.assertEqual(htmdoc.normalize_client_path("/home/x/f.html"),
                         "/home/x/f.html")
        self.assertEqual(htmdoc.normalize_client_path("/files/f.html"),
                         "/files/f.html")
        self.assertEqual(htmdoc.normalize_client_path(""), "")

    def test_safe_join_blocks_traversal(self):
        self.assertIsNotNone(htmdoc.safe_join("page.html"))
        self.assertIsNotNone(htmdoc.safe_join("sub/page.html"))
        self.assertIsNone(htmdoc.safe_join("../escape.html"))
        self.assertIsNone(htmdoc.safe_join("../../etc/passwd"))

    def test_resolve_rejects_non_html(self):
        write(os.path.join(self.tmp, "notes.txt"), "x")
        self.assertIsNone(htmdoc.resolve_save_target("notes.txt"))

    def test_resolve_never_escapes_root(self):
        # Traversal / absolute inputs are confined: the resolver either returns
        # None or a path *under* root (which then 404s if it doesn't exist), but
        # never a path outside root.
        for raw in ("../outside.html", "/etc/secret.html", "../../etc/passwd.html"):
            target = htmdoc.resolve_save_target(raw)
            if target is not None:
                self.assertTrue(
                    target == self.tmp or target.startswith(self.tmp + os.sep),
                    "%r escaped root: %r" % (raw, target))

    def test_resolve_accepts_html_forms(self):
        page = os.path.join(self.tmp, "page.html")
        write(page, "<html></html>")
        self.assertEqual(htmdoc.resolve_save_target("page.html"), page)
        self.assertEqual(htmdoc.resolve_save_target("/files/page.html"), page)
        self.assertEqual(htmdoc.resolve_save_target(page), page)
        # Bare filename is the last-resort fallback.
        self.assertEqual(htmdoc.resolve_save_target("/weird/prefix/page.html"), page)

    def test_inject_editor_idempotent_and_specific(self):
        # A plain page gets the tag inserted before </body>.
        out = htmdoc.inject_editor(b"<html><body><p>hi</p></body></html>")
        self.assertIn(b"data-htmdoc", out)
        self.assertLess(out.index(b"<script"), out.index(b"</body>"))
        # An already-tagged page is left alone (no second tag).
        already = b'<body><script src="/htmdoc.js" data-htmdoc></script></body>'
        self.assertEqual(htmdoc.inject_editor(already), already)
        # A page that merely MENTIONS htmdoc still gets injected (the old bare
        # "htmdoc" mark used to wrongly suppress this).
        prose = b"<html><body><p>I edited this with htmdoc.</p></body></html>"
        self.assertIn(b"data-htmdoc", htmdoc.inject_editor(prose))

    def test_inject_tag_carries_token(self):
        htmdoc.TOKEN = ""
        self.assertNotIn(b"data-token", htmdoc.inject_tag_bytes())
        htmdoc.TOKEN = "s3cret"
        self.assertIn(b'data-token="s3cret"', htmdoc.inject_tag_bytes())

    def test_bookmarklet_carries_token(self):
        htmdoc.PORT = 8321
        htmdoc.TOKEN = ""
        self.assertNotIn("data-token", htmdoc.bookmarklet(8321))
        htmdoc.TOKEN = "abc"
        self.assertIn("data-token", htmdoc.bookmarklet(8321))

    def test_history_rotation(self):
        page = os.path.join(self.tmp, "page.html")
        write(page, "v0")
        # Force unique timestamps so each snapshot is a distinct file.
        counter = {"n": 0}
        orig = htmdoc.time.strftime

        def fake_strftime(fmt, *a):
            counter["n"] += 1
            return "stamp-%03d" % counter["n"]

        htmdoc.time.strftime = fake_strftime
        try:
            for i in range(htmdoc.HISTORY_KEEP + 5):
                write(page, "v%d" % i)
                htmdoc.save_history(page)
        finally:
            htmdoc.time.strftime = orig

        hdir = os.path.join(self.tmp, htmdoc.HISTORY_DIR)
        kept = [n for n in os.listdir(hdir) if n.startswith("page.html.")]
        self.assertEqual(len(kept), htmdoc.HISTORY_KEEP)
        versions = htmdoc.list_history(page)
        self.assertEqual(len(versions), htmdoc.HISTORY_KEEP)
        self.assertEqual(set(versions[0].keys()), {"version", "mtime", "size"})


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        htmdoc.Handler.log_message = lambda *a, **k: None  # silence in tests

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self._root, self._port, self._token = htmdoc.ROOT, htmdoc.PORT, htmdoc.TOKEN
        htmdoc.ROOT = self.tmp
        htmdoc.TOKEN = ""
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), htmdoc.Handler)
        self.port = self.server.server_address[1]
        htmdoc.PORT = self.port
        self.origin = "http://127.0.0.1:%d" % self.port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        htmdoc.ROOT, htmdoc.PORT, htmdoc.TOKEN = self._root, self._port, self._token
        shutil.rmtree(self.tmp, ignore_errors=True)

    def req(self, method, path, body=None, headers=None):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        h = dict(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, (bytes, str)) else json.dumps(body)
            h.setdefault("Content-Type", "text/plain")
        conn.request(method, path, data, h)
        resp = conn.getresponse()
        raw = resp.read()
        out = {"status": resp.status, "headers": {k.lower(): v for k, v in resp.getheaders()}}
        try:
            out["json"] = json.loads(raw.decode("utf-8"))
        except ValueError:
            out["body"] = raw
        conn.close()
        return out

    def save_body(self, path, html, token=""):
        return {"path": path, "html": html, "token": token}

    # --- basics -------------------------------------------------------------

    def test_health(self):
        r = self.req("GET", "/health")
        self.assertEqual(r["status"], 200)
        self.assertTrue(r["json"]["ok"])

    def test_serve_injects_editor(self):
        write(os.path.join(self.tmp, "p.html"), "<html><body>hi</body></html>")
        r = self.req("GET", "/files/p.html")
        self.assertIn(b"data-htmdoc", r["body"])
        raw = self.req("GET", "/files/p.html?raw=1")
        self.assertNotIn(b"data-htmdoc", raw["body"])

    # --- save round-trip ----------------------------------------------------

    def test_save_writes_and_backs_up_once(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "<html>original</html>")
        r = self.req("POST", "/save", self.save_body(page, "<html>edited</html>"),
                     {"Origin": self.origin})
        self.assertEqual(r["status"], 200)
        self.assertTrue(r["json"]["ok"])
        self.assertEqual(read(page), "<html>edited</html>")
        self.assertEqual(read(page + ".bak"), "<html>original</html>")

        # A second save edits the file but must NOT rewrite the one-time .bak.
        self.req("POST", "/save", self.save_body(page, "<html>edited2</html>"),
                 {"Origin": self.origin})
        self.assertEqual(read(page), "<html>edited2</html>")
        self.assertEqual(read(page + ".bak"), "<html>original</html>")

    def test_save_noop_is_skipped(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "<html>same</html>")
        first = self.req("POST", "/save", self.save_body(page, "<html>changed</html>"),
                         {"Origin": self.origin})
        self.assertNotIn("unchanged", first["json"])
        # Re-saving identical bytes returns unchanged and adds no history entry.
        again = self.req("POST", "/save", self.save_body(page, "<html>changed</html>"),
                         {"Origin": self.origin})
        self.assertTrue(again["json"].get("unchanged"))
        self.assertEqual(len(htmdoc.list_history(page)), 1)

    # --- security guards ----------------------------------------------------

    def test_save_rejects_foreign_origin(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "safe")
        r = self.req("POST", "/save", self.save_body(page, "HACKED"),
                     {"Origin": "http://evil.example"})
        self.assertEqual(r["status"], 403)
        self.assertEqual(read(page), "safe")  # untouched

    def test_save_allows_null_origin(self):
        # file:// pages send Origin: null — the core "double-click a file" flow.
        page = os.path.join(self.tmp, "p.html")
        write(page, "x")
        r = self.req("POST", "/save", self.save_body(page, "y"), {"Origin": "null"})
        self.assertEqual(r["status"], 200)
        self.assertEqual(read(page), "y")

    def test_bad_host_rejected(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "safe")
        r = self.req("POST", "/save", self.save_body(page, "HACKED"),
                     {"Host": "attacker.example", "Origin": self.origin})
        self.assertEqual(r["status"], 403)
        self.assertEqual(read(page), "safe")
        # GET is guarded too.
        self.assertEqual(self.req("GET", "/health", headers={"Host": "evil.example"})["status"], 403)

    def test_save_rejects_traversal(self):
        # A path pointing outside root must never touch that file. The resolver
        # confines it to a (nonexistent) path under root, so the write is
        # refused — 403 (unresolvable) or 404 (resolves under root but missing).
        outside = os.path.join(os.path.dirname(self.tmp), "outside.html")
        write(outside, "keep")
        try:
            r = self.req("POST", "/save", self.save_body(outside, "HACKED"),
                         {"Origin": self.origin})
            self.assertIn(r["status"], (403, 404))
            self.assertEqual(read(outside), "keep")  # the outside file is untouched
        finally:
            os.remove(outside)

    def test_cors_reflects_only_allowed_origin(self):
        write(os.path.join(self.tmp, "p.html"), "<html></html>")
        allowed = self.req("GET", "/health", headers={"Origin": self.origin})
        self.assertEqual(allowed["headers"].get("access-control-allow-origin"), self.origin)
        foreign = self.req("GET", "/health", headers={"Origin": "http://evil.example"})
        self.assertIsNone(foreign["headers"].get("access-control-allow-origin"))

    def test_token_required_when_set(self):
        htmdoc.TOKEN = "letmein"
        page = os.path.join(self.tmp, "p.html")
        write(page, "orig")
        # Right origin but no token -> refused.
        bad = self.req("POST", "/save", self.save_body(page, "x"), {"Origin": self.origin})
        self.assertEqual(bad["status"], 403)
        self.assertEqual(read(page), "orig")
        # Correct token -> allowed even from a foreign origin.
        good = self.req("POST", "/save", self.save_body(page, "x", token="letmein"),
                        {"Origin": "http://evil.example"})
        self.assertEqual(good["status"], 200)
        self.assertEqual(read(page), "x")

    # --- restore ------------------------------------------------------------

    def test_restore_rejects_bad_version(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "orig")
        # A version escaping the history dir / not belonging to this file.
        r = self.req("POST", "/restore",
                     {"path": page, "version": "../../secret", "token": ""},
                     {"Origin": self.origin})
        self.assertEqual(r["status"], 403)

    def test_restore_round_trip(self):
        page = os.path.join(self.tmp, "p.html")
        write(page, "v1")
        self.req("POST", "/save", self.save_body(page, "v2"), {"Origin": self.origin})
        versions = htmdoc.list_history(page)
        self.assertTrue(versions)  # the pre-save "v1" snapshot
        r = self.req("POST", "/restore",
                     {"path": page, "version": versions[0]["version"], "token": ""},
                     {"Origin": self.origin})
        self.assertEqual(r["status"], 200)
        self.assertEqual(read(page), "v1")


if __name__ == "__main__":
    unittest.main()
