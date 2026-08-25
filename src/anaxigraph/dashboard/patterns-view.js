import {
  api,
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  request,
  state,
  toast,
} from "/assets/dashboard-core.js";

const SCORE_ORDER = [
  "opportunity", "suitability", "applicability", "conformance", "confidence",
  "benefit", "urgency", "execution_safety", "migration_cost",
];

let currentResult = null;
let currentOffset = 0;
let loadedRepositoryId = null;

export function setupPatternView() {
  if (byId("view-patterns")) return;
  installStylesheet();
  const tab = document.createElement("button");
  tab.className = "tab";
  tab.dataset.view = "patterns";
  tab.textContent = "Patterns";
  document.querySelector('.tab[data-view="architecture"]').after(tab);
  const section = document.createElement("section");
  section.id = "view-patterns";
  section.className = "view";
  section.innerHTML = patternViewMarkup();
  byId("view-architecture").after(section);
  bindPatternEvents(tab);
  renderWaitingState();
}

export function resetPatternView() {
  loadedRepositoryId = null;
  currentResult = null;
  currentOffset = 0;
  byId("patterns-query-form")?.reset();
  renderWaitingState();
  if (byId("view-patterns")?.classList.contains("active")) {
    window.setTimeout(loadPatterns, 0);
  }
}

function installStylesheet() {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/assets/patterns.css";
  link.dataset.patternStyles = "true";
  document.head.append(link);
}

function patternViewMarkup() {
  return `
    <article class="panel pattern-intro">
      <div>
        <p class="eyebrow">Autonomous, evidence-backed design review</p>
        <h2>Pattern intelligence</h2>
        <p class="panel-copy">Explore only current evaluations that completed independent agent
          critique. Start with a target to compare suitable patterns, or a catalog key to find
          examples, weak conformers, and high-value opportunities across the code hierarchy.</p>
      </div>
      <div class="pattern-contract-note"><strong>Nine separate scores</strong><span>Fit,
        presence, value, safety, and cost remain distinct. A high-conformance example is not
        mislabeled as a refactor opportunity.</span></div>
    </article>
    ${patternQueryMarkup()}
    <div id="pattern-query-summary" class="notice pattern-query-summary"></div>
    <div id="pattern-results" class="pattern-results"></div>
    <div class="pattern-pagination"><button id="pattern-previous" class="secondary-button"
      type="button">Previous</button><span id="pattern-page-label" class="snapshot-label"></span>
      <button id="pattern-next" class="secondary-button" type="button">Next</button></div>`;
}

function patternQueryMarkup() {
  return `<article class="panel pattern-query-panel">
      <form id="patterns-query-form" class="pattern-query-grid">
        <label class="pattern-query-wide">Target key, path, or qualified name
          <input id="pattern-target-filter" placeholder="module:src/service.py or src/service.py" />
        </label>
        <label class="pattern-query-wide">Pattern catalog key
          <input id="pattern-key-filter" placeholder="strategy" />
        </label>
        <label>Level<select id="pattern-level-filter"><option value="">All levels</option>
          ${options(["symbol", "type", "module", "subsystem", "area", "repository"])}</select>
        </label>
        <label>Presence<select id="pattern-presence-filter"><option value="">Any presence</option>
          ${options(["present", "partial", "absent", "uncertain"])}</select></label>
        <label>Recommendation<select id="pattern-recommendation-filter">
          <option value="">Any recommendation</option>${options([
            "retain", "introduce", "improve_conformance", "replace", "avoid", "no_action",
            "insufficient_evidence",
          ])}</select></label>
        <label>Rank by<select id="pattern-sort-filter">${options(SCORE_ORDER, "opportunity")}
        </select></label>
        <label>Minimum score<input id="pattern-minimum-score" type="number" min="0" max="100"
          value="0" /></label>
        <label>Rows<select id="pattern-page-size">${options([20, 50, 100], 20)}</select></label>
        <label class="checkbox-label pattern-evidence-toggle"><input id="pattern-include-evidence"
          type="checkbox" />Include detailed evidence &amp; critique</label>
        <div class="pattern-query-actions"><button class="button" type="submit">Query finalized
          evaluations</button><button id="pattern-query-reset" class="secondary-button"
          type="button">Reset</button></div>
      </form>
    </article>`;
}

function options(values, selected = "") {
  return values.map((value) => (
    `<option value="${escapeAttr(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(humanize(value))}</option>`
  )).join("");
}

function bindPatternEvents(tab) {
  tab.addEventListener("click", () => {
    if (loadedRepositoryId !== state.repositoryId) loadPatterns();
  });
  byId("patterns-query-form").addEventListener("submit", (event) => {
    event.preventDefault();
    currentOffset = 0;
    loadPatterns();
  });
  byId("pattern-query-reset").addEventListener("click", () => {
    byId("patterns-query-form").reset();
    currentOffset = 0;
    loadPatterns();
  });
  byId("pattern-previous").addEventListener("click", () => movePage(-1));
  byId("pattern-next").addEventListener("click", () => movePage(1));
  byId("pattern-results").addEventListener("click", useResultAsFilter);
}

async function loadPatterns() {
  const submit = byId("patterns-query-form").querySelector('[type="submit"]');
  submit.disabled = true;
  byId("pattern-query-summary").textContent = "Reading current finalized evaluations…";
  try {
    currentResult = await request(api("/api/patterns", queryParameters()));
    loadedRepositoryId = state.repositoryId;
    renderPatternResults();
  } catch (error) {
    currentResult = null;
    byId("pattern-query-summary").textContent = error.message;
    byId("pattern-results").innerHTML = "";
    toast(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

function queryParameters() {
  return {
    target: byId("pattern-target-filter").value.trim(),
    pattern: byId("pattern-key-filter").value.trim(),
    level: byId("pattern-level-filter").value,
    presence: byId("pattern-presence-filter").value,
    recommendation: byId("pattern-recommendation-filter").value,
    sort_by: byId("pattern-sort-filter").value,
    minimum_score: Number(byId("pattern-minimum-score").value || 0),
    limit: Number(byId("pattern-page-size").value),
    offset: currentOffset,
    include_evidence: byId("pattern-include-evidence").checked,
  };
}

function renderWaitingState() {
  if (!byId("pattern-query-summary")) return;
  byId("pattern-query-summary").textContent = "Open this view to query current pattern intelligence.";
  byId("pattern-results").innerHTML = "";
  updatePagination();
}

function renderPatternResults() {
  const result = currentResult || { total: 0, returned: 0, items: [] };
  const start = result.returned ? result.offset + 1 : 0;
  const end = result.offset + result.returned;
  byId("pattern-query-summary").innerHTML = result.total
    ? `<strong>${format.format(start)}–${format.format(end)}</strong> of <strong>${format.format(result.total)}</strong> current, independently critiqued evaluation(s). Ranked by ${escapeHtml(humanize(result.filters.sort_by))}.`
    : emptyResultMessage();
  byId("pattern-results").innerHTML = (result.items || []).map(patternCard).join("");
  updatePagination();
}

function emptyResultMessage() {
  const patterns = state.semanticStatus?.patterns || {};
  if (!patterns.ready) {
    const pending = Number(patterns.pending || state.semanticStatus?.jobs?.pending || 0);
    return `<strong>No finalized pattern evaluations yet.</strong> Semantic mapping${pending ? ` has ${format.format(pending)} queued job(s)` : " is not complete"}; assessments appear here only after independent critique.`;
  }
  return "<strong>No current evaluation matches these filters.</strong> Clear a filter or lower the minimum score.";
}

function patternCard(item) {
  const target = item.target || {};
  const pattern = item.pattern || {};
  const review = item.review || {};
  return `<article class="panel pattern-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family)} · ${escapeHtml(humanize(pattern.kind))}</p>
      <h2>${escapeHtml(pattern.name)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge recommendation">${escapeHtml(humanize(item.recommendation))}</span>
      <span class="pattern-badge">${escapeHtml(humanize(item.presence))}</span></div></div>
    <div class="pattern-target"><div><strong>${escapeHtml(target.label)}</strong>
      <span>${escapeHtml(target.path || target.qualified_name || target.key)}</span></div>
      <span class="pattern-level">${escapeHtml(target.level)}</span></div>
    <p class="pattern-summary">${escapeHtml(item.summary)}</p>
    <div class="pattern-score-grid">${SCORE_ORDER.map((name) => scoreCell(name, item.scores?.[name])).join("")}</div>
    <div class="pattern-review"><div><strong>Independent critique · ${escapeHtml(humanize(review.verdict || "complete"))}</strong>
      <span>${escapeHtml(review.summary || "Final critique completed.")}</span></div>
      <span>${format.format(review.confidence || 0)}/100 confidence</span></div>
    ${item.details ? detailMarkup(item.details) : ""}
    <div class="pattern-result-footer"><span>${escapeHtml(item.provenance?.provider || "provider unknown")} · ${escapeHtml(item.provenance?.model || "runtime model")} · ${escapeHtml(item.provenance?.created_at || "")}</span>
      <div><button class="text-button" data-pattern-target="${escapeAttr(target.key)}">Compare patterns for target</button>
      <button class="text-button" data-pattern-key="${escapeAttr(pattern.key)}">Find this pattern elsewhere</button></div></div>
  </article>`;
}

function scoreCell(name, value) {
  const score = Number(value || 0);
  return `<div class="pattern-score" data-score-band="${score >= 70 ? "high" : score >= 40 ? "medium" : "low"}"><span>${escapeHtml(humanize(name))}</span><strong>${score}</strong></div>`;
}

function detailMarkup(details) {
  const lists = ["evidence", "counter_evidence", "alternatives", "prerequisites", "risks"];
  const sections = lists.map((name) => evidenceGroup(name, details[name])).join("");
  const issues = (details.review_issues || []).map((issue) => (
    `<li><strong>${escapeHtml(humanize(issue.kind))}</strong> · ${escapeHtml(issue.explanation)}</li>`
  )).join("");
  return `<details class="pattern-details"><summary>Detailed evidence and critique</summary>
    <div class="pattern-evidence-grid">${sections}${issues ? `<section><h3>Review issues</h3><ul>${issues}</ul></section>` : ""}</div></details>`;
}

function evidenceGroup(name, values) {
  if (!values?.length) return "";
  return `<section><h3>${escapeHtml(humanize(name))}</h3><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}

function movePage(direction) {
  if (!currentResult) return;
  const limit = Number(byId("pattern-page-size").value);
  currentOffset = direction > 0
    ? Number(currentResult.next_offset || currentOffset)
    : Math.max(0, currentOffset - limit);
  loadPatterns();
}

function updatePagination() {
  const result = currentResult;
  byId("pattern-previous").disabled = !result || currentOffset <= 0;
  byId("pattern-next").disabled = !result || result.next_offset == null;
  byId("pattern-page-label").textContent = result?.total
    ? `Offset ${format.format(result.offset)} · ${format.format(result.returned)} shown`
    : "No page";
}

function useResultAsFilter(event) {
  const button = event.target.closest("[data-pattern-target], [data-pattern-key]");
  if (!button) return;
  if (button.dataset.patternTarget) {
    byId("pattern-target-filter").value = button.dataset.patternTarget;
    byId("pattern-key-filter").value = "";
  } else {
    byId("pattern-key-filter").value = button.dataset.patternKey;
    byId("pattern-target-filter").value = "";
  }
  currentOffset = 0;
  byId("patterns-query-form").scrollIntoView({ behavior: "smooth", block: "start" });
  loadPatterns();
}
