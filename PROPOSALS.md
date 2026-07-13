# htmdoc — review & proposals

A review of the project as of `96791ed`, with proposed next steps ranked by
value.

## Status: all implemented ✅

Every item below has been done (verified with 22 passing tests plus a live
browser round-trip). Summary of what changed:

| # | Item | Landed in |
|---|---|---|
| 1 | Origin/Host guards, scoped CORS, optional `--token`, loud root warning | `htmdoc.py`, `htmdoc.js` |
| 2 | Test suite for the disk-write path (22 tests, stdlib) | `test_htmdoc.py` |
| 3 | LICENSE (MIT) | `LICENSE` |
| 4 | Insert menu: link / table / image / divider | `htmdoc.js` |
| 5 | Paste sanitization (+ Shift = plain text) | `htmdoc.js` |
| 6 | No-op saves skipped (client + server); README notes round-trip | `htmdoc.py`, `htmdoc.js` |
| 7 | One-click launchers | `htmdoc-mac.command`, `htmdoc-windows.bat` |
| 8 | Toolbar a11y (aria-labels, focus ring) + `styleWithCSS` highlight fix | `htmdoc.js` |
| 9 | `execCommand` deprecation noted | `htmdoc.js` comment |
| 10 | Windows `file://` path normalization (+ test) | `htmdoc.py` |
| 11 | `EDITOR_MARKS` false-positive fix, `file://` restore nudge, live scope-mark refresh | `htmdoc.py`, `htmdoc.js` |
| 12 | Removed stale zip/`.DS_Store`; GitHub Actions CI | `.github/workflows/test.yml`, `.gitignore` |

The original review follows, for reference.

## What's already strong

- **Tight scope, honestly stated.** The "static documents, not apps" boundary
  is drawn deliberately and explained (README "What it can't edit" + the
  script-generated-content detector). That honesty is the product's spine.
- **Small, readable surface.** Two files, stdlib-only, ~1.5k lines total. The
  comments explain *why* (e.g. the `text/plain` no-preflight note, the
  camelCase-SVG `localName` walk). Easy to audit and maintain.
- **Careful disk writes.** Atomic `os.replace`, one-time `.bak`, rolling
  10-version history with a restore path, path-traversal guard in `safe_join`.
- **Thoughtful UX details.** Scope outlines with hover reasons, live block-style
  dropdown, minimize-to-chip, Cmd/Ctrl+click to follow links, SVG-label overlay.
- **Excellent README.** The comparison table and the "last 5% after an AI draft"
  framing are genuinely good positioning.

The gaps below are mostly *because* the tool is good enough to now be exposed to
real files and real browsers.

---

## Tier 1 — should do (correctness, safety, trust)

### 1. Close the cross-site write/read hole
**Why:** The helper defaults `--root` to the **entire home directory**
([htmdoc.py:450](htmdoc.py:450)), sets `Access-Control-Allow-Origin: *` on every
response ([htmdoc.py:248](htmdoc.py:248)), and `/save` is sent as
`Content-Type: text/plain` ([htmdoc.js:213](htmdoc.js:213)) — deliberately a CORS
"simple request" so there's no preflight. The combination means: **while the
helper is running, any website open in the browser can POST to
`http://127.0.0.1:8321/save` and overwrite any `.html` file under your home
directory** (the write happens server-side regardless of whether CORS lets them
read the reply), and can *read* your HTML files / enumerate folders via
`/files/` + `/browse/` because of the `*` header. A DNS-rebinding site bypasses
the "localhost only" bind entirely. The README acknowledges the missing token;
this proposes a concrete, zero-friction fix.

**What (defense in depth, all stdlib):**
- **Host-header check** — reject requests whose `Host` isn't `127.0.0.1:PORT` /
  `localhost:PORT`. Kills DNS rebinding (rebound requests carry the attacker's
  hostname).
- **Origin allowlist on POST** — accept only `Origin: null` (file:// pages) or
  the server's own origin; reject everything else. Blocks other sites' CSRF
  writes without touching the happy path.
- **Stop echoing `ACAO: *`** — reflect only the server origin (or drop it; the
  write doesn't need a readable response).
- **Optional `--token`** — server prints a token, bookmarklet carries it, `/save`
  and `/restore` require it. Opt-in for shared/multi-user machines.
- Consider making `--root` default to something narrower than `~`, or at least
  loudly print the effective root and its blast radius at startup.

**Effort:** ~30–40 lines in `Handler`. High value — this is the one item I'd do
first.

### 2. Add a test suite for the disk-write path
**Why:** The scariest code (writes to real user files) has zero automated
coverage, and `htmdoc.py` imports cleanly (server only starts under
`__main__`), so it's easy to test.

**What (stdlib `unittest`, temp dirs):**
- `safe_join` / `resolve_save_target` — traversal (`../`), symlink escape,
  non-`.html` rejection, `/files/` vs absolute vs bare-name resolution
  ([htmdoc.py:106](htmdoc.py:106), [htmdoc.py:129](htmdoc.py:129)).
- `save` — first save creates `.bak` exactly once; atomic replace; rejects paths
  outside root; rejects non-existent files.
- `save_history` — rotation keeps exactly `HISTORY_KEEP`
  ([htmdoc.py:61](htmdoc.py:61)); `handle_restore` rejects a `version` that isn't
  a bare filename for *this* file ([htmdoc.py:383](htmdoc.py:383)).
- A couple of end-to-end `http.client` calls against a server on an ephemeral
  port (health, serve+inject, save round-trip, the Tier-1 Origin/Host rejects).

**Effort:** half a day. Backs the "actively maintained" claim in the README's
comparison table.

### 3. Add a LICENSE
**Why:** The README positions the tool against named open-source projects and
advertises "Maintained ✅", but there's no license file — which legally means
"all rights reserved" and blocks the reuse the framing invites. Pick one (MIT
fits the spirit) and add it.

**Effort:** minutes.

---

## Tier 2 — real feature/UX gains

### 4. Insert operations, not just edit-in-place
Today you can edit an *existing* link/table/image but can't create new ones. The
most-missed authoring actions:
- **Make a link from selected text** (`createLink`) — the link editor
  ([htmdoc.js:627](htmdoc.js:627)) only edits links that already exist.
- **Insert table** (then the existing +Row/+Col ops take over).
- **Insert image** from file as a data URI (the swap logic in
  [htmdoc.js:644](htmdoc.js:644) already embeds — reuse it for insert).
- **Insert horizontal rule / divider.**

**Effort:** a small "Insert ▾" menu; each item is a few lines. High
user-visible payoff.

### 5. Paste sanitization / paste-as-plain-text
**Why:** The target workflow is pasting from AI chats, Word, and Google Docs —
all of which inject huge inline-styled span soup into contentEditable, which then
gets serialized straight into the file. There's currently no `paste` handler.

**What:** intercept `paste`, strip to a safe subset (or plain text with a
modifier), so edits stay clean and diffs stay small.

**Effort:** ~30–50 lines. Meaningfully improves output quality.

### 6. Minimize save-diff noise (git-friendliness)
**Why:** `serializePage` re-serializes the whole DOM via `outerHTML`
([htmdoc.js:151](htmdoc.js:151)). The browser normalizes attribute quoting/order
and whitespace, so a two-word edit can produce a large, noisy diff against the
original file — which undercuts the "surgical last 5%" pitch for anyone who
version-controls their HTML.

**What:** at minimum, measure it on a real file and document the behavior. If
it's bad, explore preserving untouched regions, or a light normalization pass so
re-saves are stable (idempotent save = save an unchanged page, expect a
near-empty diff). Worth a spike before committing to an approach.

### 7. One-click launch (skip the Terminal)
**Why:** The audience is people who receive HTML from AI, not necessarily people
comfortable in a shell. The README's setup step 2 (open Terminal, type
`python3`, drag the file) is the biggest drop-off point.

**What:** ship a double-clickable launcher — a `.command` on macOS and a `.bat`
on Windows that just runs the helper — and/or a `pipx`/`uvx` one-liner for the
technical path. Keep the stdlib-only core; these are thin wrappers.

**Effort:** small, mostly docs + two tiny scripts.

---

## Tier 3 — polish & longer-term

### 8. Toolbar accessibility & cross-browser formatting
- Buttons rely on `title` only — add `aria-label`s and visible focus states.
- **Verify `hiliteColor`** works without `styleWithCSS` across browsers
  ([htmdoc.js:915](htmdoc.js:915)); Chrome sometimes needs `backColor` or a
  `styleWithCSS` toggle first. Worth a quick manual check in Chrome + Firefox +
  Safari.

### 9. Note the `execCommand` deprecation risk
All formatting goes through `document.execCommand`
([htmdoc.js:834](htmdoc.js:834), [876](htmdoc.js:876),
[907](htmdoc.js:907)), which is deprecated (though still broadly supported).
No need to rewrite now, but record it as a known long-term risk so a future
browser change isn't a surprise. A full replacement (Selection/Range-based
commands) is a large effort — track, don't chase.

### 10. Verify Windows `file://` paths end-to-end
`filePath()` returns `location.pathname` ([htmdoc.js:182](htmdoc.js:182)), which
on Windows looks like `/C:/Users/...`. Confirm `resolve_save_target`'s
`os.path.isabs` / `realpath` handling actually maps that back to the right file
under `--root` on Windows, since the README explicitly courts Windows users.

### 11. Small edge cases
- **`EDITOR_MARKS` false positive:** injection is skipped if the bytes
  `htmdoc`/`make-editable` appear *anywhere* in the file
  ([htmdoc.py:119](htmdoc.py:119)) — a document that merely mentions the tool
  won't become editable. Tighten to match the actual tag.
- **Restore on a `file://` page reloads without the editor.** `handle_restore`
  → `location.reload()` ([htmdoc.js:754](htmdoc.js:754)) works for `/files/`
  pages (editor re-injected) but a bookmarklet'd `file://` page comes back plain;
  the user must click the bookmark again. Worth a note or a nudge.
- **Legend/uneditable outlines don't refresh after DOM changes**
  (`markUneditables`/`updateLegend` run once on ready,
  [htmdoc.js:1071](htmdoc.js:1071)); inserting a table/image later won't outline
  it until reload.

### 12. Repo housekeeping / CI
- `editable-html.zip` (old `make-editable.js`/`save-server.py` names) sits in the
  working tree — gitignored and untracked, but stale clutter; consider deleting.
- Add a minimal GitHub Actions workflow running the Tier-2 tests on push, so the
  "Maintained" badge is demonstrably true.

---

## Suggested order

1. **#1 Origin/Host hardening** — biggest safety win, small.
2. **#2 Tests** — locks in the write path before changing more.
3. **#3 LICENSE** — trivial, unblocks sharing.
4. **#4 Insert ops** + **#5 paste cleanup** — the two features users will feel.
5. **#7 one-click launch** — widens the audience.
6. Tier 3 as time allows.

Happy to implement any of these next — say which and I'll start.
