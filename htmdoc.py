#!/usr/bin/env python3
"""htmdoc — edit any HTML file on your computer, in place.

    python3 htmdoc.py [--port 8321] [--root DIR] [--inject]

Root defaults to your home directory, so every HTML file you own is covered.

The main flow — no copying files, no per-project setup:
  1. Once: open http://127.0.0.1:8321/ and drag the "Make editable"
     bookmarklet to your bookmarks bar.
  2. Double-click any HTML file, exactly like you always do (file://).
  3. Click the bookmark. The page becomes editable and every edit
     auto-saves back to the file (one-time .bak before first overwrite).

Alternative: browse http://127.0.0.1:8321/ and click a file — it's served
with the editor already injected into the response (the file on disk is
never modified by the tooling). Or add the tag to a page yourself:
    <script src="http://127.0.0.1:8321/htmdoc.js" data-htmdoc></script>

Endpoints:
    GET  /                  -> file browser (also /browse/<subdir>)
    GET  /files/<path>      -> serve a file under root; HTML gets the editor
                               injected in-flight (never written to disk)
    GET  /htmdoc.js         -> the editor script (from this file's directory;
                               /make-editable.js is kept as a legacy alias)
    GET  /health            -> 200, lets the editor detect the server
    POST /save              -> body {"path": ..., "html": ...}; writes the file

Safety: binds 127.0.0.1 only; reads and writes are confined to --root;
writes further restricted to existing .html/.htm files; atomic writes;
one-time <file>.bak backups.

--inject (optional, legacy): additionally write the editor tag permanently
into the HTML files directly in root, for pages you want self-editable when
opened via file:// without the bookmarklet.
"""
import argparse
import html as html_mod
import json
import mimetypes
import os
import shutil
import tempfile
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote

ROOT = os.getcwd()
PORT = 8321
HERE = os.path.dirname(os.path.abspath(__file__))
EDITOR_JS = os.path.join(HERE, "htmdoc.js")

SKIP_DIRS = {"node_modules", "__pycache__", ".git", ".svn", "venv", ".venv"}

# Rolling version history: before each overwrite, the current file is copied
# into a hidden sibling folder; the newest HISTORY_KEEP versions are kept.
HISTORY_DIR = ".htmdoc-history"
HISTORY_KEEP = 10


def save_history(target):
    """Snapshot the current contents of target into its history folder."""
    try:
        hdir = os.path.join(os.path.dirname(target), HISTORY_DIR)
        os.makedirs(hdir, exist_ok=True)
        base = os.path.basename(target)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dest = os.path.join(hdir, "%s.%s" % (base, stamp))
        if not os.path.exists(dest):
            shutil.copy2(target, dest)
        versions = sorted(n for n in os.listdir(hdir) if n.startswith(base + "."))
        for old in versions[:-HISTORY_KEEP]:
            os.unlink(os.path.join(hdir, old))
    except OSError:
        pass


def list_history(target):
    hdir = os.path.join(os.path.dirname(target), HISTORY_DIR)
    base = os.path.basename(target)
    out = []
    if os.path.isdir(hdir):
        for name in sorted(os.listdir(hdir), reverse=True):
            if not name.startswith(base + "."):
                continue
            try:
                st = os.stat(os.path.join(hdir, name))
            except OSError:
                continue
            out.append({"version": name, "mtime": int(st.st_mtime), "size": st.st_size})
    return out

# Injected into served HTML only — never written to disk. data-me-injected
# tells the editor to strip this tag when serializing for a save.
INJECT_TAG = b'<script src="/htmdoc.js" data-htmdoc data-me-injected></script>'

# Files carrying any of these already reference the editor ("make-editable"
# is the tool's former name — old tags keep working).
EDITOR_MARKS = (b"htmdoc", b"make-editable")


def real_root():
    return os.path.realpath(ROOT)


def safe_join(rel_path):
    """Resolve a root-relative path, refusing anything that escapes root."""
    root = real_root()
    target = os.path.realpath(os.path.join(root, rel_path.lstrip("/")))
    if target == root or target.startswith(root + os.sep):
        return target
    return None


def is_html(path):
    return path.lower().endswith((".html", ".htm"))


def inject_editor(data):
    """Insert the editor tag into served HTML bytes (idempotent)."""
    if any(mark in data for mark in EDITOR_MARKS):
        return data
    idx = data.lower().rfind(b"</body>")
    if idx == -1:
        return data + b"\n" + INJECT_TAG + b"\n"
    return data[:idx] + INJECT_TAG + b"\n" + data[idx:]


def resolve_save_target(raw_path):
    """Map a client-supplied path to a real, writable file under ROOT, or None.

    Accepts: "/files/<rel>" (pages served by this server), an absolute disk
    path (file:// pages using the bookmarklet or a manual tag), a
    root-relative path, or a bare filename as a last resort.
    """
    if not raw_path:
        return None
    root = real_root()
    candidates = []
    if raw_path.startswith("/files/"):
        candidates.append(os.path.realpath(os.path.join(root, raw_path[len("/files/"):])))
    if os.path.isabs(raw_path):
        candidates.append(os.path.realpath(raw_path))
    candidates.append(os.path.realpath(os.path.join(root, raw_path.lstrip("/"))))
    candidates.append(os.path.realpath(os.path.join(root, os.path.basename(raw_path))))
    allowed = [t for t in candidates
               if (t == root or t.startswith(root + os.sep)) and is_html(t)]
    for target in allowed:
        if os.path.isfile(target):
            return target
    return allowed[0] if allowed else None


def bookmarklet(port):
    # data-me-injected keeps the appended tag out of saved files.
    return ("javascript:(function()%7Bvar s=document.createElement('script');"
            "s.src='http://127.0.0.1:{p}/htmdoc.js';"
            "s.setAttribute('data-htmdoc','');"
            "s.setAttribute('data-me-injected','');"
            "document.body.appendChild(s);%7D)();").format(p=port)


def render_listing(rel_dir):
    """HTML for the file-browser page of one directory under root."""
    abs_dir = safe_join(rel_dir)
    if abs_dir is None or not os.path.isdir(abs_dir):
        return None
    dirs, files = [], []
    try:
        for name in sorted(os.listdir(abs_dir), key=str.lower):
            if name.startswith(".") or name in SKIP_DIRS:
                continue
            full = os.path.join(abs_dir, name)
            if os.path.isdir(full):
                dirs.append(name)
            elif is_html(name):
                files.append(name)
    except OSError:
        return None

    rel_dir = rel_dir.strip("/")
    rows = []
    if rel_dir:
        parent = rel_dir.rsplit("/", 1)[0] if "/" in rel_dir else ""
        rows.append('<li class="dir"><a href="/browse/%s">&#8617; ..</a></li>'
                    % quote(parent))
    for name in dirs:
        rel = (rel_dir + "/" + name) if rel_dir else name
        rows.append('<li class="dir"><a href="/browse/%s">&#128193; %s/</a></li>'
                    % (quote(rel), html_mod.escape(name)))
    for name in files:
        rel = (rel_dir + "/" + name) if rel_dir else name
        rows.append('<li><a href="/files/%s">&#128196; %s</a></li>'
                    % (quote(rel), html_mod.escape(name)))
    if not rows:
        rows.append("<li><em>no HTML files or folders here</em></li>")

    crumb = html_mod.escape("/" + rel_dir if rel_dir else "/")
    return """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>htmdoc — edit any HTML file</title>
<style>
 body{{font:15px/1.6 -apple-system,system-ui,sans-serif;max-width:680px;margin:40px auto;padding:0 20px;color:#222}}
 h1{{font-size:22px}} h2{{font-size:16px;margin:36px 0 8px}} code{{background:#f2f2f2;padding:2px 6px;border-radius:4px}}
 ul{{list-style:none;padding:0}} li{{padding:5px 0;border-bottom:1px solid #eee}}
 a{{text-decoration:none;color:#0a58c2}} a:hover{{text-decoration:underline}}
 .hero{{background:#f6f9ff;border:1px solid #dbe7fb;border-radius:12px;padding:16px 20px;margin:18px 0}}
 .hero ol{{margin:8px 0 4px;padding-left:22px}} .hero li{{border:none;padding:3px 0}}
 .hero .once{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#667}}
 .bm{{display:inline-block;background:#0a58c2;color:#fff;padding:5px 14px;border-radius:6px;cursor:grab}}
 .copybtn{{font:inherit;font-size:13px;padding:2px 9px;border:1px solid #ccc;border-radius:6px;background:#fff;cursor:pointer}}
 .copybtn:hover{{background:#f0f0f0}}
 .alt{{color:#666;font-size:14px}}
</style></head><body>
<h1>htmdoc &mdash; edit any HTML file like a document</h1>
<p>Double-click your HTML files exactly like you always do &mdash; then one click makes
the page editable, and every edit saves itself back to the file.</p>
<div class="hero">
<div class="once">One-time setup</div>
<ol>
<li>Show your bookmarks bar: <b>&#8984;&#8679;B</b> (Mac) or <b>Ctrl+Shift+B</b> (Windows/Linux).</li>
<li>Drag this button onto it (press, pull up to the bar, release):
    <a class="bm" href="{bm}">Make editable</a>
    &nbsp;<button class="copybtn" onclick="navigator.clipboard.writeText(document.querySelector('.bm').href).then(()=>{{this.textContent='Copied!'}})">or copy the code</button>
    <span class="alt">(paste into a new bookmark's URL field)</span></li>
</ol>
<div class="once" style="margin-top:10px">Every day after</div>
<ol>
<li>Double-click any HTML file &mdash; it opens as <code>file://&hellip;</code> as usual.</li>
<li>Click the <b>Make editable</b> bookmark. Edit; changes save automatically
    (toolbar shows <code>Saved &#10003;</code>).</li>
</ol>
</div>
<h2>Or browse and click &mdash; no bookmarklet needed <span class="alt">&mdash; <code>{crumb}</code></span></h2>
<p class="alt">Files opened from this list get the editor automatically.</p>
<ul>{rows}</ul>
</body></html>""".format(crumb=crumb, rows="\n".join(rows), bm=bookmarklet(PORT))


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self._send_raw(code, "application/json", body)

    def _send_raw(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parts = self.path.split("?", 1)
        path = unquote(parts[0])
        raw = len(parts) > 1 and "raw=1" in parts[1]
        if path == "/health":
            self._send_json(200, {"ok": True, "root": ROOT})
        elif path in ("/htmdoc.js", "/make-editable.js"):  # old name kept as alias
            try:
                with open(EDITOR_JS, "rb") as f:
                    body = f.read()
            except OSError:
                self._send_json(500, {"ok": False, "error": "htmdoc.js not found next to htmdoc.py"})
                return
            self._send_raw(200, "application/javascript; charset=utf-8", body)
        elif path == "/history":
            q = parse_qs(parts[1]) if len(parts) > 1 else {}
            target = resolve_save_target(q.get("path", [""])[0])
            if target is None or not os.path.isfile(target):
                self._send_json(404, {"ok": False, "error": "file not found"})
            else:
                self._send_json(200, {"ok": True, "versions": list_history(target)})
        elif path == "/" or path == "/browse" or path.startswith("/browse/"):
            rel = path[len("/browse"):] if path.startswith("/browse") else ""
            page = render_listing(rel)
            if page is None:
                self._send_json(404, {"ok": False, "error": "not found"})
            else:
                self._send_raw(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path.startswith("/files/"):
            self.serve_file(path[len("/files/"):], raw)
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def serve_file(self, rel, raw=False):
        target = safe_join(rel)
        if target is None:
            self._send_json(403, {"ok": False, "error": "path not allowed"})
            return
        if os.path.isdir(target):
            self._send_raw(302, "text/plain", b"", {"Location": "/browse/" + quote(rel.strip("/"))})
            return
        if not os.path.isfile(target):
            self._send_json(404, {"ok": False, "error": "file not found"})
            return
        try:
            with open(target, "rb") as f:
                data = f.read()
        except OSError as err:
            self._send_json(500, {"ok": False, "error": str(err)})
            return
        if is_html(target):
            # ?raw=1 skips injection — the editor fetches this to compare the
            # rendered DOM against the true source (script-generated markers).
            self._send_raw(200, "text/html", data if raw else inject_editor(data))
        else:
            ctype = mimetypes.guess_type(target)[0] or "application/octet-stream"
            self._send_raw(200, ctype, data)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _write_atomic(self, target, data_bytes):
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(target), suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(data_bytes)
        os.replace(tmp, target)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/save":
            self.handle_save()
        elif path == "/restore":
            self.handle_restore()
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def handle_save(self):
        try:
            data = self._read_json_body()
            raw_path = data["path"]
            html = data["html"]
        except (ValueError, KeyError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad request"})
            return

        target = resolve_save_target(raw_path)
        if target is None:
            self._send_json(403, {"ok": False, "error": "path not allowed"})
            return
        if not os.path.isfile(target):
            self._send_json(404, {"ok": False, "error": "file does not exist"})
            return

        backup = target + ".bak"
        if not os.path.exists(backup):
            shutil.copy2(target, backup)
        save_history(target)

        try:
            self._write_atomic(target, html.encode("utf-8"))
        except OSError as err:
            self._send_json(500, {"ok": False, "error": str(err)})
            return

        self._send_json(200, {"ok": True, "path": target})

    def handle_restore(self):
        try:
            data = self._read_json_body()
            raw_path = data["path"]
            version = data["version"]
        except (ValueError, KeyError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad request"})
            return

        target = resolve_save_target(raw_path)
        if target is None or not os.path.isfile(target):
            self._send_json(404, {"ok": False, "error": "file not found"})
            return
        # The version must be a bare filename belonging to this file's history.
        if version != os.path.basename(version) or not version.startswith(os.path.basename(target) + "."):
            self._send_json(403, {"ok": False, "error": "bad version"})
            return
        src = os.path.join(os.path.dirname(target), HISTORY_DIR, version)
        if not os.path.isfile(src):
            self._send_json(404, {"ok": False, "error": "version not found"})
            return

        save_history(target)  # snapshot the current state before restoring
        try:
            with open(src, "rb") as f:
                self._write_atomic(target, f.read())
        except OSError as err:
            self._send_json(500, {"ok": False, "error": str(err)})
            return
        self._send_json(200, {"ok": True, "path": target, "restored": version})

    def log_message(self, fmt, *args):
        print("[htmdoc] %s" % (fmt % args))


def inject_script_tags(port):
    """Legacy --inject mode: permanently add the editor tag to every
    .html/.htm directly in ROOT (skipping files that already have it), for
    pages that should be self-editable when opened via file://."""
    tag = ('<script src="http://127.0.0.1:%d/htmdoc.js" data-htmdoc></script>'
           % port).encode("ascii")
    injected = 0
    for name in sorted(os.listdir(ROOT)):
        if not is_html(name):
            continue
        path = os.path.join(ROOT, name)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            continue
        if any(mark in data for mark in EDITOR_MARKS):
            continue
        idx = data.lower().rfind(b"</body>")
        if idx == -1:
            new_data = data + b"\n" + tag + b"\n"
        else:
            new_data = data[:idx] + tag + b"\n" + data[idx:]
        fd, tmp = tempfile.mkstemp(dir=ROOT, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(new_data)
            os.replace(tmp, path)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            continue
        injected += 1
        print("[htmdoc] injected editor tag into %s" % name)
    if injected == 0:
        print("[htmdoc] all HTML files already wired up")


def main():
    global ROOT, PORT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8321)
    ap.add_argument("--root", default=os.path.expanduser("~"),
                    help="directory whose HTML files may be edited and saved (default: your home directory)")
    ap.add_argument("--inject", action="store_true",
                    help="also write the editor tag permanently into HTML files directly in root")
    args = ap.parse_args()
    ROOT = os.path.abspath(args.root)
    PORT = args.port
    if args.inject:
        inject_script_tags(args.port)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("[htmdoc] editable files under: %s" % ROOT)
    print("[htmdoc] open http://127.0.0.1:%d/ to install the bookmarklet (once)," % args.port)
    print("[htmdoc] then double-click any HTML file and click it to edit.")
    server.serve_forever()


if __name__ == "__main__":
    main()
