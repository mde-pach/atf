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
  const rows = Array.from(document.querySelectorAll(".trow"));
  search.addEventListener("input", () => {
    const needle = search.value.trim().toLowerCase();
    rows.forEach((row) => {
      row.style.display = !needle || (row.dataset.search || "").includes(needle) ? "" : "none";
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
  const suggest = document.getElementById("suggest");
  const statusEl = document.getElementById("editor-status");
  const tryBtn = document.getElementById("try-btn");
  const saveBtn = document.getElementById("save-btn");
  const filenameInput = document.getElementById("filename-input");

  const kindWordsEl = document.getElementById("kind-words");
  const kindWords = new Set(kindWordsEl ? JSON.parse(kindWordsEl.textContent) : []);
  const phraseListEl = document.getElementById("phrase-list");
  const phrases = phraseListEl ? JSON.parse(phraseListEl.textContent) : [];
  const highlightHtml = backdrop.querySelector(".line-highlight")?.outerHTML || "";

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

  function renderBackdrop(text) {
    return text
      .split("\n")
      .map((line) => {
        const stripped = line.replace(/^ +/, "");
        const indent = line.slice(0, line.length - stripped.length);
        const spaceAt = stripped.indexOf(" ");
        const word = spaceAt > -1 ? stripped.slice(0, spaceAt) : "";
        const body =
          spaceAt > -1 && KEYWORDS.has(word.toLowerCase())
            ? `<span class="tok-kw">${escapeHtml(word)}</span> ${highlightLine(stripped.slice(spaceAt + 1))}`
            : highlightLine(stripped);
        return indent + body;
      })
      .join("\n");
  }

  function paintBackdrop() {
    backdrop.innerHTML = highlightHtml + renderBackdrop(input.value);
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

  // The lines already written, read back as ATF's own real `offers()` would read them — so ranking
  // narrows to what is actually reachable from here (a `Then` only once something above has acted,
  // no more `Given`s once something has), not just word overlap over the whole suite's vocabulary.
  // Refetched only when the cursor moves to a different line, since that's the only time "what's
  // above" can have changed.
  let reachablePool = null;
  let reachableLine = -1;
  let reachableTimer = null;

  function stepsAbove(lineIndex) {
    return input.value
      .split("\n")
      .slice(0, lineIndex)
      .map((raw) => raw.trim())
      .filter(Boolean)
      .map((stripped) => {
        const spaceAt = stripped.indexOf(" ");
        if (spaceAt === -1) return null;
        const word = stripped.slice(0, spaceAt).toLowerCase();
        return KEYWORDS.has(word) ? [word, stripped.slice(spaceAt + 1)] : null;
      })
      .filter(Boolean);
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
        reachablePool = data.offers.map((o) => ({ keyword: o.keyword, text: o.sentence, why: o.why }));
        reachableLine = lineIndex;
        const line = caretLine();
        if (line.index === lineIndex && !suggest.hidden) renderSuggest(line.typed, line.index);
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

  function rankPhrases(typed, lineIndex) {
    const pool = reachableLine === lineIndex && reachablePool ? reachablePool : phrases;
    const words = new Set(typed.toLowerCase().split(/\W+/).filter(Boolean));
    if (!words.size) return { pool, ranked: [] };
    const ranked = pool
      .map((p) => ({
        p,
        overlap: (p.keyword + " " + p.text).toLowerCase().split(/\W+/).filter((w) => words.has(w)).length,
      }))
      .filter((r) => r.overlap > 0)
      .sort((a, b) => b.overlap - a.overlap)
      .slice(0, 5)
      .map((r) => r.p);
    return { pool, ranked };
  }

  function closeSuggest() {
    suggest.hidden = true;
    suggest.innerHTML = "";
    shownPhrases = [];
    activeIndex = -1;
  }

  function paintSuggest() {
    suggest.querySelectorAll(".sug-item").forEach((el, i) => el.classList.toggle("on", i === activeIndex));
  }

  function renderSuggest(typed, lineIndex) {
    const { pool, ranked } = rankPhrases(typed, lineIndex);
    shownPhrases = ranked;
    if (!shownPhrases.length) {
      closeSuggest();
      return;
    }
    activeIndex = 0;
    const reach =
      pool !== phrases && pool.length < phrases.length
        ? `<div class="sug-reach">${pool.length} reachable from here — the rest need something above this line first</div>`
        : "";
    suggest.innerHTML =
      `<div class="sug-hint">closest to "${escapeHtml(typed.trim())}"</div>${reach}` +
      shownPhrases
        .map(
          (p, i) =>
            `<button type="button" class="sug-item" data-index="${i}">` +
            `<span class="sug-text">${escapeHtml(p.text)}</span><span class="sug-why">${escapeHtml(p.why)}</span></button>`
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
    closeSuggest();
    paintBackdrop();
    syncGutter();
    markDirty();
  }

  input.addEventListener("input", () => {
    paintBackdrop();
    syncGutter();
    markDirty();
    const line = caretLine();
    if (line.index !== reachableLine) refreshReachable(line.index);
    renderSuggest(line.typed, line.index);
  });
  input.addEventListener("scroll", syncScroll);
  input.addEventListener("keydown", (e) => {
    if (suggest.hidden) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = e.key === "ArrowDown" ? Math.min(activeIndex + 1, shownPhrases.length - 1) : Math.max(activeIndex - 1, 0);
      paintSuggest();
    } else if (e.key === "Enter" || e.key === "Tab") {
      if (activeIndex > -1) {
        e.preventDefault();
        pick(activeIndex);
      }
    } else if (e.key === "Escape") {
      closeSuggest();
    }
  });
  suggest.addEventListener("mousedown", (e) => {
    const item = e.target.closest(".sug-item");
    if (item) {
      e.preventDefault();
      pick(Number(item.dataset.index));
    }
  });
  input.addEventListener("blur", () => setTimeout(closeSuggest, 120));
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
