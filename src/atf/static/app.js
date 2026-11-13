// atf edit — the fixed chrome's Run button, the Resources actions (native <details>, no JS needed),
// and the Tests editor: a real text surface with live syntax colour and autocomplete. Every fetch
// stays same-origin (loopback only); nothing here talks to anything but this server.
"use strict";

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function currentEnv() {
  return new URLSearchParams(location.search).get("env") || "";
}

function withEnv(path) {
  const env = currentEnv();
  return env ? `${path}${path.includes("?") ? "&" : "?"}env=${encodeURIComponent(env)}` : path;
}

function runUrl(tests) {
  const params = new URLSearchParams();
  const env = currentEnv();
  if (env) params.set("env", env);
  (tests || []).forEach((id) => params.append("test", id));
  const qs = params.toString();
  return "/api/run" + (qs ? `?${qs}` : "");
}

// --- The Run button: a real background run, polled for status, cancellable, never re-offered -----
//
// The label text never changes ("Run" always) so the button never resizes and shifts the nav next
// to it — running/passed/failed show only as colour and the spinner. Progress is a *separate*
// element (#run-elapsed) so its own width changing doesn't move the button either. `RunControl`
// is shared with the Tests page so one test's "Run this test" starts the same tracked run.

let RunControl = null;

function initRunButton() {
  const btn = document.getElementById("run-btn");
  if (!btn) return;
  const spin = btn.querySelector(".spin");
  const elapsedEl = document.getElementById("run-elapsed");
  const cancelBtn = document.getElementById("cancel-btn");
  let poller = null;

  function fmt(seconds) {
    const s = Math.max(0, Math.round(seconds));
    return s < 60 ? `${s}s` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }

  function showElapsed(elapsed, estimate) {
    elapsedEl.hidden = false;
    elapsedEl.textContent = estimate ? `${fmt(elapsed)} / ~${fmt(estimate)}` : fmt(elapsed);
  }

  function setRunning(isRunning) {
    btn.classList.toggle("running", isRunning);
    spin.hidden = !isRunning;
    cancelBtn.hidden = !isRunning;
    elapsedEl.hidden = !isRunning;
    btn.disabled = isRunning;
  }

  async function poll() {
    let data;
    try {
      data = await (await fetch(withEnv("/api/run/status"))).json();
    } catch {
      return;
    }
    if (data.running) {
      showElapsed(data.elapsed, data.estimate);
      poller = setTimeout(poll, 1000);
      return;
    }
    setRunning(false);
    location.reload();
  }

  function startPolling() {
    setRunning(true);
    clearTimeout(poller);
    poll();
  }

  RunControl = {
    running: () => btn.classList.contains("running"),
    start: async (tests) => {
      if (btn.classList.contains("running")) return;
      try {
        await fetch(runUrl(tests), { method: "POST" });
      } catch {
        return;
      }
      startPolling();
    },
  };

  btn.addEventListener("click", () => RunControl.start([]));

  cancelBtn.addEventListener("click", async () => {
    cancelBtn.disabled = true;
    try {
      await fetch(withEnv("/api/run/cancel"), { method: "POST" });
    } finally {
      cancelBtn.disabled = false;
    }
  });

  // A refresh mid-run lands here with the button already server-rendered as running.
  if (btn.classList.contains("running")) startPolling();
}

// --- Tests: the search box live-filters the rendered rows; opening one is a real link (`_test_row`
// already renders `<a href="/tests/{id}">`), so the pane arrives server-rendered — nothing here
// fetches it. ---------------------------------------------------------------------------------------

function initTestSearch() {
  const search = document.getElementById("test-search");
  if (!search) return;
  const groups = Array.from(document.querySelectorAll(".filegroup"));
  search.addEventListener("input", () => {
    const needle = search.value.trim().toLowerCase();
    groups.forEach((group) => {
      const rows = Array.from(group.querySelectorAll(".trow"));
      let anyShown = false;
      rows.forEach((row) => {
        const hit = !needle || (row.dataset.search || "").includes(needle);
        row.style.display = hit ? "" : "none";
        anyShown = anyShown || hit;
      });
      group.style.display = anyShown ? "" : "none";
    });
  });
}

// --- The editor surface: a transparent textarea over a coloured backdrop, a synced line-number
// gutter, and autocomplete ranked by shared words against what's typed — the same closeness
// `steps.undefined()` uses server-side to name the nearest step ATF knows, done here client-side
// against the suite's whole sayable vocabulary since there's no "so far" to narrow it while typing. -

const KEYWORDS = new Set(["given", "when", "then", "and", "but"]);
const LINE_HEIGHT = 13 * 1.9; // px — must track .editor-input's font-size/line-height in app.css

function initEditorSurface() {
  const input = document.getElementById("editor-input");
  if (!input) return;
  const backdrop = document.getElementById("editor-backdrop");
  const gutter = document.getElementById("editor-gutter");
  const gutterIcons = document.getElementById("gutter-icons");
  const stickyScenario = document.getElementById("sticky-scenario");
  const suggest = document.getElementById("suggest");
  const statusEl = document.getElementById("editor-status");
  const tryBtn = document.getElementById("try-btn");
  const saveBtn = document.getElementById("save-btn");
  const runScenarioBtn = document.getElementById("run-scenario-btn");
  const filenameInput = document.getElementById("filename-input");

  const kindWordsEl = document.getElementById("kind-words");
  const kindWords = new Set(kindWordsEl ? JSON.parse(kindWordsEl.textContent) : []);
  const phraseListEl = document.getElementById("phrase-list");
  const phrases = phraseListEl ? JSON.parse(phraseListEl.textContent) : [];
  const highlightHtml = backdrop.querySelector(".line-highlight")?.outerHTML || "";

  // What every sentence means (hover) and what's worth a second look (the advisory gutter icons)
  // — a fact and a soft suggestion, never a fault, so neither ever blocks a save. Both start from
  // what the server rendered, and refresh on the same pause-in-typing debounce lint already uses.
  const hovercard = document.getElementById("hovercard");
  const popover = document.getElementById("qf-popover");
  const meaningsDataEl = document.getElementById("meanings-data");
  let meaningsByLine = {};
  (meaningsDataEl ? JSON.parse(meaningsDataEl.textContent) : []).forEach((m) => (meaningsByLine[m.line] = m));
  // start line → { width, phrase }, only while that run is folded to a view-only line — the file
  // itself never changes because of this; only a real 💡 rewrite ever does that.
  const foldedRanges = new Map();

  // Mirrors `_highlight_words`/`_highlight_line`/`_render_backdrop` in editor.py exactly — same
  // colouring from the same rules, just run on every keystroke instead of once at render time.
  function highlightWords(chunk) {
    return chunk
      .split(/(\s+)/)
      .map((word) => (kindWords.has(word.trim()) ? `<span class="tok-kind">${escapeHtml(word)}</span>` : escapeHtml(word)))
      .join("");
  }

  function highlightLine(text) {
    const parts = [];
    let last = 0;
    const re = /"[^"]*"/g;
    let m;
    while ((m = re.exec(text))) {
      parts.push(highlightWords(text.slice(last, m.index)));
      parts.push(`<span class="tok-str">${escapeHtml(m[0])}</span>`);
      last = m.index + m[0].length;
    }
    parts.push(highlightWords(text.slice(last)));
    return parts.join("");
  }

  // A phrase-shaped run currently folded to a view-only line — client state only, never disk.
  // Keyed by its start line, so a click on the same chevron toggles the same entry back off.
  function foldedRangeAt(number) {
    for (const [start, info] of foldedRanges) {
      if (number >= start && number < start + info.width) {
        return { start, width: info.width, phrase: info.phrase, isLast: number === start + info.width - 1 };
      }
    }
    return null;
  }

  function renderBackdrop(text) {
    return text
      .split("\n")
      .map((line, i) => {
        const number = i + 1;
        const stripped = line.replace(/^ +/, "");
        const indent = line.slice(0, line.length - stripped.length);
        const spaceAt = stripped.indexOf(" ");
        const word = spaceAt > -1 ? stripped.slice(0, spaceAt) : "";
        const hasMeaning = Object.prototype.hasOwnProperty.call(meaningsByLine, number);
        // The `.tok` wrap is decoration only — the mouse-move hit test on the real textarea, not
        // a `:hover` here, is what shows the fact, and it is what excludes a quoted value from it.
        let body;
        if (spaceAt > -1 && KEYWORDS.has(word.toLowerCase())) {
          const rest = highlightLine(stripped.slice(spaceAt + 1));
          body = `<span class="tok-kw">${escapeHtml(word)}</span> ${hasMeaning ? `<span class="tok">${rest}</span>` : rest}`;
        } else {
          const rest = highlightLine(stripped);
          body = hasMeaning ? `<span class="tok">${rest}</span>` : rest;
        }
        const folded = foldedRangeAt(number);
        if (folded) {
          body = `<span class="folded-dim">${body}</span>`;
          if (folded.isLast) body += ` <span class="fold-marker">folded — ${escapeHtml(folded.phrase)}</span>`;
        }
        return indent + body;
      })
      .join("\n");
  }

  // --- Inline linting: what `atf plan` would say about this draft, checked on a pause in typing,
  // without saving. A line marker is decorative only (pointer-events:none — it must never steal a
  // click meant for the textarea underneath it), so the message itself lives in the status line.

  let lintProblems = [];
  let lintTimer = null;

  function lintMarkersHtml(text) {
    if (!lintProblems.length) return "";
    const lines = text.split("\n");
    return lintProblems
      .map((msg) => {
        const at = lines.findIndex((l) => l.trim() && msg.includes(l.trim()));
        return at === -1 ? "" : `<div class="lint-line" style="top:calc(${at} * 1.9em)"></div>`;
      })
      .join("");
  }

  function paintLintStatus() {
    if (lintProblems.length) {
      const more = lintProblems.length > 1 ? ` (+${lintProblems.length - 1} more)` : "";
      statusEl.textContent = `⚠ ${lintProblems[0]}${more}`;
      statusEl.className = "status fail";
    } else if (dirty) {
      // Problems cleared but the draft still isn't saved — restore the plain note markDirty set
      // once and won't set again (its own early-return only fires on the very first edit).
      statusEl.textContent = "edited — not yet saved";
      statusEl.className = "status";
    }
  }

  function scheduleLint() {
    clearTimeout(lintTimer);
    lintTimer = setTimeout(async () => {
      try {
        const res = await fetch(withEnv("/api/tests/lint"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: input.value }),
        });
        const data = await res.json();
        lintProblems = data.problems || [];
      } catch {
        lintProblems = [];
      }
      paintBackdrop();
      paintLintStatus();
    }, 500);
  }

  function paintBackdrop() {
    backdrop.innerHTML = highlightHtml + lintMarkersHtml(input.value) + renderBackdrop(input.value);
  }

  // --- Hover: what a sentence's fixed words mean — a fact, never an action. The backdrop sits
  // under the real (transparent) textarea, so a `:hover` there would never fire; this hit-tests
  // the mouse against the textarea itself and positions one floating card by hand instead. --------

  let charWidth = 0;
  function measureCharWidth() {
    const probe = document.createElement("span");
    probe.style.font = getComputedStyle(input).font;
    probe.style.position = "absolute";
    probe.style.visibility = "hidden";
    probe.style.whiteSpace = "pre";
    probe.textContent = "0".repeat(40);
    document.body.appendChild(probe);
    const width = probe.getBoundingClientRect().width / 40;
    document.body.removeChild(probe);
    return width || 7.8;
  }

  function quotedRanges(line) {
    const ranges = [];
    const re = /"[^"]*"/g;
    let m;
    while ((m = re.exec(line))) ranges.push([m.index, m.index + m[0].length]);
    return ranges;
  }

  function hideHovercard() {
    hovercard.hidden = true;
  }

  function showHovercard(meaning, row, col) {
    const fact = meaning.phrase
      ? `a phrase this suite teaches — <b>${escapeHtml(meaning.where)}</b>`
      : `answered by <b>${escapeHtml(meaning.where)}</b>${meaning.doc ? ` — ${escapeHtml(meaning.doc)}` : ""}`;
    hovercard.innerHTML = `<div class="title">${escapeHtml(meaning.pattern)}</div>${fact}`;
    hovercard.hidden = false;
    const top = 14 + row * LINE_HEIGHT - input.scrollTop + LINE_HEIGHT;
    const left = Math.min(Math.max(0, col * charWidth), input.clientWidth - 280);
    hovercard.style.top = `${Math.max(4, top)}px`;
    hovercard.style.left = `${Math.max(4, left)}px`;
  }

  input.addEventListener("mousemove", (e) => {
    if (!charWidth) charWidth = measureCharWidth();
    const rect = input.getBoundingClientRect();
    const row = Math.floor((e.clientY - rect.top + input.scrollTop - 14) / LINE_HEIGHT);
    const lineText = input.value.split("\n")[row];
    const meaning = lineText === undefined ? null : meaningsByLine[row + 1];
    if (!meaning) {
      hideHovercard();
      return;
    }
    const col = Math.round((e.clientX - rect.left + input.scrollLeft) / charWidth);
    if (quotedRanges(lineText).some(([s, e2]) => col >= s && col < e2)) {
      hideHovercard();
      return;
    }
    showHovercard(meaning, row, col);
  });
  input.addEventListener("mouseleave", hideHovercard);

  function scheduleMeanings() {
    clearTimeout(scheduleMeanings.timer);
    scheduleMeanings.timer = setTimeout(async () => {
      try {
        const res = await fetch(withEnv("/api/tests/meanings"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: input.value }),
        });
        const data = await res.json();
        meaningsByLine = {};
        (data.meanings || []).forEach((m) => (meaningsByLine[m.line] = m));
      } catch {
        meaningsByLine = {};
      }
      paintBackdrop();
    }, 500);
  }

  // --- Advisories: a second look, never a fault — a duplicate scenario's 💡, and a run of raw
  // steps that already says a phrase this suite teaches (a fold ▾, and its own rewrite 💡). Both
  // gutter icons refresh on the same debounce lint already runs on; the draft-claim 💡 does not —
  // it is rendered once from disk, since drafting only ever reads what a real run produced. -------

  function gutterIcon(line, innerHtml) {
    const el = document.createElement("div");
    el.className = "gutter-icon gutter-icon-advisory";
    el.style.top = `calc(14px + ${line - 1} * 1.9em)`;
    el.innerHTML = innerHtml;
    return el;
  }

  function paintAdvisories(found) {
    if (!gutterIcons) return;
    gutterIcons.querySelectorAll(".gutter-icon-advisory").forEach((el) => el.remove());
    // An edit can move a folded run without moving its start line along with it — the fold is
    // only kept where the phrase match it stands for is still actually there to find.
    const stillMatching = new Set(found.filter((one) => one.kind === "phrase").map((one) => one.start));
    for (const start of [...foldedRanges.keys()]) {
      if (!stillMatching.has(start)) foldedRanges.delete(start);
    }
    found.forEach((one) => {
      if (one.kind === "duplicate" && one.target) {
        gutterIcons.appendChild(
          gutterIcon(
            one.line,
            `<button type="button" class="qf-icon" data-qf="dup" data-target="${escapeHtml(one.target)}" ` +
              `data-hint="${escapeHtml(one.hint)}" title="quick fix">💡</button>`
          )
        );
      } else if (one.kind === "phrase") {
        const chev =
          `<button type="button" class="fold-chev" data-fold-start="${one.start}" data-fold-width="${one.width}" ` +
          `data-phrase="${escapeHtml(one.phrase)}" title="fold — view only">▾</button>`;
        const rewrite = one.replacement
          ? `<button type="button" class="qf-icon" data-qf="phraseuse" data-fold-start="${one.start}" ` +
            `data-fold-width="${one.width}" data-hint="${escapeHtml(one.hint)}" ` +
            `data-replacement="${escapeHtml(one.replacement)}" title="quick fix">💡</button>`
          : "";
        gutterIcons.appendChild(gutterIcon(one.start, `<span class="gutter-group">${chev}${rewrite}</span>`));
      }
    });
  }

  function scheduleAdvisories() {
    clearTimeout(scheduleAdvisories.timer);
    scheduleAdvisories.timer = setTimeout(async () => {
      let found = [];
      try {
        const res = await fetch(withEnv("/api/tests/advisories"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: input.value, id: input.dataset.testId || "" }),
        });
        const data = await res.json();
        found = data.advisories || [];
      } catch {
        found = [];
      }
      const before = foldedRanges.size;
      paintAdvisories(found);
      if (foldedRanges.size !== before) paintBackdrop();
    }, 500);
  }

  function foldLines(start, width, replacement) {
    const lines = input.value.split("\n");
    const indent = (lines[start - 1].match(/^[ \t]*/) || [""])[0];
    lines.splice(start - 1, width, indent + replacement);
    input.value = lines.join("\n");
    foldedRanges.delete(start);
    paintBackdrop();
    syncGutter();
    markDirty();
    scheduleLint();
    scheduleMeanings();
    scheduleAdvisories();
  }

  function closePopover() {
    popover.hidden = true;
    popover.innerHTML = "";
    popover._source = null;
  }

  async function runDraftClaim(testId) {
    popover.innerHTML = '<p class="qf-desc">drafting from the real answer…</p>';
    try {
      const res = await fetch(withEnv(`/api/tests/${encodeURIComponent(testId)}/draft`), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await res.json();
      if (res.ok) {
        location.reload();
        return;
      }
      popover.innerHTML = `<p class="qf-desc">${escapeHtml(data.error || "could not draft")}</p>`;
    } catch {
      popover.innerHTML = '<p class="qf-desc">could not draft</p>';
    }
  }

  document.addEventListener("click", (e) => {
    const chev = e.target.closest(".fold-chev");
    if (chev && gutterIcons?.contains(chev)) {
      const start = Number(chev.dataset.foldStart);
      const width = Number(chev.dataset.foldWidth);
      const folding = !foldedRanges.has(start);
      if (folding) foldedRanges.set(start, { width, phrase: chev.dataset.phrase });
      else foldedRanges.delete(start);
      chev.textContent = folding ? "▸" : "▾";
      chev.title = folding ? "unfold" : "fold — view only";
      paintBackdrop();
      return;
    }
    const icon = e.target.closest(".qf-icon");
    if (icon && gutterIcons?.contains(icon)) {
      const kind = icon.dataset.qf;
      let desc = "";
      let actionLabel = "";
      if (kind === "draft") {
        desc = "Draft the claim this scenario made none of, from what a real run actually returns.";
        actionLabel = "draft it from the real answer";
      } else if (kind === "dup") {
        desc = escapeHtml(icon.dataset.hint);
        if (icon.dataset.target) actionLabel = "open it";
      } else if (kind === "phraseuse") {
        desc = escapeHtml(icon.dataset.hint);
        actionLabel = "use it — rewrite the file";
      }
      popover.innerHTML =
        `<p class="qf-desc">${desc}</p>` + (actionLabel ? `<button type="button" class="qf-action">${escapeHtml(actionLabel)}</button>` : "");
      const r = icon.getBoundingClientRect();
      popover.style.left = `${Math.min(r.left, window.innerWidth - 300)}px`;
      popover.style.top = `${r.bottom + 6}px`;
      popover.hidden = false;
      popover.dataset.for = kind;
      popover._source = icon;
      e.stopPropagation();
      return;
    }
    const action = e.target.closest(".qf-action");
    if (action && !popover.hidden) {
      const kind = popover.dataset.for;
      const source = popover._source;
      closePopover();
      if (kind === "draft") runDraftClaim(source.dataset.testId);
      else if (kind === "dup") location.href = withEnv(`/tests/${encodeURIComponent(source.dataset.target)}`);
      else if (kind === "phraseuse") {
        foldLines(Number(source.dataset.foldStart), Number(source.dataset.foldWidth), source.dataset.replacement);
      }
      return;
    }
    if (!popover.hidden && !e.target.closest(".qf-popover")) closePopover();
  });

  // --- Sticky scenario header while scrolling: which scenario the current scroll position sits
  // inside, pinned above the text. Only present in a file with more than one to distinguish. ------

  const boundsEl = document.getElementById("scenario-bounds");
  const scenarioBounds = boundsEl ? JSON.parse(boundsEl.textContent) : [];

  function updateStickyScenario() {
    if (!stickyScenario || !scenarioBounds.length) return;
    const topLine = Math.floor(input.scrollTop / LINE_HEIGHT) + 1;
    let current = null;
    for (const one of scenarioBounds) {
      if (one.start <= topLine) current = one;
    }
    if (!current || topLine <= current.start) {
      stickyScenario.hidden = true;
      return;
    }
    stickyScenario.innerHTML =
      `<div class="t">▸ ${escapeHtml(current.name)}</div>` +
      (current.description ? `<div class="d">${escapeHtml(current.description)}</div>` : "");
    stickyScenario.hidden = false;
  }

  function syncGutter() {
    if (!gutter) return;
    const count = input.value.split("\n").length;
    gutter.textContent = Array.from({ length: count }, (_, i) => i + 1).join("\n");
  }

  function syncScroll() {
    backdrop.scrollTop = input.scrollTop;
    backdrop.scrollLeft = input.scrollLeft;
    if (gutter) gutter.scrollTop = input.scrollTop;
    // `.gutter-icon`s are positioned absolutely, so they carry no scrollable height of their own
    // to drive a native `scrollTop` — moved by hand, in lock-step with the real scroll instead.
    if (gutterIcons) gutterIcons.style.transform = `translateY(${-input.scrollTop}px)`;
    updateStickyScenario();
    hideHovercard();
  }

  let dirty = false;
  function markDirty() {
    if (dirty) return;
    dirty = true;
    statusEl.textContent = "edited — not yet saved";
    statusEl.className = "status";
  }

  // --- Autocomplete -----------------------------------------------------------------------------

  let shownPhrases = [];
  let activeIndex = -1;
  // Set only by a deliberate close (Escape, blur, picking one) — never by `renderSuggest` finding
  // nothing yet. The reachable pool for a line often arrives after the flat vocabulary already
  // rendered nothing for it; that empty render must not stop the real one from ever showing.
  let dismissed = false;

  // The lines already written, read back as ATF's own real `offers()` would read them — so ranking
  // narrows to what is actually reachable from here (a `Then` only once something above has acted,
  // no more `Given`s once something has), not just word overlap over the whole suite's vocabulary.
  // Refetched only when the cursor moves to a different line, since that's the only time "what's
  // above" can have changed.
  let reachablePool = null;
  let reachableLine = -1;
  let reachableTimer = null;

  // What this scenario has said so far — never a line borrowed from another one. A file holds
  // more than one, and an earlier scenario's own `Given`/`When`/`Then` say nothing about what
  // *this* one has arranged: the scan stops at the nearest header above the line being written.
  function stepsAbove(lineIndex) {
    const lines = input.value.split("\n");
    let start = 0;
    for (let i = lineIndex - 1; i >= 0; i--) {
      if (/^\s*(Scenario:|Example:|Phrase:|Feature:|Rule:)/.test(lines[i])) {
        start = i + 1;
        break;
      }
    }
    let keyword = "";
    const out = [];
    for (const raw of lines.slice(start, lineIndex)) {
      const stripped = raw.trim();
      const spaceAt = stripped.indexOf(" ");
      if (!stripped || spaceAt === -1) continue;
      const word = stripped.slice(0, spaceAt).toLowerCase();
      const text = stripped.slice(spaceAt + 1);
      // `And`/`But` carry on whatever keyword came before them — the same rule `feature.py`'s own
      // parser reads a scenario by. Read as its own, literal word, "And the note..." arranges
      // nothing and acts nothing, which is not what continuing a `Given` means.
      if (word === "and" || word === "but") {
        if (keyword) out.push([keyword, text]);
      } else if (KEYWORDS.has(word)) {
        keyword = word;
        out.push([keyword, text]);
      }
    }
    return out;
  }

  function refreshReachable(lineIndex) {
    clearTimeout(reachableTimer);
    reachableTimer = setTimeout(async () => {
      try {
        const res = await fetch(withEnv("/api/composer"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ lines: stepsAbove(lineIndex) }),
        });
        if (!res.ok) return;
        const data = await res.json();
        reachablePool = data.offers.map((o) => ({ keyword: o.keyword, text: o.sentence, why: o.why, ghost: o.ghost }));
        reachableLine = lineIndex;
        const line = caretLine();
        if (line.index === lineIndex && !dismissed) renderSuggest(line.typed, line.index);
      } catch {
        // Silent — the flat, suite-wide vocabulary is still there to rank against.
      }
    }, 150);
  }

  function caretLine() {
    const pos = input.selectionStart;
    const before = input.value.slice(0, pos);
    const start = before.lastIndexOf("\n") + 1;
    const index = before.split("\n").length - 1;
    const stop = input.value.indexOf("\n", pos);
    const full = input.value.slice(start, stop === -1 ? input.value.length : stop);
    return { typed: before.slice(start), full, start, index };
  }

  function contentStart(full) {
    const stripped = full.replace(/^ +/, "");
    const indentLen = full.length - stripped.length;
    const spaceAt = stripped.indexOf(" ");
    const word = spaceAt > -1 ? stripped.slice(0, spaceAt) : stripped;
    return spaceAt > -1 && KEYWORDS.has(word.toLowerCase()) ? indentLen + spaceAt + 1 : indentLen;
  }

  function currentKeyword(typed) {
    const stripped = typed.replace(/^\s+/, "");
    const spaceAt = stripped.indexOf(" ");
    const word = spaceAt > -1 ? stripped.slice(0, spaceAt) : stripped;
    return KEYWORDS.has(word.toLowerCase()) ? word.toLowerCase() : "";
  }

  function candidateWords(p) {
    return (p.keyword + " " + p.text).toLowerCase().split(/\W+/).filter(Boolean);
  }

  // "a"/"an"/"the" are grammar, not content — every one of these sentences opens with one, so
  // they say nothing about which is meant.
  const ARTICLES = new Set(["a", "an", "the"]);

  // What belongs here comes from context, not from how the letters typed line up against a
  // pattern's own wording: `pool` is already exactly what `core.offers()` says makes sense from
  // what is arranged above, in the order it says makes sense — a `Given` for what nothing has
  // touched yet, a claim for what just got arranged, nothing about anything else. The one thing
  // still worth reading off the line itself is which keyword it is completing: a line started
  // `When` is never offered a `Then`. Once scoped to that, typed content only ever filters the
  // list — one word must still be a prefix of some word the candidate itself has — it never
  // scores or reorders it, so what shows first is always what the context says comes first.
  function rankPhrases(typed, lineIndex) {
    const usingReachable = reachableLine === lineIndex && !!reachablePool;
    const pool = usingReachable ? reachablePool : phrases;
    const keyword = currentKeyword(typed);
    const scoped = keyword ? pool.filter((p) => p.keyword.toLowerCase() === keyword) : pool;
    const rest = typed.slice(contentStart(typed));
    const words = rest.toLowerCase().split(/\W+/).filter((w) => w && !ARTICLES.has(w));
    const ranked = words.length
      ? scoped.filter((p) => {
          const cwords = candidateWords(p);
          return words.every((w) => cwords.some((cw) => cw.startsWith(w)));
        })
      : scoped;
    return { pool: scoped, usingReachable, ranked: ranked.slice(0, 8) };
  }

  function closeSuggest(byUser) {
    suggest.hidden = true;
    suggest.innerHTML = "";
    shownPhrases = [];
    activeIndex = -1;
    if (byUser) dismissed = true;
  }

  function paintSuggest() {
    suggest.querySelectorAll(".sug-item").forEach((el, i) => el.classList.toggle("on", i === activeIndex));
  }

  // The blank in a suggestion, previewed with a real, already-declared value — never an invented
  // one, and never what actually gets inserted; picking one still lands the caret in an empty `""`.
  function ghostPreview(text, ghost) {
    // Found on the raw text, not the escaped one — `escapeHtml` turns every `"` into `&quot;`
    // first, and the literal `""` this looks for would never be there to find again.
    const at = ghost ? text.indexOf('""') : -1;
    if (at === -1) return escapeHtml(text);
    return (
      escapeHtml(text.slice(0, at + 1)) +
      `<span class="ghost">${escapeHtml(ghost)}</span>` +
      escapeHtml(text.slice(at + 1))
    );
  }

  function renderSuggest(typed, lineIndex) {
    const { pool, usingReachable, ranked } = rankPhrases(typed, lineIndex);
    shownPhrases = ranked;
    if (!shownPhrases.length) {
      closeSuggest();
      return;
    }
    activeIndex = 0;
    const reach = usingReachable
      ? `<div class="sug-reach">${pool.length} make sense from what is written above</div>`
      : "";
    suggest.innerHTML =
      reach +
      shownPhrases
        .map(
          (p, i) =>
            `<button type="button" class="sug-item" data-index="${i}">` +
            `<span class="sug-text">${ghostPreview(p.text, p.ghost)}</span><span class="sug-why">${escapeHtml(p.why)}</span></button>`
        )
        .join("");
    paintSuggest();
    const top = 14 + lineIndex * LINE_HEIGHT - input.scrollTop + LINE_HEIGHT;
    suggest.style.top = `${Math.max(4, top)}px`;
    suggest.style.left = "68px";
    suggest.hidden = false;
  }

  // A picked phrase often carries a blank to fill — an empty `""` (a value ATF could not guess) or
  // a literal `{placeholder}` (a step's own capture, still unfilled). Land the caret there instead
  // of after the whole phrase, so picking one is one keystroke from typing the part that's actually
  // yours to say.
  function placeInBlank(insertedAt, text) {
    const quotes = text.indexOf('""');
    const brace = text.search(/\{[^}]*\}/);
    if (quotes > -1 && (brace === -1 || quotes < brace)) {
      const at = insertedAt + quotes + 1;
      input.setSelectionRange(at, at);
    } else if (brace > -1) {
      const token = text.slice(brace).match(/\{[^}]*\}/)[0];
      input.setSelectionRange(insertedAt + brace, insertedAt + brace + token.length);
    }
  }

  function pick(index) {
    const phrase = shownPhrases[index];
    if (!phrase) return;
    const line = caretLine();
    const from = line.start + contentStart(line.full);
    const to = Math.max(from, input.selectionStart);
    input.focus();
    input.setRangeText(phrase.text, from, to, "end");
    placeInBlank(from, phrase.text);
    closeSuggest(true);
    paintBackdrop();
    syncGutter();
    markDirty();
  }

  input.addEventListener("input", () => {
    paintBackdrop();
    syncGutter();
    markDirty();
    scheduleLint();
    scheduleMeanings();
    scheduleAdvisories();
    dismissed = false;
    const line = caretLine();
    if (line.index !== reachableLine) refreshReachable(line.index);
    renderSuggest(line.typed, line.index);
  });
  input.addEventListener("scroll", syncScroll);
  updateStickyScenario();

  // --- Indent: Enter matches the line just left (one level deeper after a Feature:/Scenario:/
  // Phrase: header, since that's the only thing in this grammar that opens a block — there are no
  // tables to indent into). Tab/Shift+Tab indent or dedent the current line, or every line the
  // selection touches, four spaces at a time — this suite's own convention. -----------------------

  const INDENT = "    ";

  function lineIndent(text) {
    return (text.match(/^[ \t]*/) || [""])[0];
  }

  function autoIndentNewline() {
    const line = caretLine();
    const stripped = line.full.replace(/^[ \t]*/, "");
    const indent = lineIndent(line.full);
    const opensBlock = /^(Feature:|Scenario:|Example:|Phrase:)/.test(stripped);
    const pos = input.selectionStart;
    input.setRangeText("\n" + indent + (opensBlock ? "  " : ""), pos, input.selectionEnd, "end");
    paintBackdrop();
    syncGutter();
    markDirty();
  }

  function indentSelection() {
    const text = input.value;
    const selStart = input.selectionStart;
    const selEnd = input.selectionEnd;
    if (selStart === selEnd) {
      input.setRangeText(INDENT, selStart, selEnd, "end");
      paintBackdrop();
      syncGutter();
      markDirty();
      return;
    }
    const startLine = text.lastIndexOf("\n", selStart - 1) + 1;
    const block = text.slice(startLine, selEnd);
    const indented = block
      .split("\n")
      .map((l) => INDENT + l)
      .join("\n");
    input.setRangeText(indented, startLine, selEnd, "select");
    input.setSelectionRange(selStart + INDENT.length, startLine + indented.length);
    paintBackdrop();
    syncGutter();
    markDirty();
  }

  function dedentSelection() {
    const text = input.value;
    const selStart = input.selectionStart;
    const selEnd = input.selectionEnd;
    const startLine = text.lastIndexOf("\n", selStart - 1) + 1;
    const effectiveEnd = Math.max(selEnd, startLine);
    const block = text.slice(startLine, effectiveEnd);
    let removedFirst = 0;
    const dedented = block
      .split("\n")
      .map((l, i) => {
        const strip = Math.min(INDENT.length, lineIndent(l).length);
        if (i === 0) removedFirst = strip;
        return l.slice(strip);
      })
      .join("\n");
    input.setRangeText(dedented, startLine, effectiveEnd, "select");
    input.setSelectionRange(Math.max(startLine, selStart - removedFirst), startLine + dedented.length);
    paintBackdrop();
    syncGutter();
    markDirty();
  }

  // Tab, with the caret sitting inside an open quote and a closing one right ahead, steps past it
  // instead of indenting — the same escape a paired auto-close would give you, without one.
  function smartTabPastQuote() {
    if (input.selectionStart !== input.selectionEnd) return false;
    const pos = input.selectionStart;
    if (input.value[pos] !== '"') return false;
    const lineStart = input.value.lastIndexOf("\n", pos - 1) + 1;
    const before = input.value.slice(lineStart, pos);
    if (((before.match(/"/g) || []).length % 2) !== 1) return false;
    input.setSelectionRange(pos + 1, pos + 1);
    return true;
  }

  input.addEventListener("keydown", (e) => {
    if (!suggest.hidden) {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        activeIndex = e.key === "ArrowDown" ? Math.min(activeIndex + 1, shownPhrases.length - 1) : Math.max(activeIndex - 1, 0);
        paintSuggest();
        return;
      } else if (e.key === "Enter" || e.key === "Tab") {
        if (activeIndex > -1) {
          e.preventDefault();
          pick(activeIndex);
          return;
        }
      } else if (e.key === "Escape") {
        closeSuggest(true);
        return;
      }
    }
    if (e.key === "Enter") {
      e.preventDefault();
      autoIndentNewline();
    } else if (e.key === "Tab") {
      e.preventDefault();
      if (e.shiftKey) dedentSelection();
      else if (!smartTabPastQuote()) indentSelection();
    }
  });
  suggest.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".sug-item");
    if (item) {
      e.preventDefault();
      pick(Number(item.dataset.index));
    }
  });
  input.addEventListener("blur", () => setTimeout(() => closeSuggest(true), 120));
  filenameInput?.addEventListener("input", markDirty);

  // --- Try it / Save -----------------------------------------------------------------------------

  tryBtn?.addEventListener("click", async () => {
    tryBtn.disabled = true;
    statusEl.textContent = "running…";
    statusEl.className = "status";
    try {
      const res = await fetch(withEnv("/api/composer/try"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: input.value }),
      });
      const data = await res.json();
      const passed = data.code === 0;
      statusEl.textContent = passed ? "passed, nothing saved" : (data.lines || []).join(" ") || "failed";
      statusEl.className = `status ${passed ? "ok" : "fail"}`;
    } catch {
      statusEl.textContent = "could not run";
      statusEl.className = "status fail";
    } finally {
      tryBtn.disabled = false;
    }
  });

  saveBtn?.addEventListener("click", async () => {
    saveBtn.disabled = true;
    try {
      if (input.dataset.mode === "new") {
        const name = filenameInput ? filenameInput.value.trim() : "";
        if (!name) {
          statusEl.textContent = "name the file first";
          statusEl.className = "status fail";
          return;
        }
        const res = await fetch(withEnv("/api/tests/save-new"), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name, text: input.value }),
        });
        const data = await res.json();
        if (res.ok && data.saved) {
          location.href = withEnv(`/tests/${encodeURIComponent(data.id)}`);
          return;
        }
        statusEl.textContent = data.error || "could not save";
        statusEl.className = "status fail";
      } else {
        const res = await fetch(withEnv(`/api/tests/${encodeURIComponent(input.dataset.testId)}/save`), {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text: input.value }),
        });
        const data = await res.json();
        if (res.ok && data.saved) {
          dirty = false;
          statusEl.textContent = "saved";
          statusEl.className = "status ok";
        } else {
          statusEl.textContent = data.error || "could not save";
          statusEl.className = "status fail";
        }
      }
    } catch {
      statusEl.textContent = "could not save";
      statusEl.className = "status fail";
    } finally {
      saveBtn.disabled = false;
    }
  });

  // A real run of this one scenario as it stands on disk — not the scratch dry run Try it does —
  // scoped by the id the page already opened, the same way the top-nav Run button runs one test.
  runScenarioBtn?.addEventListener("click", () => {
    if (RunControl) RunControl.start([runScenarioBtn.dataset.testId]);
  });

  // Land on the scenario that was actually clicked, in a file that can hold several — a plain
  // in-page jump, not a fetch, so it works before any script beyond this one has run.
  const scrollLine = Number(input.dataset.scrollToLine || 0);
  if (scrollLine > 1) {
    const target = Math.max(0, (scrollLine - 1) * LINE_HEIGHT - LINE_HEIGHT * 2);
    input.scrollTop = target;
    syncScroll();
  }
}

// --- Resources: what browse() finds that nothing declared matches — checked on request, never on
// page load, since browse() can be a real network call and a page that's always right is not worth
// one that's always slow. ----------------------------------------------------------------------------

function initUndeclared() {
  const btn = document.getElementById("check-undeclared");
  if (!btn) return;
  const out = document.getElementById("undeclared-result");
  btn.addEventListener("click", async () => {
    btn.disabled = true;
    btn.textContent = "checking…";
    try {
      const res = await fetch(withEnv(`/api/resources/${encodeURIComponent(btn.dataset.kind)}/undeclared`));
      const data = await res.json();
      if (!res.ok) {
        out.innerHTML = `<p class="undec-note">${escapeHtml(data.error || "could not check")}</p>`;
      } else if (!data.browsable) {
        out.innerHTML = `<p class="undec-note">${escapeHtml(data.why)}</p>`;
      } else if (!data.records.length) {
        out.innerHTML = '<p class="undec-note">nothing out there that isn\'t already declared.</p>';
      } else {
        out.innerHTML = data.records
          .map(
            (r) =>
              `<div class="undec-row"><span class="k">${escapeHtml(r.label)}</span>` +
              `<span class="f">${escapeHtml(Object.entries(r.fields).map(([k, v]) => `${k}: ${JSON.stringify(v)}`).join(", "))}</span></div>`
          )
          .join("");
      }
    } catch {
      out.innerHTML = '<p class="undec-note">could not check.</p>';
    } finally {
      btn.disabled = false;
      btn.textContent = "↺ Check what's out there but not declared";
    }
  });
}

// --- Resources: the scoped Provision button on a row. Provisioning itself is a synchronous call
// (plan.apply() — no job queue), so the pending state here is honest, not a fake wait: it really is
// running for as long as the button says "provisioning…". ------------------------------------------

function initProvision() {
  document.querySelectorAll(".provision-btn[data-make]").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const label = btn.textContent;
      btn.disabled = true;
      btn.classList.add("running");
      btn.textContent = "provisioning…";
      try {
        const res = await fetch(withEnv(`/api/make/${encodeURIComponent(btn.dataset.make)}`), { method: "POST" });
        if (!res.ok) throw new Error();
        btn.classList.remove("running");
        btn.classList.add("flash");
        btn.textContent = "✓ done";
        location.reload();
      } catch {
        btn.disabled = false;
        btn.classList.remove("running");
        btn.textContent = label;
      }
    });
  });
}

document.addEventListener("DOMContentLoaded", () => {
  initRunButton();
  initTestSearch();
  initEditorSurface();
  initUndeclared();
  initProvision();
});
