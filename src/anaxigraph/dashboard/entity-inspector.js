import { escapeAttr, escapeHtml, format, humanize, state } from "/assets/dashboard-core.js";

export function entityButton(node, label = "") {
  const id = typeof node === "string" ? node : node.id;
  const title = label || node.label || node.name || node.overview || id;
  return `<button type="button" class="entity-link" data-entity-id="${escapeAttr(id)}">${escapeHtml(title)}</button>`;
}

export function entityInspector(value) {
  const node = value.node || value.entity || {};
  const properties = node.properties || {};
  const connections = value.connections || {};
  return `<article class="entity-inspector" data-entity-inspector="${escapeAttr(node.id)}">
    ${entityHeader(node, value.context)}${entityDescription(node)}${metricsMarkup(node.metrics || {})}${historyWindow(value.context)}${structuralNotice(value.context)}${unresolvedCalls(properties)}
    <div class="module-detail-actions"><button class="secondary-button" data-entity-focus="${escapeAttr(node.id)}">Focus in graph</button><button class="secondary-button" data-entity-guide="${escapeAttr(node.id)}">Guide coding agent</button></div>
    ${entityList("Functions", value.functions, node.id)}
    ${entityList("Interfaces", value.interfaces, node.id)}
    ${contractList(value.contracts || properties.contracts)}
    ${legacyObligations(value.legacy_obligations, node.id)}
    ${entityList("Incoming relationships", connections.incoming, node.id)}
    ${entityList("Outgoing relationships", connections.outgoing, node.id)}
    ${entityList("Relevant tests", connections.tests || value.tests, node.id)}
    ${contractProperties(node)}
    ${evidenceMarkup(node.provenance, value.evidence || properties.evidence)}
    ${countsMarkup(value.counts)}
  </article>`;
}

function entityHeader(node, context = {}) {
  return `${state.entityTrail.length ? '<button class="secondary-button" data-entity-back>Back to previous entity</button>' : ""}
    <p class="eyebrow">${escapeHtml(humanize(node.kind || "entity"))} · ${escapeHtml(context.graph_kind || "observed")}</p>
    <h2>${escapeHtml(node.label || node.name || node.id)}</h2>
    ${node.reference ? '<p class="muted">Reference artifact · excluded from default source inventory</p>' : ""}
    ${node.path ? `<code class="inspector-path">${escapeHtml(node.path)}</code>` : ""}`;
}

function entityDescription(node) {
  const overview = node.overview || node.summary || "Understanding not yet recorded.";
  const detail = node.detail || node.properties?.detail;
  const readiness = node.readiness === "structural" ? "Structural facts available · semantic annotation not yet saved" : `Saved understanding: ${humanize(node.readiness || "readiness unknown")}`;
  return `<p class="entity-overview">${escapeHtml(overview)}</p><p class="entity-readiness muted">${escapeHtml(readiness)}</p>
    ${detail ? detail !== overview ? `<p class="entity-detail">${escapeHtml(detail)}</p>` : "" : '<p class="muted">No deeper explanation has been saved yet.</p>'}`;
}

function metricsMarkup(metrics) {
  const fields = [["Code lines", "lines_of_code"], ["Functions", "function_count"],
    ["Incoming consumers", "fan_in"], ["Known outgoing dependencies", Object.hasOwn(metrics, "resolved_fan_out") ? "resolved_fan_out" : "fan_out"]];
  const entries = fields.filter(([, key]) => Object.hasOwn(metrics, key));
  return entries.length ? `<dl class="entity-metrics">${entries.map(([label, key]) => (
    `<div><dt>${label}</dt><dd>${metrics[key] == null ? "Unknown" : escapeHtml(format.format(metrics[key]))}</dd></div>`
  )).join("")}</dl>` : "";
}

function unresolvedCalls(properties) {
  const calls = Number(properties.unresolved_call_count || 0);
  if (!calls) return "";
  const targets = Number(properties.unresolved_target_count || 0);
  return `<p class="entity-unresolved muted">${format.format(targets)} unresolved call targets · ${format.format(calls)} call sites. These are additional to the known dependencies; a missing static link is not evidence of unused code.</p>`;
}

function historyWindow(context = {}) {
  if (context.graph_kind !== "observed") return "";
  const history = context.git_metrics;
  if (!history?.scope || history.scope === "unavailable") return "";
  const labels = { observed_window: "Recent observed Git window", legacy_observed_history: "Preserved legacy Git observations", loaded_history: "Explicitly loaded Git history" };
  return `<p class="entity-history muted">${escapeHtml(labels[history.scope] || humanize(history.scope))} · ${format.format(history.window_commit_count || 0)} observed commits${history.observed_head ? ` · ${escapeHtml(history.observed_head.slice(0, 12))}` : ""}. Change counts and dates describe these observations, not a guaranteed lifetime total.</p>`;
}

export function structuralNotice(context = {}) {
  const analysis = context.structural_analysis;
  if (context.graph_kind !== "observed" || !analysis?.reindexed) return "";
  return `<p class="graph-reanalysis-note muted">Matching source files reanalyzed with current extractor (${format.format(analysis.reindexed_files)} files). Original source revisions and saved AI results remain preserved.</p>`;
}

function entityList(title, values, ownerId) {
  if (!Array.isArray(values) || !values.length) return "";
  return `<section class="entity-relations"><h3>${title}</h3><ul>${values.map(item => {
    const id = connectedEntityId(item, ownerId), label = connectedEntityLabel(item, id);
    const relation = item.relationship_type || item.type || item.kind;
    return `<li>${id ? entityButton(id, label) : escapeHtml(label || item)}
      ${relation ? `<small>${escapeHtml(humanize(relation))}</small>` : ""}
      ${item.overview || item.summary ? `<p>${escapeHtml(item.overview || item.summary)}</p>` : ""}</li>`;
  }).join("")}</ul></section>`;
}

function connectedEntityId(item, ownerId) {
  if (item.entity_id || item.node?.id) return item.entity_id || item.node.id;
  if (item.source && item.target) return String(item.source) === String(ownerId) ? item.target : item.source;
  return item.id;
}

function connectedEntityLabel(item, id) {
  const linked = state.graph.nodes.find(node => node.id === id);
  return item.label || item.node?.label || item.name || linked?.label || linked?.name || id;
}

function contractList(values, title = "Contracts and obligations") {
  if (!Array.isArray(values) || !values.length) return "";
  return `<section class="entity-contracts"><h3>${escapeHtml(title)}</h3>${values.map(item => {
    if (typeof item === "string") return `<p>${escapeHtml(item)}</p>`;
    return `<article>${item.id ? entityButton(item) : `<strong>${escapeHtml(item.name || item.label || "Contract")}</strong>`}
      <p>${escapeHtml(item.overview || item.summary || item.description || "")}</p>${contractProperties(item)}</article>`;
  }).join("")}</section>`;
}

function contractProperties(node) {
  const properties = node.properties || node;
  const fields = ["inputs", "outputs", "invariants", "obligations", "errors", "failures", "side_effects", "ordering", "constraints", "assumptions", "required_capabilities", "planned_paths", "unknowns"];
  return fields.filter(key => properties[key]?.length).map(key => {
    const values = Array.isArray(properties[key]) ? properties[key] : [properties[key]];
    return `<h4>${escapeHtml(humanize(key))}</h4><ul>${values.map(item => (
      `<li>${escapeHtml(typeof item === "object" ? item.description || item.name || JSON.stringify(item) : item)}</li>`
    )).join("")}</ul>`;
  }).join("");
}

function evidenceMarkup(provenance, evidence) {
  const sources = Array.isArray(evidence) ? evidence : [];
  if (!provenance && !sources.length) return "";
  return `<details class="entity-evidence"><summary>Evidence, provenance and uncertainty</summary>
    ${provenance ? `<pre>${escapeHtml(JSON.stringify(provenance, null, 2))}</pre>` : ""}
    ${sources.length ? `<ul>${sources.map(item => `<li>${escapeHtml(typeof item === "object" ? JSON.stringify(item) : item)}</li>`).join("")}</ul>` : ""}</details>`;
}

function countsMarkup(counts = {}) {
  const omitted = Object.entries(counts).filter(([key, value]) => key.startsWith("omitted") && value > 0);
  return omitted.length ? `<p class="muted">This focused response omits ${omitted.map(([key, value]) => `${format.format(value)} ${humanize(key.replace(/^omitted_/, ""))}`).join(", ")}. Expand the related graph scope to inspect more.</p>` : "";
}

export function legacyObligations(value, id) {
  if (!value?.total) return "";
  const offset = value.offset || 0, limit = value.limit || 25;
  const button = (label, next) => `<button class="secondary-button" data-entity-legacy="${escapeAttr(id)}" data-legacy-offset="${next}">${label}</button>`;
  return `<section class="entity-legacy-obligations">${contractList(value.items, "Saved legacy obligations · function bindings unknown")}<p class="muted">${value.returned || value.items?.length || 0} shown of ${value.total} saved obligations.</p>${offset ? button("Previous obligations", Math.max(0, offset - limit)) : ""}${value.next_offset != null ? button("Next obligations", value.next_offset) : ""}</section>`;
}
