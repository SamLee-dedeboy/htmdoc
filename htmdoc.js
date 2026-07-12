/*!
 * htmdoc.js — formerly make-editable.js; old tags keep working.
 * Drop this script into a STATIC HTML page (via <script src="htmdoc.js"
 * data-htmdoc></script>) and every element becomes editable when the
 * page renders, with edits silently auto-saved back to the file on disk.
 *
 * Saving requires the companion helper:
 *     python3 htmdoc.py
 * The editor detects it automatically and auto-saves in place (a one-time
 * <file>.bak backup is created on the first save). Without the helper, the
 * Save button falls back to a file picker (Chromium) or a download.
 *
 * Scope: static HTML content. Pages whose scripts generate DOM (charts,
 * widgets) are out of scope — the editor shows a warning badge on such pages,
 * because saving the rendered DOM alongside the scripts that produced it can
 * duplicate or lose content.
 *
 * Features:
 *  - Whole-page editing via contentEditable (the browser's native editor)
 *  - Static inline SVG labels editable via a click-to-edit overlay
 *    (contentEditable doesn't work inside SVG)
 *  - Auto-save: debounced ~1s after each edit; Cmd/Ctrl+S flushes immediately;
 *    pending edits are flushed on page unload via sendBeacon
 *  - Links don't navigate while editing (Cmd/Ctrl+click still follows them)
 */
(function () {
  'use strict';

  if (window.__htmdoc || window.__makeEditable) return; // idempotent: safe to include twice
  // __makeEditable kept as an alias of the former name.
  var api = (window.__htmdoc = window.__makeEditable = { enabled: false, serverOk: false });

  var TOOLBAR_ID = 'me-toolbar';
  var STYLE_ID = 'me-style';
  var SVGEDIT_ID = 'me-svgedit';

  // The save server address. When this script is loaded FROM the server
  // (the injected <script src="http://127.0.0.1:<port>/htmdoc.js">),
  // its own URL is the server — so the port always matches. A local copy
  // falls back to data-port / 8321.
  var ownScript = document.currentScript;
  var SERVER = (function () {
    var src = (ownScript && ownScript.src) || '';
    var m = src.match(/^(https?:\/\/(?:127\.0\.0\.1|localhost)(?::\d+)?)\//);
    // The script's origin is the save server when it's a local http origin
    // and either differs from the page's origin (bookmarklet on a file://
    // page, or a manual absolute tag) or the tag is marked data-me-injected
    // (the server injected it in-flight while serving this very page — the
    // src is relative, so it resolves to the page's own origin). A plain
    // same-origin src just means some web server is serving a local copy of
    // this file, and is NOT the save server.
    // Also trust the page's own origin when it's served from the save
    // server's /files/ path (its signature) — covers pages that carry their
    // own relative editor tag and are opened through the file browser.
    if (m && (m[1] !== location.origin ||
              ownScript.hasAttribute('data-me-injected') ||
              location.pathname.indexOf('/files/') === 0)) {
      return m[1];
    }
    var port = (ownScript && ownScript.getAttribute('data-port')) || '8321';
    return 'http://127.0.0.1:' + port;
  })();
  api.server = SERVER;

  function onReady(fn) {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  }

  function injectStyle() {
    var css = [
      '#' + TOOLBAR_ID + '{position:fixed;top:12px;right:12px;z-index:2147483647;',
      'display:flex;flex-direction:column;padding:6px 8px;border-radius:10px;',
      'background:rgba(28,28,30,.92);color:#fff;font:13px/1.4 -apple-system,system-ui,sans-serif;',
      'box-shadow:0 4px 16px rgba(0,0,0,.25);user-select:none;-webkit-user-select:none;}',
      '#' + TOOLBAR_ID + ' .me-row{display:flex;gap:6px;align-items:center;}',
      '#' + TOOLBAR_ID + ' .me-legend{display:none;gap:12px;align-items:center;',
      'font-size:11px;color:rgba(255,255,255,.75);margin-top:6px;padding-top:5px;',
      'border-top:1px solid rgba(255,255,255,.15);}',
      'body.me-editing #' + TOOLBAR_ID + '.me-haslegend .me-legend{display:flex;}',
      '#' + TOOLBAR_ID + ' .me-sw{display:inline-block;width:9px;height:9px;border-radius:2px;',
      'margin-right:5px;vertical-align:-1px;border:2px dashed rgba(224,36,94,.9);}',
      '#' + TOOLBAR_ID + ' .me-sw.me-amber{border-color:rgba(217,144,10,.9);}',
      '#' + TOOLBAR_ID + ' button{all:unset;cursor:pointer;padding:4px 9px;border-radius:6px;',
      'background:rgba(255,255,255,.12);color:#fff;font:inherit;}',
      '#' + TOOLBAR_ID + ' button:hover{background:rgba(255,255,255,.24);}',
      '#' + TOOLBAR_ID + ' button.me-on{background:#34c759;color:#0a2a12;font-weight:600;}',
      '#' + TOOLBAR_ID + ' .me-fmt{font-weight:700;min-width:14px;text-align:center;}',
      '#' + TOOLBAR_ID + ' .me-status{color:rgba(255,255,255,.75);padding:0 4px;min-width:52px;text-align:center;}',
      '#' + TOOLBAR_ID + ' .me-min{padding:4px 7px;color:rgba(255,255,255,.7);}',
      '#me-chip{position:fixed;top:12px;right:12px;z-index:2147483647;display:none;',
      'width:34px;height:34px;border-radius:50%;background:rgba(28,28,30,.92);color:#fff;',
      'font:17px/34px -apple-system,system-ui,sans-serif;text-align:center;cursor:pointer;',
      'box-shadow:0 4px 16px rgba(0,0,0,.25);user-select:none;-webkit-user-select:none;}',
      '#me-chip:hover{background:rgba(50,50,54,.95);}',
      'body.me-editing :hover{outline:1px dashed rgba(0,122,255,.55);outline-offset:1px;}',
      'body.me-editing #' + TOOLBAR_ID + ' :hover{outline:none;}',
      // While editing, elements the tool can't (fully) edit carry their own
      // indicators: red = not editable / not saved, amber = partly editable.
      'body.me-editing canvas,body.me-editing video,body.me-editing audio,',
      'body.me-editing iframe,body.me-editing embed,body.me-editing object,',
      'body.me-editing .me-generated{outline:2px dashed rgba(224,36,94,.8);outline-offset:2px;}',
      'body.me-editing img,body.me-editing input,body.me-editing textarea,',
      'body.me-editing select{outline:2px dashed rgba(217,144,10,.75);outline-offset:2px;}',
      'body.me-editing #me-svgedit{outline:none;}',
      // SVG labels often disable pointer-events; re-enable them while editing
      // so they can be clicked and edited via the overlay input.
      'body.me-editing svg text,body.me-editing svg text *{pointer-events:all;cursor:text;}'
    ].join('');
    var style = document.createElement('style');
    style.id = STYLE_ID;
    style.textContent = css;
    document.head.appendChild(style);
  }

  // ---- Serialization ----
  // The saved file is the current DOM minus editor UI artifacts. Page markup —
  // including its <script> tags and this editor's tag — is kept verbatim, so
  // the saved file reopens editable. (Static-page scope: no scripts are
  // expected to regenerate DOM.)
  function serializePage() {
    var root = document.documentElement.cloneNode(true);
    // script[data-me-injected] is the tag the server adds while serving the
    // page — it must never be written into the file on disk.
    var kill = root.querySelectorAll(
      '#' + TOOLBAR_ID + ', #' + STYLE_ID + ', #' + SVGEDIT_ID + ', #me-chip, script[data-me-injected]'
    );
    for (var i = 0; i < kill.length; i++) kill[i].parentNode.removeChild(kill[i]);
    // Strip the scope indicators (hover titles, generated-content classes) —
    // they're editor UI, not page content.
    var titled = root.querySelectorAll('[data-me-titled]');
    for (var j = 0; j < titled.length; j++) {
      titled[j].removeAttribute('title');
      titled[j].removeAttribute('data-me-titled');
    }
    var gen = root.querySelectorAll('.me-generated');
    for (var k = 0; k < gen.length; k++) {
      gen[k].classList.remove('me-generated');
      if (!gen[k].getAttribute('class')) gen[k].removeAttribute('class');
    }
    var body = root.querySelector('body');
    if (body) {
      body.removeAttribute('contenteditable');
      body.classList.remove('me-editing');
      if (body.getAttribute('class') === '') body.removeAttribute('class');
    }
    return '<!DOCTYPE html>\n' + root.outerHTML;
  }

  // ---- Saving via the local helper server ----

  function filePath() {
    // file:// pages: absolute disk path. http-served pages: server-relative
    // path, resolved against the helper's --root.
    try { return decodeURIComponent(location.pathname); } catch (err) { return location.pathname; }
  }

  function currentFileName() {
    var name = filePath().split('/').pop();
    return name || 'page.html';
  }

  function setStatus(text) {
    if (api._statusEl) api._statusEl.textContent = text;
  }

  var saveTimer = null;
  var pendingSave = false;

  function savePayload() {
    return JSON.stringify({ path: filePath(), html: serializePage() });
  }

  function saveNow() {
    if (!api.serverOk) return Promise.resolve(false);
    pendingSave = false;
    clearTimeout(saveTimer);
    setStatus('Saving…');
    // text/plain keeps this a "simple" CORS request (no preflight), matching
    // what sendBeacon sends on unload.
    return fetch(SERVER + '/save', {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain' },
      body: savePayload()
    })
      .then(function (res) { return res.json(); })
      .then(function (out) {
        if (out && out.ok) { setStatus('Saved ✓'); return true; }
        setStatus('Save failed');
        return false;
      })
      .catch(function () {
        api.serverOk = false;
        setStatus('Server lost');
        return false;
      });
  }
  api.save = saveNow;

  function scheduleSave() {
    pendingSave = true;
    if (!api.serverOk) return;
    setStatus('…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(saveNow, 1000);
  }

  function flushOnUnload() {
    if (!pendingSave || !api.serverOk || !navigator.sendBeacon) return;
    pendingSave = false;
    clearTimeout(saveTimer);
    navigator.sendBeacon(SERVER + '/save', new Blob([savePayload()], { type: 'text/plain' }));
  }

  function detectServer() {
    var ctl = typeof AbortController !== 'undefined' ? new AbortController() : null;
    if (ctl) setTimeout(function () { ctl.abort(); }, 1500);
    return fetch(SERVER + '/health', { signal: ctl && ctl.signal })
      .then(function (res) { return res.ok; })
      .catch(function () { return false; })
      .then(function (ok) {
        api.serverOk = ok;
        setStatus(ok ? 'Auto-save: on' : 'No save server');
        if (ok && pendingSave) scheduleSave();
        return ok;
      });
  }

  // ---- Fallback save (no helper running) ----

  function downloadFile(html, filename) {
    var blob = new Blob([html], { type: 'text/html' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function fallbackSave() {
    var html = serializePage();
    if (!window.showSaveFilePicker) {
      downloadFile(html, currentFileName());
      setStatus('Downloaded');
      return Promise.resolve(false);
    }
    return Promise.resolve(api._fileHandle)
      .then(function (handle) {
        if (handle) return handle;
        return window.showSaveFilePicker({
          suggestedName: currentFileName(),
          types: [{ description: 'HTML file', accept: { 'text/html': ['.html', '.htm'] } }]
        });
      })
      .then(function (handle) {
        api._fileHandle = handle;
        return handle.createWritable()
          .then(function (w) { return w.write(html).then(function () { return w.close(); }); });
      })
      .then(function () {
        pendingSave = false;
        setStatus('Saved ✓');
        return true;
      })
      .catch(function (err) {
        if (err && err.name === 'AbortError') { setStatus(''); return false; }
        setStatus('Save failed');
        return false;
      });
  }

  function manualSave() {
    return api.serverOk ? saveNow() : fallbackSave();
  }

  // ---- Label overlay editing ----
  // Some labels can't be edited with the caret: SVG text (contentEditable
  // doesn't work inside SVG) and interactive controls like <button>, whose
  // activation would otherwise swallow the click. Both get a floating-input
  // overlay, opened by a plain click while editing (Alt/Option+click
  // activates the control instead). Enter/blur commits, Escape cancels.

  var svgEditInput = null;
  var svgEditTarget = null;

  function labelOf(el) {
    return el.tagName === 'INPUT' ? el.value : el.textContent;
  }

  function setLabel(el, value) {
    if (el.tagName === 'INPUT') {
      el.value = value;
      el.setAttribute('value', value); // sync the attribute so it serializes
    } else {
      el.textContent = value;
    }
  }

  // Deepest editable SVG text node (tspan/textPath/text) at or above el.
  // Walked by localName because camelCase SVG tags can't be matched with
  // CSS selectors (closest('textPath') never matches in an HTML document).
  function svgTextTarget(el) {
    var node = el;
    while (node && node.namespaceURI === 'http://www.w3.org/2000/svg') {
      var name = (node.localName || '').toLowerCase();
      if (name === 'tspan' || name === 'textpath' || name === 'text') return node;
      node = node.parentNode;
    }
    return null;
  }

  function closeSvgTextEditor(commit) {
    if (!svgEditInput) return;
    var input = svgEditInput;
    var target = svgEditTarget;
    svgEditInput = null;
    svgEditTarget = null;
    if (commit && input.value !== labelOf(target)) {
      setLabel(target, input.value);
      scheduleSave();
    }
    input.remove();
  }

  function openSvgTextEditor(target) {
    closeSvgTextEditor(true);
    var rect = target.getBoundingClientRect();
    var cs = getComputedStyle(target);
    var input = document.createElement('input');
    input.id = SVGEDIT_ID;
    input.value = labelOf(target);
    input.style.cssText =
      'position:fixed;z-index:2147483647;' +
      'left:' + Math.max(4, rect.left - 4) + 'px;' +
      'top:' + Math.max(4, rect.top + rect.height / 2 - 15) + 'px;' +
      'width:' + Math.max(90, Math.min(rect.width + 40, window.innerWidth - rect.left - 10)) + 'px;' +
      'padding:3px 7px;border:1.5px solid #007aff;border-radius:6px;' +
      'background:#fff;color:#000;outline:none;' +
      'box-shadow:0 3px 12px rgba(0,0,0,.3);' +
      'font-family:' + cs.fontFamily + ';' +
      'font-size:' + Math.max(12, parseFloat(cs.fontSize) || 13) + 'px;';
    input.addEventListener('keydown', function (e) {
      e.stopPropagation();
      if (e.key === 'Enter') { e.preventDefault(); closeSvgTextEditor(true); }
      else if (e.key === 'Escape') { e.preventDefault(); closeSvgTextEditor(false); }
    });
    input.addEventListener('blur', function () { closeSvgTextEditor(true); });
    svgEditInput = input;
    svgEditTarget = target;
    document.body.appendChild(input);
    input.focus();
    input.select();
  }

  // While editing, clicking a link would navigate away and lose edits.
  // Block plain clicks on links; Cmd/Ctrl+click still follows.
  // Clicks on SVG text open the overlay editor instead.
  function guardClicks(e) {
    if (!api.enabled) return;
    var t = e.target;
    if (!t || !t.closest) return;
    if (e.metaKey || e.ctrlKey) {
      // contentEditable suppresses link navigation even for modifier clicks,
      // so follow the link ourselves — in a new tab, keeping the edits.
      var link = t.closest('a[href]');
      if (link && !link.closest('#' + TOOLBAR_ID)) {
        e.preventDefault();
        e.stopPropagation();
        window.open(link.href, '_blank');
      }
      return;
    }
    // While editing, a plain click on a control edits its label;
    // Alt/Option+click activates it normally instead. The editor's own
    // toolbar buttons are exempt — they must always just work.
    var ctl = t.closest('button, summary, input[type="button"], input[type="submit"], input[type="reset"]');
    if (ctl && ctl.closest('#' + TOOLBAR_ID)) ctl = null;
    if (ctl) {
      if (e.altKey) return; // let the control do its thing
      e.preventDefault();
      e.stopPropagation();
      openSvgTextEditor(ctl);
      return;
    }
    var svgText = svgTextTarget(t);
    if (svgText) {
      e.preventDefault();
      e.stopPropagation();
      openSvgTextEditor(svgText);
      return;
    }
    var a = t.closest('a[href]');
    if (a && !a.closest('#' + TOOLBAR_ID)) {
      e.preventDefault();
    }
  }

  // ---- Scope indicators: mark what can't (fully) be edited ----
  // Instead of a generic page-level warning, the actual elements carry
  // dashed outlines while editing (styling above) plus a hover explanation.

  var UNEDITABLE_TITLES = {
    canvas: 'htmdoc: drawn by a script — not editable, and the drawing is not saved in the file',
    video: 'htmdoc: media content — not editable',
    audio: 'htmdoc: media content — not editable',
    iframe: 'htmdoc: a separate embedded document — the editor cannot reach inside it',
    embed: 'htmdoc: embedded content — not editable',
    object: 'htmdoc: embedded content — not editable',
    img: 'htmdoc: image — you can delete it, but its content is not editable',
    input: 'htmdoc: values typed or picked here are not saved (surrounding labels are editable)',
    textarea: 'htmdoc: text typed here is not saved (only the original content persists)',
    select: 'htmdoc: the chosen option is not saved (surrounding labels are editable)'
  };

  function insideEditorUi(el) {
    for (var p = el; p; p = p.parentElement) {
      var id = p.id || '';
      if (id === TOOLBAR_ID || id === SVGEDIT_ID || id === 'me-chip') return true;
    }
    return false;
  }

  // Hover explanations for the outlined elements. data-me-titled marks
  // titles we added so the serializer can strip them from saved files.
  function markUneditables() {
    var els = document.body.querySelectorAll(Object.keys(UNEDITABLE_TITLES).join(','));
    for (var i = 0; i < els.length; i++) {
      var el = els[i];
      if (insideEditorUi(el) || el.title) continue;
      el.title = UNEDITABLE_TITLES[el.tagName.toLowerCase()] || '';
      el.setAttribute('data-me-titled', '');
    }
  }

  // Show the toolbar's outline legend only when the page has something to
  // explain (any outlined element outside the editor's own UI).
  function updateLegend() {
    if (!api._bar) return;
    var any = document.body.querySelector(
      '.me-generated, canvas, video, audio, iframe, embed, object, img, textarea, select, input:not(#' + SVGEDIT_ID + ')'
    );
    if (any && insideEditorUi(any)) any = null;
    api._bar.classList.toggle('me-haslegend', !!any);
  }

  // Script-generated content: when the page is served from the save server
  // (/files/), fetch the raw source and mark every element that exists in
  // the rendered DOM but not in the file — that content will be re-created
  // by the page's scripts on next open, so edits to it may not stick.
  function sigOf(el) {
    return el.tagName + '#' + (el.id || '') + '.' + (el.getAttribute('class') || '');
  }

  function detectGenerated() {
    if (location.pathname.indexOf('/files/') !== 0 || typeof DOMParser === 'undefined') return;
    fetch(location.pathname + '?raw=1', { cache: 'no-store' })
      .then(function (r) { return r.text(); })
      .then(function (srcText) {
        var srcDoc = new DOMParser().parseFromString(srcText, 'text/html');
        var srcCounts = {};
        var srcEls = srcDoc.getElementsByTagName('*');
        for (var i = 0; i < srcEls.length; i++) {
          var s = sigOf(srcEls[i]);
          srcCounts[s] = (srcCounts[s] || 0) + 1;
        }
        var liveEls = document.body.getElementsByTagName('*');
        if (liveEls.length > 5000) return; // very large page: skip, perf
        var seen = {};
        outer:
        for (var j = 0; j < liveEls.length; j++) {
          var el = liveEls[j];
          var tag = el.tagName.toLowerCase();
          if (tag === 'script' || tag === 'style' || tag === 'link') continue;
          if (insideEditorUi(el)) continue;
          for (var p = el.parentElement; p; p = p.parentElement) {
            if (p.__meGenerated) continue outer; // only mark the topmost node
          }
          var sig = sigOf(el);
          seen[sig] = (seen[sig] || 0) + 1;
          if (seen[sig] > (srcCounts[sig] || 0)) {
            el.__meGenerated = true;
            el.classList.add('me-generated');
            if (!el.title) {
              el.title = 'htmdoc: created by this page’s script — edits here may be overwritten or duplicated when the page reopens';
              el.setAttribute('data-me-titled', '');
            }
          }
        }
        updateLegend();
      })
      .catch(function () {});
  }

  // ---- Toolbar ----

  function buildToolbar() {
    var bar = document.createElement('div');
    bar.id = TOOLBAR_ID;
    bar.setAttribute('contenteditable', 'false');

    var toggle = document.createElement('button');
    toggle.textContent = 'Editing: OFF';
    toggle.title = 'Toggle page editing';
    toggle.addEventListener('click', function () { api.toggle(); });

    function fmtButton(label, command, titleText) {
      var b = document.createElement('button');
      b.className = 'me-fmt';
      b.textContent = label;
      b.title = titleText;
      // mousedown + preventDefault so the text selection is not lost
      b.addEventListener('mousedown', function (e) {
        e.preventDefault();
        if (api.enabled) document.execCommand(command);
      });
      return b;
    }

    var save = document.createElement('button');
    save.textContent = 'Save';
    save.title = 'Save now (Cmd/Ctrl+S). Auto-save is on when the save server is running; without it this opens a file picker or downloads a copy.';
    save.addEventListener('click', manualSave);

    var status = document.createElement('span');
    status.className = 'me-status';
    status.title = 'Save status. Run "python3 htmdoc.py" for silent auto-save.';

    var row = document.createElement('div');
    row.className = 'me-row';
    row.appendChild(toggle);
    row.appendChild(fmtButton('B', 'bold', 'Bold'));
    row.appendChild(fmtButton('I', 'italic', 'Italic'));
    row.appendChild(fmtButton('U', 'underline', 'Underline'));
    row.appendChild(save);
    row.appendChild(status);

    var minBtn = document.createElement('button');
    minBtn.className = 'me-min';
    minBtn.textContent = '–';
    minBtn.title = 'Minimize the toolbar (editing and auto-save keep working)';
    minBtn.addEventListener('click', function () { api.minimize(); });
    row.appendChild(minBtn);
    bar.appendChild(row);

    // Legend for the scope outlines — only shown (via CSS) while editing on
    // pages that actually contain outlined elements.
    var legend = document.createElement('div');
    legend.className = 'me-legend';
    function legendItem(swClass, text) {
      var span = document.createElement('span');
      var sw = document.createElement('i');
      sw.className = 'me-sw' + (swClass ? ' ' + swClass : '');
      span.appendChild(sw);
      span.appendChild(document.createTextNode(text));
      return span;
    }
    legend.appendChild(legendItem('', 'not editable / not saved'));
    legend.appendChild(legendItem('me-amber', 'partly editable'));
    legend.title = 'Hover an outlined element on the page for the specific reason.';
    bar.appendChild(legend);

    var chip = document.createElement('div');
    chip.id = 'me-chip';
    chip.setAttribute('contenteditable', 'false');
    chip.textContent = '✎';
    chip.title = 'htmdoc — click to show the toolbar';
    chip.addEventListener('click', function () { api.expand(); });

    document.body.appendChild(bar);
    document.body.appendChild(chip);
    api._toggleBtn = toggle;
    api._statusEl = status;
    api._bar = bar;
    api._chip = chip;
  }

  api.minimize = function () {
    if (api._bar) api._bar.style.display = 'none';
    if (api._chip) api._chip.style.display = 'block';
  };

  api.expand = function () {
    if (api._bar) api._bar.style.display = '';
    if (api._chip) api._chip.style.display = 'none';
  };

  // ---- Enable / disable ----

  api.enable = function () {
    document.body.setAttribute('contenteditable', 'true');
    document.body.classList.add('me-editing');
    api.enabled = true;
    if (api._toggleBtn) {
      api._toggleBtn.textContent = 'Editing: ON';
      api._toggleBtn.classList.add('me-on');
    }
  };

  api.disable = function () {
    closeSvgTextEditor(true);
    document.body.removeAttribute('contenteditable');
    document.body.classList.remove('me-editing');
    api.enabled = false;
    if (api._toggleBtn) {
      api._toggleBtn.textContent = 'Editing: OFF';
      api._toggleBtn.classList.remove('me-on');
    }
    if (pendingSave) saveNow();
  };

  api.toggle = function () {
    api.enabled ? api.disable() : api.enable();
  };

  onReady(function () {
    injectStyle();
    buildToolbar();
    document.addEventListener('click', guardClicks, true);
    document.body.addEventListener('input', scheduleSave);
    document.addEventListener('keydown', function (e) {
      if ((e.metaKey || e.ctrlKey) && !e.shiftKey && !e.altKey && e.key.toLowerCase() === 's') {
        e.preventDefault();
        manualSave();
      }
    });
    window.addEventListener('pagehide', flushOnUnload);
    detectServer();
    markUneditables();
    updateLegend();
    detectGenerated();
    api.enable(); // editable immediately on render
  });
})();
