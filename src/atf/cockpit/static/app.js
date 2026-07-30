// The cockpit's own behaviour: the progress bar, the command palette, the combobox, the graph and
// the tooltips. Vanilla, loaded with `defer` beside htmx — no build step, no dependency.
const bar = document.getElementById("atf-progress");
document.body.addEventListener("htmx:beforeRequest", (e) => {
  if (e.detail.elt.closest("[data-quiet]")) return;
  bar.className = "active";
});
document.body.addEventListener("htmx:afterRequest", (e) => {
  if (e.detail.elt.closest("[data-quiet]")) return;
  bar.className = "done";
  setTimeout(() => (bar.className = ""), 260);
});

// An error must never replace what you were reading — it arrives beside it.
document.body.addEventListener("htmx:responseError", (e) => {
  e.preventDefault();
  const box = document.createElement("div");
  box.className = "toast bad";
  box.innerHTML = e.detail.xhr.responseText || "Something went wrong.";
  document.getElementById("toasts").appendChild(box);
  setTimeout(() => box.remove(), 9000);
});

function atfOpenSearch() {
  const dialog = document.getElementById("palette");
  if (!dialog.open) dialog.showModal();
  dialog.querySelector("input").focus();
}
document.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); atfOpenSearch(); }
});

// One item highlighted at a time, moved with the arrow keys and scrolled to. The palette and every
// combobox navigate the same way, so they move through it.
function atfRove(items, from, key) {
  if (!items.length) return -1;
  const next = key === "ArrowDown" ? Math.min(from + 1, items.length - 1) : Math.max(from - 1, 0);
  const at = next < 0 ? 0 : next;
  items.forEach((item) => item.classList.remove("on"));
  items[at].classList.add("on");
  items[at].scrollIntoView({ block: "nearest" });
  return at;
}

// Arrow keys and Enter through the results: a palette you have to click is not a palette.
document.getElementById("palette").addEventListener("keydown", (e) => {
  const hits = [...document.querySelectorAll("#palette-results a")];
  if (!hits.length) return;
  const at = hits.findIndex((a) => a.classList.contains("on"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    atfRove(hits, at, e.key);
  } else if (e.key === "Enter") {
    e.preventDefault();
    (hits[at] || hits[0]).click();
  }
});

function atfToggleTheme() {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const current = root.dataset.theme || (dark ? "dark" : "light");
  root.dataset.theme = current === "dark" ? "light" : "dark";
  localStorage.setItem("atf-theme", root.dataset.theme);
}
const storedTheme = localStorage.getItem("atf-theme");
if (storedTheme) document.documentElement.dataset.theme = storedTheme;

function atfToggleRail() {
  const collapsed = document.body.classList.toggle("rail-collapsed");
  localStorage.setItem("atf-rail", collapsed ? "collapsed" : "open");
}
if (localStorage.getItem("atf-rail") === "collapsed") document.body.classList.add("rail-collapsed");

function atfSwitchEnv(select) {
  const url = new URL(window.location.href);
  url.searchParams.set("env", select.value);
  window.location.href = url.toString();
}

if (!navigator.platform.toLowerCase().includes("mac")) {
  document.querySelectorAll("kbd[data-other]").forEach((k) => (k.textContent = k.dataset.other));
}

// Comboboxes. Delegated from the document so they keep working after every htmx swap, and
// driven by the hidden input so the server stays the only place draft state lives.
function atfComboOptions(combo) {
  return [...combo.querySelectorAll("li[role=option]")].filter((li) => !li.hidden);
}
function atfComboOpen(combo, open) {
  combo.dataset.open = open ? "true" : "false";
  combo.querySelector(".combo-input").setAttribute("aria-expanded", open ? "true" : "false");
  if (!open) combo.querySelectorAll("li.on").forEach((li) => li.classList.remove("on"));
}
function atfComboFilter(combo) {
  const query = combo.querySelector(".combo-input").value.trim().toLowerCase();
  let shown = 0;
  for (const li of combo.querySelectorAll("li[role=option]")) {
    const hit = !query || li.dataset.search.includes(query);
    li.hidden = !hit;
    if (hit) shown += 1;
  }
  // Group headings only earn their line when something under them survived the filter.
  for (const head of combo.querySelectorAll("li.opt-group")) {
    let any = false;
    for (let n = head.nextElementSibling; n && !n.classList.contains("opt-group"); n = n.nextElementSibling) {
      if (n.getAttribute("role") === "option" && !n.hidden) any = true;
    }
    head.hidden = !any;
  }
  combo.querySelector(".combo-empty").hidden = shown > 0;
}
function atfComboPick(combo, li) {
  const input = combo.querySelector(".combo-input");
  const hidden = combo.querySelector("[data-combo-value]");
  hidden.value = li.dataset.value;
  input.value = li.querySelector(".opt-label").textContent.trim();
  input.dataset.chosen = input.value;
  combo.classList.add("chosen");
  combo.querySelectorAll("li[aria-selected=true]").forEach((o) => o.setAttribute("aria-selected", "false"));
  li.setAttribute("aria-selected", "true");
  atfComboOpen(combo, false);
  // The form reacts exactly as it would to a <select>, so nothing downstream has to know.
  hidden.dispatchEvent(new Event("change", { bubbles: true }));
}
document.addEventListener("focusin", (e) => {
  const combo = e.target.closest?.("[data-combo]");
  document.querySelectorAll('[data-combo][data-open="true"]').forEach((other) => {
    if (other !== combo) atfComboOpen(other, false);
  });
  if (combo && e.target.classList.contains("combo-input")) {
    e.target.select();
    atfComboFilter(combo);
    atfComboOpen(combo, true);
  }
});
document.addEventListener("input", (e) => {
  const combo = e.target.closest?.("[data-combo]");
  if (!combo || !e.target.classList.contains("combo-input")) return;
  atfComboFilter(combo);
  atfComboOpen(combo, true);
});
document.addEventListener("mousedown", (e) => {
  const li = e.target.closest?.("[data-combo] li[role=option]");
  if (li) { e.preventDefault(); atfComboPick(li.closest("[data-combo]"), li); return; }
  if (!e.target.closest?.("[data-combo]")) {
    document.querySelectorAll('[data-combo][data-open="true"]').forEach((c) => atfComboOpen(c, false));
  }
});
document.addEventListener("keydown", (e) => {
  const combo = e.target.closest?.("[data-combo]");
  if (!combo || !e.target.classList.contains("combo-input")) return;
  const options = atfComboOptions(combo);
  const at = options.findIndex((li) => li.classList.contains("on"));
  if (e.key === "ArrowDown" || e.key === "ArrowUp") {
    e.preventDefault();
    atfComboOpen(combo, true);
    atfRove(options, at, e.key);
  } else if (e.key === "Enter") {
    const target = options[at] || (options.length === 1 ? options[0] : null);
    if (target) { e.preventDefault(); atfComboPick(combo, target); }
  } else if (e.key === "Escape") {
    // Abandoning a search restores what was actually chosen, never a half-typed string.
    e.target.value = e.target.dataset.chosen || "";
    atfComboFilter(combo);
    atfComboOpen(combo, false);
  }
});
document.addEventListener("focusout", (e) => {
  const combo = e.target.closest?.("[data-combo]");
  if (!combo || !e.target.classList.contains("combo-input")) return;
  setTimeout(() => {
    if (combo.contains(document.activeElement)) return;
    e.target.value = e.target.dataset.chosen || "";
    atfComboOpen(combo, false);
  }, 90);
});

// A lineage is only worth drawing if you can see all of it, so shrink it to fit rather than
// clipping and asking the reader to scroll a diagram whose point is the whole chain.
function atfFitGraph(target) {
  const scope = target && target.querySelector ? target : document;
  for (const graph of scope.querySelectorAll(".graph")) {
    const wrap = graph.closest(".graph-wrap");
    if (!wrap) continue;
    // Keep the height the server computed: every node is absolutely positioned, so a graph
    // that loses it collapses to its own padding.
    graph.dataset.height = graph.dataset.height || String(graph.offsetHeight);
    graph.style.transform = "";
    graph.style.height = `${graph.dataset.height}px`;
    const natural = graph.offsetWidth;
    const room = wrap.clientWidth;
    // Never enlarge, and never shrink so far that the labels stop being readable — past that
    // point scrolling a legible diagram beats reading an illegible one.
    const scale = Math.max(0.8, Math.min(1, room / natural));
    if (scale < 1) {
      graph.style.transformOrigin = "top left";
      graph.style.transform = `scale(${scale})`;
      graph.style.height = `${Number(graph.dataset.height) * scale}px`;
    }
    const focus = graph.querySelector(".gnode.focus");
    if (focus && natural * scale > room) {
      wrap.scrollLeft = (focus.offsetLeft + focus.offsetWidth / 2) * scale - room / 2;
    }
  }
}
document.addEventListener("DOMContentLoaded", () => atfFitGraph());
document.body.addEventListener("htmx:afterSwap", (e) => atfFitGraph(e.detail.target));
addEventListener("resize", () => atfFitGraph());

// A left list is deliberately never re-rendered — swapping it would throw away the filter and
// the scroll position. So the selection it shows is whatever the server last drew, and the
// client has to keep it in step with the pane beside it.
document.body.addEventListener("htmx:beforeRequest", (e) => {
  const link = e.detail.elt?.closest?.(".list > a");
  if (!link) return;
  for (const other of link.parentElement.querySelectorAll("[aria-current]")) {
    other.removeAttribute("aria-current");
  }
  link.setAttribute("aria-current", "true");
});

// Hover definitions are positioned against the viewport rather than their parent, because
// several of the places they are used — a left list, a scrolling table — clip their overflow,
// and a definition cut off at the edge of a sidebar explains nothing.
function atfPlaceTip(host) {
  const tip = host.querySelector(":scope > .tip");
  if (!tip) return;
  tip.style.position = "fixed";
  tip.style.bottom = "auto";
  tip.style.left = "0";
  tip.style.top = "0";
  const anchor = host.getBoundingClientRect();
  const box = tip.getBoundingClientRect();
  const left = Math.min(Math.max(8, anchor.left), innerWidth - box.width - 8);
  const above = anchor.top - box.height - 8;
  tip.style.left = `${left}px`;
  tip.style.top = `${above > 8 ? above : anchor.bottom + 8}px`;
}
for (const event of ["mouseover", "focusin"]) {
  document.addEventListener(event, (e) => {
    const host = e.target.closest?.(".term, .has-tip");
    if (host) atfPlaceTip(host);
  });
}
