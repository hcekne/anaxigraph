import { api, byId, escapeAttr, escapeHtml, format, humanize, request, state, toast } from "/assets/dashboard-core.js";
import { switchView } from "/assets/navigation.js";
import { renderCandidateCard, renderEvaluationCard } from "/assets/patterns-render.js";

let result = null, offset = 0, requestToken = 0;

export function setupPatternView() {
  if (byId("view-patterns")) return;
  const section = document.createElement("section");
  section.id = "view-patterns"; section.className = "view";
  section.innerHTML = markup();
  byId("view-architecture").after(section);
  byId("patterns-query-form").addEventListener("submit", event => { event.preventDefault(); offset = 0; void loadPatterns(); });
  byId("pattern-previous").addEventListener("click", () => { offset = Math.max(0, offset - pageSize()); void loadPatterns(); });
  byId("pattern-next").addEventListener("click", () => { offset = result?.next_offset || 0; void loadPatterns(); });
  byId("pattern-open-workflow").addEventListener("click", () => switchView("workflows", false, "patterns"));
  section.addEventListener("click", event => { void handlePatternNavigation(event); });
  byId("pattern-legacy-form").addEventListener("submit", event => { event.preventDefault(); void loadLegacyDiagnostics(); });
  window.addEventListener("anaxigraph:contextready", () => {
    if (byId("view-patterns").classList.contains("active")) void loadPatterns();
  });
  window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
    if (detail.name === "patterns") void loadPatterns();
  });
}

export function resetPatternView() {
  result = null; offset = 0; requestToken += 1;
  byId("patterns-query-form")?.reset();
  if (byId("pattern-results")) byId("pattern-results").innerHTML = "";
  if (byId("view-patterns")?.classList.contains("active")) void loadPatterns();
}

function markup() {
  return `<article class="panel pattern-intro"><p class="eyebrow">The complete versioned catalogue</p>
    <h2>Which patterns could improve this architecture?</h2><p>Every catalogue entry receives contextual ratings, pros and cons. Missing assessment, uncertain evidence and poor fit are different outcomes. A useful pattern need not fix a bug.</p>
    <button id="pattern-open-workflow" class="secondary-button">Open Pattern analysis workflow</button></article>
    <article class="panel"><div id="pattern-catalogue-counts" class="catalogue-counts" role="status"></div>
    <form id="patterns-query-form" class="pattern-query-grid"><label>Pattern<input id="pattern-key-filter" type="search" placeholder="Search catalogue names or IDs" /></label>
    <label>Family<input id="pattern-family-filter" placeholder="All families" /></label><label>Assessment state<select id="pattern-state-filter"><option value="">All states</option>${["missing", "considered", "rated", "reviewed", "unresolved"].map(value => `<option value="${value}">${humanize(value)}</option>`).join("")}</select></label>
    <label>Order by<select id="pattern-sort-filter">${["opportunity", "pattern", "suitability", "benefit", "conformance", "confidence", "applicability", "urgency", "execution_safety", "migration_cost"].map(key => `<option value="${key}">${humanize(key)}</option>`).join("")}</select></label>
    <label>Rows<select id="pattern-page-size"><option>25</option><option>50</option><option>100</option></select></label><button class="button" type="submit">Show catalogue assessments</button></form>
    <p id="pattern-query-summary" class="muted">Open this view to read saved assessments.</p>
    <div id="pattern-results" class="catalogue-table-wrap"></div>
    <div class="pattern-pagination"><button id="pattern-previous" class="secondary-button">Previous</button><span id="pattern-page-label"></span><button id="pattern-next" class="secondary-button">Next</button></div></article>
    <details class="panel"><summary>Compatibility diagnostics for earlier candidate selection</summary><p>Earlier runs preselected candidate–target pairs. These diagnostics do not define current catalogue coverage.</p><form id="pattern-legacy-form"><label>Exact pattern key<input id="pattern-legacy-key" required /></label><button class="secondary-button">Read diagnostics</button></form><div id="pattern-legacy-results"></div></details>`;
}

function contextKey() { return `${state.repositoryId}:${state.overview?.snapshot?.id}`; }
function pageSize() { return Number(byId("pattern-page-size").value); }

async function loadPatterns() {
  if (!state.repositoryId || !state.overview) return;
  const token = ++requestToken, context = contextKey();
  byId("pattern-query-summary").textContent = "Reading catalogue coverage and saved assessments…";
  try {
    const value = await request(api("/api/patterns/catalogue", {
      snapshot_id: state.overview?.snapshot?.id, limit: pageSize(), offset,
      pattern: byId("pattern-key-filter").value.trim(), family: byId("pattern-family-filter").value.trim(), state: byId("pattern-state-filter").value,
      sort_by: byId("pattern-sort-filter").value,
    }));
    if (token !== requestToken || context !== contextKey()) return;
    result = value; renderPatterns(value);
  } catch (error) {
    if (token === requestToken) { byId("pattern-query-summary").textContent = error.message; toast(error.message, true); }
  }
}

function renderPatterns(value) {
  const catalogue = value.catalogue || {};
  byId("pattern-catalogue-counts").innerHTML = ["expected", "considered", "rated", "reviewed", "unresolved", "missing"].map(key => (
    `<span>${humanize(key)} <strong>${format.format(catalogue[key] || 0)}</strong></span>`
  )).join("");
  byId("pattern-query-summary").textContent = `${catalogue.complete ? "All catalogue entries reviewed" : "Catalogue review incomplete"} · ${value.returned || 0} shown of ${value.total || 0} matching entries. Coverage is independent of this page. Catalogue ${String(catalogue.fingerprint || "unknown").slice(0, 12)}.`;
  byId("pattern-results").innerHTML = `<table class="catalogue-table"><thead><tr><th>Pattern</th><th>Assessment</th><th>Ratings</th><th>Pros here</th><th>Cons here</th><th>Relevant placement and evidence</th></tr></thead><tbody>${(value.items || []).map(patternRow).join("")}</tbody></table>`;
  byId("pattern-previous").disabled = offset === 0;
  byId("pattern-next").disabled = value.next_offset == null;
  byId("pattern-page-label").textContent = `${offset + (value.returned ? 1 : 0)}–${offset + (value.returned || 0)} of ${value.total || 0}`;
}

function patternRow(item) {
  const pattern = item.pattern || {};
  const scores = Object.entries(item.scores || {}).map(([key, value]) => `<span>${escapeHtml(humanize(key))}: ${value == null ? "Unknown" : escapeHtml(value)}</span>`).join("<br>");
  return `<tr data-catalogue-pattern="${escapeAttr(pattern.key)}"><th scope="row">${escapeHtml(pattern.name || pattern.key)}<small>${escapeHtml(pattern.family || "")}</small><details><summary>Pattern intent</summary><p>${escapeHtml(pattern.intent || "")}</p></details></th>
    <td><strong>${escapeHtml(humanize(item.state))}</strong><p>${escapeHtml(item.summary || "Not assessed yet")}</p><p>${escapeHtml(humanize(item.recommendation || ""))}</p></td>
    <td>${scores || "Not rated"}</td><td>${list(item.pros)}</td><td>${list(item.cons)}</td><td>${placements(item.placements)}${item.provenance ? `<details><summary>Assessment provenance</summary><pre>${escapeHtml(JSON.stringify(item.provenance, null, 2))}</pre></details>` : ""}<button class="secondary-button" data-pattern-detail="${escapeAttr(pattern.key)}">Read full saved assessment</button><div data-pattern-full="${escapeAttr(pattern.key)}"></div></td></tr>`;
}

async function handlePatternNavigation(event) {
  const pattern = event.target.closest("[data-pattern-key], [data-evaluation-key]");
  if (pattern) {
    byId("pattern-key-filter").value = pattern.dataset.patternKey || pattern.dataset.evaluationKey;
    offset = 0; await loadPatterns(); return;
  }
  const candidate = event.target.closest("[data-candidate-key]");
  if (candidate) {
    byId("pattern-legacy-key").value = candidate.dataset.candidateKey;
    byId("pattern-legacy-form").closest("details").open = true;
    await loadLegacyDiagnostics(); return;
  }
  await loadFullAssessment(event);
}

async function loadFullAssessment(event) {
  const button = event.target.closest("[data-pattern-detail]");
  if (!button) return;
  const context = contextKey(), key = button.dataset.patternDetail;
  button.disabled = true;
  try {
    const detail = await request(api("/api/patterns", { pattern: key, snapshot_id: state.overview?.snapshot?.id, include_evidence: true, limit: 25 }));
    if (context !== contextKey() || !button.isConnected) return;
    button.nextElementSibling.innerHTML = (detail.items || []).map(renderEvaluationCard).join("") || '<p>No completed full assessment is saved yet.</p>';
  } catch (error) { if (button.isConnected) button.nextElementSibling.textContent = error.message; }
  finally { if (button.isConnected) button.disabled = false; }
}

async function loadLegacyDiagnostics() {
  const context = contextKey(), panel = byId("pattern-legacy-results");
  panel.textContent = "Reading compatibility diagnostics…";
  try {
    const value = await request(api("/api/patterns/candidates", { pattern: byId("pattern-legacy-key").value.trim(), selection: "all", include_evidence: true, limit: 50 }));
    if (context !== contextKey()) return;
    panel.innerHTML = `<p>${value.returned || 0} of ${value.total || 0} matching compatibility records.</p>` + (value.items || []).map(item => renderCandidateCard(item, value.pattern || {})).join("");
  } catch (error) { if (context === contextKey()) panel.textContent = error.message; }
}

function list(values) {
  return values?.length ? `<ul>${values.map(item => `<li>${escapeHtml(typeof item === "string" ? item : item.reason || item.description || JSON.stringify(item))}</li>`).join("")}</ul>` : '<span class="muted">Not assessed</span>';
}

function placements(values = []) {
  return values.map(item => `<details><summary>${escapeHtml(item.target_key || item.entity_id || "Relevant area")}</summary><p>${escapeHtml(item.reason || "")}</p>${list(item.pros)}${list(item.cons)}${list(item.evidence)}</details>`).join("") || '<span class="muted">No placement established</span>';
}
