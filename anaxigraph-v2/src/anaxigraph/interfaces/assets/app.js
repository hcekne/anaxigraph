"use strict";

const $ = (selector) => document.querySelector(selector);
const state = { sort: "path", descending: false, offset: 0, limit: 25, selected: null, request: null };
let moduleGeneration = 0;
let entityGeneration = 0;

function notice(message, error = false) {
  const element = $("#notice");
  element.hidden = !message;
  element.classList.toggle("error", error);
  element.textContent = message;
}

async function api(path, body, timeout = 20000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method: body === undefined ? "GET" : "POST",
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: controller.signal,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data));
    }
    return data;
  } catch (error) {
    if (error.name === "AbortError") throw new Error("The request timed out. Refresh to check the saved state.");
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function action(button, operation) {
  if (button.disabled) return;
  button.disabled = true;
  const label = button.textContent;
  button.textContent = "Working…";
  notice("");
  try {
    await operation();
  } catch (error) {
    notice(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}

function formatJSON(value) { return JSON.stringify(value, null, 2); }
function lines(value) { return value.split("\n").map((line) => line.trim()).filter(Boolean); }
function title(node) {
  return node.kind !== "module" && node.path ? `${node.name} · ${node.path}` : (node.path || node.name || node.id);
}
function short(value, length = 37) { return value.length > length ? `…${value.slice(-length + 1)}` : value; }
function bytes(value) {
  if (!Number.isFinite(value)) return "—";
  return value < 1048576 ? `${(value / 1024).toFixed(0)} KB` : `${(value / 1048576).toFixed(1)} MB`;
}

function switchPage(name) {
  document.querySelectorAll(".page").forEach((page) => { page.hidden = page.id !== `page-${name}`; });
  document.querySelectorAll("[data-page]").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === name);
    if (button.dataset.page === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
}

function renderCheckout(snapshot, root) {
  $("#repository-name").textContent = String(root).split("/").filter(Boolean).pop() || "Your codebase";
  $("#checkout").textContent = snapshot
    ? `${root} · ${(snapshot.revision || "No Git revision").slice(0, 12)}${snapshot.dirty ? " · working changes" : ""}`
    : `${root} · build the first structural map to begin`;
  $("#snapshot-state").textContent = snapshot ? `Snapshot ${snapshot.id.slice(0, 12)}` : "No saved snapshot";
}

function renderCoverage(data) {
  const diagnostics = data.diagnostics || [];
  $("#map-state").textContent = data.snapshot ? (diagnostics.length ? "Partial coverage" : "Available") : "Not mapped";
  $("#coverage-summary").textContent = `${data.coverage || "Python/PYI syntax and scoped references"}. Other languages are not parsed in this milestone. ${data.unresolved_relationships || 0} ambiguous or unresolved relationships.`;
  $("#coverage-diagnostics").hidden = !diagnostics.length;
  $("#diagnostic-count").textContent = `${diagnostics.length} reported analysis diagnostics — inspect coverage gaps`;
  $("#diagnostic-items").replaceChildren(...diagnostics.map((item) => textElement("li", item)));
}

function renderMetrics(data) {
  $("#entity-count").textContent = `${data.modules || 0} / ${data.symbols || 0}`;
  const annotations = data.annotations || {};
  $("#annotation-count").textContent = `${annotations.current || 0} / ${data.modules || 0}`;
  $("#annotation-state").textContent = `${annotations.stale || 0} stale · ${annotations.missing || 0} awaiting agent annotation`;
  const storage = data.storage || {};
  $("#storage-size").textContent = bytes(storage.bytes ?? storage.database_bytes ?? storage.size_bytes);
}

async function refreshStatus() {
  const data = await api("/api/status");
  renderCheckout(data.snapshot, data.snapshot?.root || data.root || data.repository || "Checkout");
  renderCoverage(data);
  renderMetrics(data);
  return data;
}

function moduleRow(node) {
  const row = document.createElement("tr");
  row.classList.toggle("selected", node.id === state.selected);
  const moduleCell = document.createElement("td");
  const button = textElement("button", title(node), "module-link");
  button.addEventListener("click", () => selectEntity(node.id).catch((error) => notice(error.message, true)));
  moduleCell.append(button);
  const overview = (node.data?.annotation?.overview || "Purpose not annotated yet")
    + (node.data?.annotation_status === "stale" ? " · stale annotation" : "");
  moduleCell.append(textElement("div", overview, "module-overview"));
  row.append(moduleCell);
  const parseFailed = node.data?.parse_status && node.data.parse_status !== "parsed";
  for (const value of [node.data?.loc ?? "Unknown", parseFailed ? "Unknown" : (node.data?.function_count ?? "Unknown")]) {
    row.append(textElement("td", String(value)));
  }
  return row;
}

function renderModulePage(data) {
  const items = data.items || [];
  document.querySelectorAll("[data-sort]").forEach((button) => {
    button.closest("th").setAttribute("aria-sort", button.dataset.sort === state.sort
      ? (state.descending ? "descending" : "ascending") : "none");
  });
  $("#module-total").textContent = `${data.total || 0} modules`;
  $("#module-rows").replaceChildren(...items.map(moduleRow));
  $("#module-empty").hidden = items.length > 0;
  $("#page-label").textContent = `${items.length ? state.offset + 1 : 0}–${state.offset + items.length} of ${data.total || 0}`;
  $("#previous").disabled = state.offset === 0;
  $("#next").disabled = state.offset + items.length >= (data.total || 0);
}

async function refreshModules() {
  const generation = ++moduleGeneration;
  const query = new URLSearchParams({ sort: state.sort, descending: state.descending, limit: state.limit, offset: state.offset });
  const data = await api(`/api/modules?${query}`);
  if (generation === moduleGeneration) renderModulePage(data);
}

function addLinkGroup(name, edges, direction, nodes) {
  const section = document.createElement("section");
  section.className = "link-group";
  const heading = document.createElement("h3");
  heading.textContent = `${name} (${edges.length})`;
  section.append(heading);
  for (const edge of edges.slice(0, 12)) {
    const id = direction === "incoming" ? edge.source : edge.target;
    const button = document.createElement("button");
    button.textContent = `${edge.kind} · ${short(nodes.get(id)?.name || id, 55)}${edge.resolution !== "resolved" ? ` · ${edge.resolution}` : ""}`;
    button.addEventListener("click", () => selectEntity(id).catch((error) => notice(error.message, true)));
    section.append(button);
  }
  $("#entity-links").append(section);
}

async function selectEntity(id) {
  const generation = ++entityGeneration;
  const result = await api(`/api/entity?${new URLSearchParams({ entity_id: id, limit: 20 })}`);
  if (generation !== entityGeneration) return;
  const entity = result.entity;
  state.selected = entity.id;
  const annotation = entity.data?.annotation || {};
  $("#entity-title").textContent = title(entity);
  $("#entity-overview").textContent = annotation.overview || entity.data?.overview || "No semantic annotation yet. Source facts are available below.";
  $("#entity-detail").textContent = annotation.detail || "";
  $("#entity-facts").replaceChildren();
  for (const value of [entity.kind, entity.data?.loc === undefined ? null : `${entity.data.loc} lines`, `line ${entity.line || 1}`, entity.data?.annotation_status, entity.data?.parse_status].filter(Boolean)) {
    const chip = document.createElement("span");
    chip.textContent = value;
    $("#entity-facts").append(chip);
  }
  $("#entity-json").textContent = formatJSON(result);
  const nodes = new Map((result.neighbors || []).map((node) => [node.id, node]));
  nodes.set(entity.id, entity);
  $("#entity-links").replaceChildren();
  addLinkGroup("Incoming", result.incoming || [], "incoming", nodes);
  addLinkGroup("Outgoing", result.outgoing || [], "outgoing", nodes);
  drawGraph(entity, result.incoming || [], result.outgoing || [], nodes);
  await refreshModules();
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) element.setAttribute(key, value);
  return element;
}

function drawGraph(entity, incoming, outgoing, nodes) {
  const left = [...new Map(incoming.filter((edge) => edge.source !== entity.id).map((edge) => [edge.source, edge])).values()].slice(0, 9);
  const right = [...new Map(outgoing.filter((edge) => edge.target !== entity.id).map((edge) => [edge.target, edge])).values()].slice(0, 9);
  const height = Math.max(260, Math.max(left.length, right.length) * 54 + 70);
  const center = { x: 440, y: height / 2 };
  const svg = svgElement("svg", { viewBox: `0 0 880 ${height}`, role: "img", "aria-label": `Connections around ${title(entity)}` });
  const defs = svgElement("defs");
  const marker = svgElement("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto-start-reverse" });
  marker.append(svgElement("path", { d: "M 0 0 L 10 5 L 0 10 z", fill: "#648273" }));
  defs.append(marker);
  svg.append(defs);
  function addNode(id, point, central = false) {
    const node = nodes.get(id);
    const group = svgElement("g", { class: `graph-node${central ? " center" : ""}`, transform: `translate(${point.x - 116},${point.y - 18})`, tabindex: "0", role: "button", "aria-label": node?.name || id });
    group.append(svgElement("rect", { width: 232, height: 36 }));
    const label = svgElement("text", { x: 116, y: 23, "text-anchor": "middle" });
    label.textContent = short(node?.name || id, 29);
    const full = svgElement("title");
    full.textContent = node ? title(node) : id;
    group.append(label, full);
    const activate = () => selectEntity(id).catch((error) => notice(error.message, true));
    group.addEventListener("click", activate);
    group.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); activate(); } });
    svg.append(group);
  }
  for (const [edges, isLeft] of [[left, true], [right, false]]) {
    edges.forEach((edge, index) => {
      const point = { x: isLeft ? 135 : 745, y: height / 2 + (index - (edges.length - 1) / 2) * 54 };
      const start = isLeft ? { x: point.x + 116, y: point.y } : { x: center.x + 116, y: center.y };
      const end = isLeft ? { x: center.x - 116, y: center.y } : { x: point.x - 116, y: point.y };
      const path = svgElement("path", { d: `M ${start.x} ${start.y} C ${(start.x + end.x) / 2} ${start.y}, ${(start.x + end.x) / 2} ${end.y}, ${end.x} ${end.y}`, class: `graph-edge ${edge.resolution !== "resolved" ? "uncertain" : ""}`, "marker-end": "url(#arrow)" });
      const label = svgElement("title");
      label.textContent = `${edge.kind} · ${edge.resolution}`;
      path.append(label);
      svg.append(path);
      addNode(isLeft ? edge.source : edge.target, point);
    });
  }
  addNode(entity.id, center, true);
  $("#graph").classList.remove("graph-empty");
  $("#graph").replaceChildren(svg);
}

async function requestAnalysis(kind) {
  const scope = lines($("#analysis-scope").value);
  const packet = await api("/api/analysis/request", { kind, scope: scope.length ? scope : null });
  state.request = packet;
  $("#analysis-title").textContent = { annotate: "Module annotation", patterns: "Pattern discovery", "fresh-eyes": "Blind Fresh Eyes design" }[kind];
  $("#analysis-state").textContent = "Awaiting agent result";
  $("#analysis-packet").textContent = formatJSON(packet);
  $("#blind-note").hidden = kind !== "fresh-eyes";
  $("#submit-analysis").disabled = false;
  $("#copy-task").disabled = false;
  $("#analysis-result").value = "";
  switchPage("workflows");
  notice("Task prepared. Give its packet and response schema to your agent.");
}

async function refreshReviews() {
  const data = await api("/api/reviews");
  const items = data.items || data.reviews || [];
  $("#saved-reviews").replaceChildren();
  $("#saved-reviews").classList.toggle("empty", !items.length);
  if (!items.length) $("#saved-reviews").textContent = "No saved reviews yet.";
  for (const item of items) {
    const section = document.createElement("details");
    section.className = "review-card";
    const summary = document.createElement("summary");
    summary.textContent = `${item.kind || "Review"} · ${item.status || "saved"} · ${item.producer || "producer unspecified"}`;
    const content = document.createElement("div");
    content.className = "review-content";
    content.textContent = item.summary || "Expand to load the full saved review.";
    section.append(summary, content);
    let loaded = false;
    let loading = false;
    section.addEventListener("toggle", async () => {
      if (!section.open || loaded || loading) return;
      loading = true;
      content.textContent = "Loading saved review…";
      try {
        const id = item.id || item.review_id;
        const detail = await api(`/api/entity?${new URLSearchParams({ entity_id: `review:${id}` })}`);
        renderReview(content, detail.entity.data);
        loaded = true;
      } catch (error) {
        content.textContent = `${error.message}. Close and expand this review to retry.`;
      } finally {
        loading = false;
      }
    });
    $("#saved-reviews").append(section);
  }
}

function textElement(tag, text, className) {
  const element = document.createElement(tag);
  element.textContent = text;
  if (className) element.className = className;
  return element;
}

function reviewTradeoffs(parent, label, items) {
  parent.append(textElement("h4", label));
  const list = document.createElement("ul");
  for (const value of items || []) list.append(textElement("li", value));
  parent.append(list);
}

function alternativeCard(alternative, index) {
  const card = document.createElement("article");
  card.className = "design-alternative";
  card.append(textElement("h3", `${index + 1}. ${alternative.name}`));
  card.append(textElement("p", alternative.design));
  reviewTradeoffs(card, "Pros", alternative.pros);
  reviewTradeoffs(card, "Cons", alternative.cons);
  card.append(textElement("p", `Requirements: ${(alternative.requirements || []).join(", ")}`, "section-note"));
  card.append(textElement("h4", "Architecture diagram (Mermaid)"));
  card.append(textElement("pre", alternative.diagram, "design-diagram"));
  return card;
}

function patternCard(evaluation) {
  const card = document.createElement("details");
  card.className = "pattern-evaluation";
  const rating = evaluation.opportunity === null ? "insufficient evidence" : `opportunity ${evaluation.opportunity}/3`;
  card.append(textElement("summary", `${evaluation.pattern_id} · ${rating} · ${evaluation.module_id}`));
  if (evaluation.current_fit) card.append(textElement("p", `Current fit: ${evaluation.current_fit}`));
  if (evaluation.proposed_change) card.append(textElement("p", `Proposed change: ${evaluation.proposed_change}`));
  reviewTradeoffs(card, "Pros", evaluation.pros);
  reviewTradeoffs(card, "Cons", evaluation.cons);
  card.append(textElement("p", `Simpler alternative: ${evaluation.alternative}`));
  card.append(textElement("p", `Evidence: ${(evaluation.evidence || []).map((item) => `${item.path}:${item.line}`).join(", ") || "No source evidence supplied"}`, "section-note"));
  return card;
}

function renderPatternPages(parent, values) {
  const evaluations = [...values].sort((a, b) => (b.opportunity ?? -1) - (a.opportunity ?? -1));
  const count = textElement("p", `${evaluations.length} saved module × pattern evaluations`, "section-note");
  const list = document.createElement("div");
  let shown = 0;
  const more = textElement("button", "Show next 25 evaluations", "secondary");
  function appendPage() {
    list.append(...evaluations.slice(shown, shown + 25).map(patternCard));
    shown = Math.min(shown + 25, evaluations.length);
    count.textContent = `${shown} of ${evaluations.length} saved module × pattern evaluations · highest opportunities first`;
    more.hidden = shown >= evaluations.length;
  }
  more.addEventListener("click", appendPage);
  parent.append(count, list, more);
  appendPage();
}

function renderReview(parent, record) {
  parent.replaceChildren();
  const result = record.result?.result || record.result || {};
  parent.append(textElement("p", `${record.status || "saved"} · ${result.producer || "producer unspecified"} · snapshot ${record.snapshot_id}`, "section-note"));
  if (record.status !== "current") {
    parent.append(textElement("p", record.freshness_reason || "This review belongs to earlier or unknown analysis inputs and has not been refreshed.", "review-stale"));
  }
  if (Array.isArray(result.alternatives)) parent.append(...result.alternatives.map(alternativeCard));
  else if (Array.isArray(result.evaluations)) renderPatternPages(parent, result.evaluations);
  const raw = document.createElement("details");
  raw.append(textElement("summary", "Full saved record and provenance"));
  raw.append(textElement("pre", formatJSON(record)));
  parent.append(raw);
}

async function refresh() {
  const status = await refreshStatus();
  if (status.snapshot) {
    await refreshModules();
  } else {
    $("#module-rows").replaceChildren();
    $("#module-empty").hidden = false;
    $("#module-total").textContent = "0 modules";
    $("#page-label").textContent = "0–0";
    $("#previous").disabled = true;
    $("#next").disabled = true;
  }
}

document.querySelectorAll("[data-page]").forEach((button) => button.addEventListener("click", () => switchPage(button.dataset.page)));
document.querySelectorAll("[data-kind]").forEach((button) => button.addEventListener("click", () => action(button, () => requestAnalysis(button.dataset.kind))));
document.querySelectorAll("[data-sort]").forEach((button) => button.addEventListener("click", () => {
  state.descending = state.sort === button.dataset.sort ? !state.descending : button.dataset.sort !== "path";
  state.sort = button.dataset.sort;
  state.offset = 0;
  action(button, refreshModules);
}));
$("#refresh").addEventListener("click", () => action($("#refresh"), refresh));
$("#scan").addEventListener("click", () => action($("#scan"), async () => {
  await api("/api/scan", {}, 120000);
  state.offset = 0;
  await refresh();
  notice("Structural map saved. Semantic annotations and architectural reviews have separate readiness.");
}));
$("#previous").addEventListener("click", () => { state.offset = Math.max(0, state.offset - state.limit); refreshModules().catch((error) => notice(error.message, true)); });
$("#next").addEventListener("click", () => { state.offset += state.limit; refreshModules().catch((error) => notice(error.message, true)); });
$("#copy-task").addEventListener("click", () => action($("#copy-task"), async () => {
  await navigator.clipboard.writeText(formatJSON(state.request));
  notice("Task copied.");
}));
$("#submit-analysis").addEventListener("click", () => action($("#submit-analysis"), async () => {
  if (!state.request) throw new Error("Prepare a task first.");
  const result = JSON.parse($("#analysis-result").value);
  await api("/api/analysis/submit", { request_id: state.request.request_id, result });
  $("#analysis-state").textContent = "Validated and saved";
  await Promise.all([refresh(), refreshReviews()]);
  notice("Agent result validated and saved for its requested snapshot.");
}));
$("#load-reviews").addEventListener("click", () => action($("#load-reviews"), refreshReviews));
$("#prepare-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => { $("#change-brief").textContent = formatJSON(await api("/api/prepare", { task: $("#change-task").value })); });
});
$("#assess-form").addEventListener("submit", (event) => {
  event.preventDefault();
  action(event.submitter, async () => {
    if (!$("#change-task").value.trim()) throw new Error("Describe your intended change first.");
    $("#change-validation").textContent = formatJSON(await api("/api/assess", { task: $("#change-task").value, files: lines($("#planned-files").value) }));
  });
});
$("#validate-change").addEventListener("click", () => action($("#validate-change"), async () => {
  const receipts = $("#receipts").value.trim() ? JSON.parse($("#receipts").value) : null;
  $("#change-validation").textContent = formatJSON(await api("/api/validate", { receipts }));
}));
refresh().catch((error) => notice(error.message, true));
