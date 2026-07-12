# htmdoc

**Open any HTML file on your computer, click once, and edit it like a
document.**

Built for people who create and share static HTML with AI agents all the
time. Agents get you 95% of the way: a polished report, a dashboard, a
data story, but the last 5% is surgical. Round-
tripping through prompt for a two-word fix is slow and can
touch things you didn't ask it to. htmdoc is that missing last step: open
the html in the browser, and edit it like a Word document.

## Setup (once)

You need [Python](https://www.python.org/downloads/) — already on most Macs;
Windows users install it once (**tick "Add python.exe to PATH"**).

1. **Download**: green **Code** button above → **Download ZIP** → unzip.
2. **Start the helper**:
   - **Mac**: open Terminal (⌘+Space, "Terminal"), type `python3 `, drag
     `htmdoc.py` into the window, press Return.
   - **Windows**: in the unzipped folder, type `cmd` in File Explorer's
     address bar, then run `python htmdoc.py`.

   **Leave the window open** — the helper only works while it's running.
3. **Install the bookmark**: go to **http://127.0.0.1:8321/** and drag the
   blue **Make editable** button onto your bookmarks bar (⌘⇧B / Ctrl+Shift+B
   shows the bar).

To practice, try it on the included `demo.html` first.

## Editing a file (every day)

1. Helper running? (If not: Setup step 2 — ten seconds.)
2. **Double-click your HTML file.**
3. **Click the "Make editable" bookmark.** The editor toolbar appears.
4. **Type.** A second later the toolbar shows **`Saved ✓`** — it's in the
   file. No save button, nothing else to do.

The first save creates a backup next to your file (same name + `.bak`), in
case you ever want the original back.

## What to expect while editing

A small dark toolbar floats in the top-right corner:

```
┌──────────────────────────────────────────────────┐
│ Editing: ON │ B │ I │ U │ Save │  Auto-save: on  │
└──────────────────────────────────────────────────┘
```

| Status | Meaning |
|---|---|
| `Auto-save: on` | The helper is running; your edits save themselves |
| `…` → `Saving…` → `Saved ✓` | You typed → it's being written → it's in the file |
| `Save failed` / `Server lost` | The save didn't happen — check the helper window is still open |
| `No save server` | The helper isn't running — do Setup step 2 again |

While editing, anything the tool can't (fully) edit is outlined right on the
page — hover an outlined element for the reason. A small legend row under
the toolbar recaps the colors (it only appears on pages that have such
elements):

| Outline | Meaning |
|---|---|
| **Red dashed** | Not editable / not saved: videos, audio, canvas drawings, embedded frames — and content created by the page's own programs (edits there may not stick) |
| **Amber dashed** | Partly editable: images (deletable, not redrawable) and form boxes (they stay, but typed values aren't saved) |

- Click into any heading, paragraph, list, or table cell and type.
- Clicking a link/button won't navigate away while you're editing. To actually follow a link, hold **Cmd** (Mac) or
  **Ctrl** (Windows) while clicking — it opens in a new tab, so your edits
  stay put. (Handily, that's the same shortcut browsers already use for
  opening a link in a tab without leaving the current page, so it likely
  matches your muscle memory.)
- Text labels inside charts and graphics (SVG images) can be edited too:
  click one, type in the little box that appears, press Enter.

## How saving works

- The first time a file is saved, a backup of the original is created next
  to it (same name, ending in `.bak`). It's made once and never touched
  again — delete it whenever you no longer want it.
- Saves are written safely: even if your computer crashes mid-save, the
  file can't end up half-written.
- Saved files contain only your page and your edits — no leftover pieces of
  this tool.

## If something isn't working

- **The toolbar says "No save server"** — the helper window isn't open.
  Start it again (Setup, step 2), then reload the page and click the
  bookmark again.
- **The bookmark does nothing** — check the helper window is open, then
  reload the page (⌘⇧R on Mac / Ctrl+Shift+R on Windows) and click it again.
- **`python3: command not found` (Mac)** — install Python once from
  [python.org/downloads](https://www.python.org/downloads/), then retry.
- **`python is not recognized` (Windows)** — reinstall Python and make sure
  to tick **"Add python.exe to PATH"** during the install.
- **An element has a red dashed outline** — the tool can't edit it (hover it
  for the reason); see "What it can't edit" below.
- **You want the original file back** — the file ending in `.bak` next to
  your file is the untouched original. Delete your edited file and remove
  `.bak` from the backup's name.

## Another way to open files: the file browser

The page at **http://127.0.0.1:8321/** also lists your folders and HTML
files. Click any file there and it opens ready to edit — no bookmark click
needed. Handy when you don't remember where a file lives.

## What it can't edit

This tool is for *documents*: pages made of text, images, tables, and
charts that sit still. Some pages are more like *apps* — they contain
programs (scripts) that build or change the page while you view it, for
example a chart that redraws when you move a slider. Editing those is
unreliable: the tool would save what the program drew, and the program
would draw it again on top the next time the page opens, doubling things
up. When you open a page like that through the file browser, the
script-created parts get a **red dashed outline** — take it as "edits here
may not stick."

A few other things that can't be changed in the page: what's *inside* an
image, drawings without text, and things you type into form boxes (the
boxes themselves stay, but typed-in values aren't part of the file).

<details><summary>Technical explanation</summary>

The editor saves the page by serializing the rendered DOM. On pages whose
scripts generate DOM (D3 charts, client-rendered widgets), that generated
content would be baked into the saved file and then regenerated on top of
it when reopened — duplicating or clobbering content. There is no general
way to know which DOM a script owns, so such pages are out of scope. Plain
`<script type="application/json">` data blocks are fine. Form control state
lives in JS properties, not attributes, so it doesn't serialize.
</details>

## How this compares to existing tools

Plenty of tools touch this space; none combine all of the properties this
one is built around (✅ yes · ◐ partial · ❌ no):

| | Edit visually in the browser | Your files, edited in place | Auto-saves to disk | Any local HTML file | No extension or app to install | No packages — runtime + stdlib only | Maintained |
|---|---|---|---|---|---|---|---|
| **htmdoc (this)** | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ ¹ | ✅ |
| `designMode` bookmarklets ([example](https://github.com/msankhala/editable-bookmarklet)) | ✅ | ❌ | ❌ | ✅ | ✅ | ✅ | ✅ |
| [Chrome DevTools Workspaces](https://developer.chrome.com/docs/devtools/workspaces) | ◐ ² | ◐ ² | ◐ ² | ❌ | ✅ | ✅ | ✅ |
| [SingleFile](https://github.com/gildas-lormeau/SingleFile) | ❌ | ❌ | ❌ | ✅ | ❌ ³ | ✅ | ✅ |
| [TiddlyWiki](https://tiddlywiki.com/static/Saving.html) + [Timimi](https://github.com/ibnishak/Timimi) | ✅ | ✅ | ✅ | ❌ ⁴ | ❌ ³ | ◐ | ✅ |
| [MikaelMayer/Editor](https://github.com/MikaelMayer/Editor) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ ⁵ | ❌ ⁵ |
| [GrapesJS](https://github.com/GrapesJS/grapesjs), [VvvebJs](https://github.com/givanz/Vvvebjs) | ✅ | ❌ ⁶ | ◐ ⁶ | ❌ | ✅ | ❌ | ✅ |
| Pinegrow, Dreamweaver, Bootstrap Studio | ✅ | ✅ | ✅ | ✅ | ❌ ⁷ | ❌ | ✅ |

¹ To be fair: a Python 3 runtime is required — preinstalled on macOS/Linux,
a one-time install on Windows. "No packages" means nothing beyond that:
stdlib only, no `pip`/`npm`, copy two files and run.
² CSS edits only — Chrome [deliberately refuses](https://developer.chrome.com/docs/devtools/workspaces)
to save DOM/HTML edits back to source ("the DOM ≠ the HTML"), and each
folder needs workspace setup.
³ Requires a browser extension (Timimi also needs a native host install).
⁴ TiddlyWiki files only.
⁵ Needs the Node runtime *plus* an npm package and its dependency tree; the
closest relative to this tool, but it attempted the ambiguous DOM→source
mapping problem and has been unmaintained since 2019.
⁶ Page *builders*: you construct pages inside their canvas and export —
they don't open an existing file in place, and saving needs a backend you write.
⁷ Full (mostly commercial) desktop applications.

**In short:** the runtime requirement is comparable to Editor's (Python vs.
Node — both an install on Windows); what separates this tool is everything
after the runtime: no package manager step, two readable files, an actively
maintained codebase, your existing double-click workflow, saved files with
no tooling traces — and an honestly-stated static-pages scope, deliberately
avoiding the DOM-vs-source wall that stalled the more ambitious projects
above.

---

*Everything below is for technical readers — you don't need any of it to
use the tool.*

## Options

| Flag | Effect |
|---|---|
| `--root DIR` | Directory whose files can be edited (default: your home directory). Also the security boundary. |
| `--port N` | Port (default 8321). Everything adapts automatically. |
| `--inject` | Permanently write the editor tag into HTML files directly in root, making them self-editable without even the bookmark click. |

## Security notes

The server binds `127.0.0.1` only, refuses paths outside `--root`, only
writes to existing `.html`/`.htm` files, writes atomically, and keeps a
one-time `.bak`. There is no auth token in this version, so any page running
in your browser could in principle POST to it while it's running — run it
only while editing, or narrow `--root`, or add a token if that matters in
your environment.

## JS API

On any page with the editor loaded: `window.__htmdoc.enable() /
.disable() / .toggle() / .save()`, plus `.server` (resolved server address)
and `.serverOk` (whether auto-save is live).

## Try it

```sh
python3 htmdoc.py --root .     # from this repo's directory
# open http://127.0.0.1:8321/ and click demo.html — or double-click
# demo.html in Finder and use the bookmarklet
```
