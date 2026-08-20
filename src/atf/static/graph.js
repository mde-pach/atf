// atf edit — the graph screen. Cytoscape draws the canvas; the sidebar's node list and node detail
// are real markup this file swaps, driven by the same /api/graph endpoints the page itself uses.
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const container = document.getElementById("cy");
  if (!container || typeof cytoscape === "undefined") return;

  const nodes = JSON.parse(document.getElementById("graph-data").textContent);
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  const env = new URLSearchParams(location.search).get("env") || "";
  const withEnv = (path) => (env ? `${path}${path.includes("?") ? "&" : "?"}env=${encodeURIComponent(env)}` : path);
  const escapeHtml = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

  // Two dimensions, same two the sidebar's legend shows: the ring is how long it lives, the fill is
  // whether it is there right now. Neither is invented for the canvas — both are `core.state_of`'s
  // and `lives.of`'s own vocabulary.
  const livesColor = { forever: "#8891a0", "the run": "#a68fe0", "the test": "#e2935f" };
  const stateFill = { present: "#16261f", absent: "#23262c", unreachable: "#2e1e1a" };

  const elements = [];
  nodes.forEach((n) => {
    elements.push({ data: { id: n.id, label: `${n.label}\n${n.kind}`, lives: n.lives, state: n.state } });
    (n.needs || []).forEach((parent) => {
      if (byId[parent]) elements.push({ data: { id: `${parent}->${n.id}`, source: parent, target: n.id } });
    });
  });

  const cy = cytoscape({
    container,
    elements,
    style: [
      {
        selector: "node",
        style: {
          shape: "round-rectangle",
          "background-color": (el) => stateFill[el.data("state")] || "#1b1e24",
          "border-width": 2,
          "border-color": (el) => livesColor[el.data("lives")] || "#3a3e47",
          label: "data(label)",
          color: "#e7e9ec",
          "font-family": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif",
          "font-size": 12,
          "text-valign": "center",
          "text-halign": "center",
          "text-wrap": "wrap",
          "text-max-width": "150px",
          "line-height": 1.5,
          width: "label",
          height: "label",
          padding: "16px",
          "corner-radius": "8",
        },
      },
      { selector: "node:active", style: { "overlay-opacity": 0 } },
      { selector: "node.selected", style: { "border-color": "#6f93ff", "border-width": 3 } },
      {
        selector: "edge",
        style: {
          "curve-style": "bezier",
          "target-arrow-shape": "triangle",
          "target-distance-from-node": 4,
          "source-distance-from-node": 4,
          "line-color": "#343841",
          "target-arrow-color": "#343841",
          width: 1.5,
          "arrow-scale": 0.85,
        },
      },
    ],
    layout: {
      name: "breadthfirst",
      directed: true,
      spacingFactor: 1.9,
      nodeDimensionsIncludeLabels: true,
      animate: false,
      padding: 40,
    },
    wheelSensitivity: 0.25,
    minZoom: 0.15,
    maxZoom: 2.5,
  });
  container.style.cursor = "grab";
  cy.on("grab", () => (container.style.cursor = "grabbing"));
  cy.on("free", () => (container.style.cursor = "grab"));
  cy.on("mouseover", "node", () => (container.style.cursor = "pointer"));
  cy.on("mouseout", "node", () => (container.style.cursor = "grab"));

  function selectNode(id) {
    cy.nodes().removeClass("selected");
    const el = cy.$id(id);
    if (el.nonempty()) el.addClass("selected");
  }

  async function openNode(id, push) {
    const res = await fetch(withEnv(`/api/graph/${encodeURIComponent(id)}`));
    if (!res.ok) return;
    const detail = await res.json();
    renderDetail(detail);
    selectNode(id);
    if (push) history.pushState({}, "", withEnv(`/graph/${encodeURIComponent(id)}`));
  }

  function renderDetail(detail) {
    const body = document.getElementById("graph-sidebody");
    const edges = (title, list) =>
      `<div class="field"><div class="k">${escapeHtml(title)}</div><div class="chips">` +
      (list.length
        ? list.map((n) => `<a class="chip" href="${withEnv(`/graph/${encodeURIComponent(n.id)}`)}" data-nav="${escapeHtml(n.id)}">${escapeHtml(n.label)}</a>`).join("")
        : '<span class="v" style="color:var(--ink-dim)">nothing</span>') +
      "</div></div>";
    body.innerHTML =
      `<div class="drawerhead"><div class="drawertitle">${escapeHtml(detail.label)}</div></div>` +
      `<div class="drawersub">${escapeHtml(detail.kind)}${detail.sentence ? " · " + escapeHtml(detail.sentence) : ""}</div>` +
      edges("needs", detail.needs) +
      edges("what breaks if this does", detail.needed_by) +
      (detail.kind === "resource"
        ? `<a class="runfor" href="${withEnv(`/tests?resource=${encodeURIComponent(detail.id)}`)}">▶ run tests using ${escapeHtml(detail.id)}</a>`
        : "");
    body.querySelectorAll("[data-nav]").forEach((a) =>
      a.addEventListener("click", (evt) => {
        evt.preventDefault();
        openNode(a.dataset.nav, true);
      })
    );
  }

  cy.on("tap", "node", (evt) => openNode(evt.target.id(), true));

  document.getElementById("zoom-in")?.addEventListener("click", () => cy.zoom({ level: cy.zoom() * 1.25, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } }));
  document.getElementById("zoom-out")?.addEventListener("click", () => cy.zoom({ level: cy.zoom() / 1.25, renderedPosition: { x: container.clientWidth / 2, y: container.clientHeight / 2 } }));
  document.getElementById("zoom-fit")?.addEventListener("click", () => cy.fit(undefined, 40));

  const preselect = container.dataset.selected;
  if (preselect) {
    selectNode(preselect);
    cy.ready(() => {
      const el = cy.$id(preselect);
      if (el.nonempty()) cy.center(el);
    });
  }
});
