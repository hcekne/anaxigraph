import { architectureFor, byId, escapeAttr, escapeHtml, format, humanize, state } from "/assets/dashboard-core.js";
import { formatDate } from "/assets/dashboard-format.js";
import { entityInspector } from "/assets/entity-inspector.js";

const COLUMNS = [
  ["path", "Module"], ["architecture_area", "Area"], ["summary", "Purpose"],
  ["lines_of_code", "Code lines"], ["function_count", "Functions"],
  ["fan_in", "Consumers"], ["fan_out", "Dependencies"],
  ["complexity", "Branches", true], ["line_coverage", "Coverage", true],
  ["change_count", "Observed changes", true], ["first_changed_at", "First observed change", true],
  ["last_commit_at", "Last worked", true], ["interface_count", "Interfaces", true],
  ["contract_count", "Contracts", true],
];

const DEFAULT_COLUMNS = COLUMNS.filter(([, , advanced]) => !advanced).map(([key]) => key);
let selectedColumns = columnPreference();

function columnPreference() {
  try { const value = JSON.parse(localStorage.getItem("anaxigraph.module-columns")); if (Array.isArray(value)) return new Set(["path", ...value]); } catch (_) { /* Use the readable default when storage is unavailable. */ }
  return new Set(DEFAULT_COLUMNS);
}

export function renderModuleColumnChoices() {
  byId("module-column-options").innerHTML = COLUMNS.map(([key, label]) => `<label class="checkbox-label"><input type="checkbox" value="${key}" ${selectedColumns.has(key) ? "checked" : ""} ${key === "path" ? "disabled" : ""} />${label}</label>`).join("");
}

export function selectModuleColumns(keys) {
  const focused = byId("module-column-options").contains(document.activeElement) ? document.activeElement.value : "";
  selectedColumns = new Set(["path", ...(keys === "all" ? COLUMNS.map(([key]) => key) : keys === "default" ? DEFAULT_COLUMNS : keys)]);
  try { localStorage.setItem("anaxigraph.module-columns", JSON.stringify([...selectedColumns])); } catch (_) { /* Choices work for this session. */ }
  renderModuleColumnChoices(); renderModules();
  if (focused) byId("module-column-options").querySelector(`input[value="${focused}"]`)?.focus();
}

export function renderModuleFilters() {
  const facets = state.moduleEnvelope?.facets || {};
  populate("module-area-filter", facets.areas, "areas", "architecture_area");
  populate("module-subsystem-filter", facets.subsystems, "subsystems", "architecture_subsystem");
  populate("module-language-filter", facets.languages, "languages", "language");
}

function populate(id, facet, label, key) {
  const select = byId(id), selected = select.value;
  const values = [...new Set((facet || state.modules.map(item => item[key])).map(
    item => typeof item === "object" ? item.value || item.name || item.key : item,
  ).filter(Boolean))].sort();
  if (selected && !values.includes(selected)) values.push(selected);
  select.innerHTML = `<option value="">All ${label}</option>${values.map(value => (
    `<option value="${escapeAttr(value)}">${escapeHtml(humanize(value))}</option>`
  )).join("")}`;
  select.value = selected;
}

export function renderModules() {
  const envelope = state.moduleEnvelope;
  const items = state.modules || [];
  const limit = Number(byId("module-page-size").value || 100);
  const total = Number(envelope?.total_nodes ?? envelope?.total ?? 0);
  const pages = Math.max(1, Math.ceil(total / limit));
  const columns = COLUMNS.filter(([key]) => selectedColumns.has(key));
  byId("view-modules").style.setProperty("--module-table-width", `${Math.max(800, columns.length * 130)}px`);
  byId("view-modules").setAttribute("aria-busy", String(!!state.moduleLoading));
  byId("module-result-count").textContent = state.moduleError || (state.moduleLoading && !envelope
    ? "Reading the selected module page…"
    : `${format.format(items.length)} shown · ${format.format(total)} matching modules · globally sorted`);
  byId("module-page-label").textContent = `Page ${state.modulePage} of ${pages}`;
  byId("module-previous").disabled = state.moduleLoading || state.modulePage <= 1;
  byId("module-next").disabled = state.moduleLoading || envelope?.next_offset == null;
  byId("view-modules").querySelector("thead").innerHTML = moduleHeader(columns);
  byId("module-table-body").innerHTML = items.map(item => moduleRow(item, columns)).join("")
    || `<tr><td colspan="${columns.length + 1}"><p class="muted">${state.moduleLoading ? "Loading modules…" : "No modules match this scope."}</p></td></tr>`;
}

function moduleHeader(columns) {
  return `<tr><th scope="col"><span class="sr-only">Expand module</span></th>${columns.map(([key, label]) => {
    const selected = state.moduleSort.key === key;
    const sort = selected ? state.moduleSort.direction === "asc" ? "ascending" : "descending" : "none";
    const arrow = state.moduleSort.direction === "asc" ? "↑" : "↓";
    return `<th scope="col" aria-sort="${sort}"><button data-module-sort="${key}" ${selected ? `data-direction="${arrow}"` : ""}>${label}</button></th>`;
  }).join("")}</tr>`;
}

function moduleRow(item, columns) {
  const id = String(item.id || item.artifact_id);
  const expanded = String(state.expandedModuleId) === id;
  const cells = columns.map(([key]) => `<td${["path", "summary", "architecture_area"].includes(key) ? "" : ' class="numeric"'}>${cell(item, key)}</td>`).join("");
  const row = `<tr class="module-row" data-module-id="${escapeAttr(id)}" aria-expanded="${expanded}"><td class="module-select"><button type="button" data-module-expand="${escapeAttr(id)}" aria-label="${expanded ? "Collapse" : "Expand"} ${escapeAttr(item.name)}">${expanded ? "−" : "+"}</button></td>${cells}</tr>`;
  return expanded ? row + detailRow(item, columns.length + 1) : row;
}

function cell(item, key) {
  if (key === "path") return `<span class="module-name">${escapeHtml(item.name)}</span>${item.reference ? '<span class="attention-pill reference">Reference</span>' : ""}<code class="module-path">${escapeHtml(item.path)}</code>`;
  if (key === "summary") return `<span class="module-summary">${escapeHtml(item.overview || item.summary)}</span>`;
  if (key === "architecture_area") return moduleAreaCell(item);
  const value = item[key] ?? item.metrics?.[key];
  if (value == null) return '<span class="muted" title="Not recorded or not applicable">—</span>';
  if (key === "line_coverage") return `${Math.round(Number(value) * 100)}%`;
  if (key.endsWith("_at")) return escapeHtml(formatDate(value));
  return escapeHtml(typeof value === "number" ? format.format(value) : value);
}

function moduleAreaCell(item) {
  const place = architectureFor(item) || item.placement || {};
  return `<strong>${escapeHtml(place.area_label || humanize(place.area || item.architecture_area || "Unclassified"))}</strong>`;
}

function detailRow(item, span) {
  const detail = state.moduleDetails.get(String(item.id));
  const content = detail ? entityInspector(detail) : '<p role="status">Reading saved understanding…</p>';
  return `<tr class="module-detail-row"><td colspan="${span}"><div class="module-detail shared-entity-detail">${content}</div></td></tr>`;
}
