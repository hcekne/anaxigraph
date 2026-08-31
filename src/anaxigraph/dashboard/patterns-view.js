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
import {
  renderCandidateCard,
  renderEvaluationCard,
} from "/assets/patterns-render.js";

const SCORE_ORDER = [
  "opportunity", "suitability", "applicability", "conformance", "confidence",
  "benefit", "urgency", "execution_safety", "migration_cost",
];

const OPTION_LABELS = {
  evaluations: "Completed pattern results",
  candidates: "Why code was selected or skipped",
  symbol: "Function or method",
  type: "Class, interface, or type",
  module: "File",
  subsystem: "Smaller repository area",
  area: "Broad repository area",
  repository: "Whole repository",
  present: "Clearly present",
  partial: "Partly present",
  absent: "Not present",
  uncertain: "Not enough evidence",
  retain: "Keep the current pattern",
  introduce: "Consider adding the pattern",
  improve_conformance: "Make the existing pattern more consistent",
  replace: "Consider a different pattern",
  avoid: "Do not use this pattern here",
  no_action: "No change suggested",
  insufficient_evidence: "Not enough evidence",
  conformance: "How completely the code already follows it",
  applicability: "Whether the pattern addresses this kind of problem",
  suitability: "How well the pattern fits this code",
  opportunity: "How useful a change may be",
  execution_safety: "How safely the change can be made",
  migration_cost: "Cost of changing the code",
};

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
  configureQueryMode();
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
        <p class="eyebrow">Pattern suggestions checked by a second AI pass</p>
        <h2>Which coding patterns fit?</h2>
        <p class="panel-copy">See completed pattern results, or ask why a file, function, class,
          or repository area was selected or skipped before an AI checked it. Search by code or
          pattern across every size of the repository.</p>
      </div>
      <div class="pattern-contract-note"><strong>Nine scores answer different questions</strong><span>A pattern
        can fit well and already be fully present, which usually means the code should stay as it is.
        That is different from finding a useful reason to refactor.</span></div>
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
        <label>View<select id="pattern-mode-filter">
          <option value="evaluations">Completed pattern results</option>
          <option value="candidates">Why code was selected or skipped</option></select></label>
        <label>Show possible matches that were<select id="pattern-selection-filter" disabled>
          ${options(["skipped", "selected", "all"], "skipped")}</select></label>
        <label class="pattern-query-wide">File, function, class, or exact target key
          <input id="pattern-target-filter" placeholder="src/service.py or WorkflowDefinition" />
        </label>
        <label class="pattern-query-wide">Pattern library key <span id="pattern-key-requirement"></span>
          <input id="pattern-key-filter" placeholder="strategy" />
        </label>
        <label>Level<select id="pattern-level-filter"><option value="">All levels</option>
          ${options(["symbol", "type", "module", "subsystem", "area", "repository"])}</select>
        </label>
        <label data-evaluation-only>Is the pattern present?<select id="pattern-presence-filter"><option value="">Any answer</option>
          ${options(["present", "partial", "absent", "uncertain"])}</select></label>
        <label data-evaluation-only>Suggested action<select id="pattern-recommendation-filter">
          <option value="">Any suggested action</option>${options([
            "retain", "introduce", "improve_conformance", "replace", "avoid", "no_action",
            "insufficient_evidence",
          ])}</select></label>
        <label data-evaluation-only>Order by<select id="pattern-sort-filter">${options(SCORE_ORDER, "opportunity")}
        </select></label>
        <label data-evaluation-only>Lowest 0–100 answer to include<input id="pattern-minimum-score" type="number" min="0" max="100"
          value="0" /></label>
        <label>Rows<select id="pattern-page-size">${options([20, 50, 100], 20)}</select></label>
        <label class="checkbox-label pattern-evidence-toggle"><input id="pattern-include-evidence"
          type="checkbox" />Include detailed evidence and the second AI check</label>
        <div class="pattern-query-actions"><button id="pattern-query-submit" class="button"
          type="submit">Show completed pattern results</button><button id="pattern-query-reset" class="secondary-button"
          type="button">Reset</button></div>
      </form>
    </article>`;
}

function options(values, selected = "") {
  return values.map((value) => (
    `<option value="${escapeAttr(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(optionLabel(value))}</option>`
  )).join("");
}

function optionLabel(value) {
  return OPTION_LABELS[value] || humanize(value);
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
    configureQueryMode();
    loadPatterns();
  });
  byId("pattern-mode-filter").addEventListener("change", () => {
    currentOffset = 0;
    configureQueryMode();
    if (queryMode() === "evaluations" || byId("pattern-key-filter").value.trim()) loadPatterns();
    else renderCandidatePrompt();
  });
  byId("pattern-previous").addEventListener("click", () => movePage(-1));
  byId("pattern-next").addEventListener("click", () => movePage(1));
  byId("pattern-results").addEventListener("click", useResultAsFilter);
}

async function loadPatterns() {
  const repositoryLoadToken = state.repositoryLoadToken;
  const mode = queryMode();
  if (mode === "candidates" && !byId("pattern-key-filter").value.trim()) {
    renderCandidatePrompt();
    return;
  }
  const submit = byId("pattern-query-submit");
  submit.disabled = true;
  byId("pattern-query-summary").textContent = mode === "candidates"
    ? "Explaining why possible matches were selected or skipped…"
    : "Reading completed pattern results…";
  try {
    const endpoint = mode === "candidates" ? "/api/patterns/candidates" : "/api/patterns";
    const result = await request(api(endpoint, queryParameters()));
    if (repositoryLoadToken !== state.repositoryLoadToken) return;
    currentResult = result;
    loadedRepositoryId = state.repositoryId;
    renderPatternResults();
  } catch (error) {
    if (repositoryLoadToken !== state.repositoryLoadToken) return;
    currentResult = null;
    byId("pattern-query-summary").textContent = error.message;
    byId("pattern-results").innerHTML = "";
    toast(error.message, true);
  } finally {
    submit.disabled = false;
  }
}

function queryParameters() {
  const shared = {
    target: byId("pattern-target-filter").value.trim(),
    pattern: byId("pattern-key-filter").value.trim(),
    level: byId("pattern-level-filter").value,
    limit: Number(byId("pattern-page-size").value),
    offset: currentOffset,
    include_evidence: byId("pattern-include-evidence").checked,
  };
  if (queryMode() === "candidates") {
    return { ...shared, selection: byId("pattern-selection-filter").value };
  }
  return {
    ...shared,
    presence: byId("pattern-presence-filter").value,
    recommendation: byId("pattern-recommendation-filter").value,
    sort_by: byId("pattern-sort-filter").value,
    minimum_score: Number(byId("pattern-minimum-score").value || 0),
  };
}

function renderWaitingState() {
  if (!byId("pattern-query-summary")) return;
  byId("pattern-query-summary").textContent = "Open this view to search the current pattern results.";
  byId("pattern-results").innerHTML = "";
  updatePagination();
}

function renderPatternResults() {
  const result = currentResult || { total: 0, returned: 0, items: [] };
  if (queryMode() === "candidates") {
    renderCandidateResults(result);
    return;
  }
  const start = result.returned ? result.offset + 1 : 0;
  const end = result.offset + result.returned;
  byId("pattern-query-summary").innerHTML = result.total
    ? `<strong>${format.format(start)}–${format.format(end)}</strong> of <strong>${format.format(result.total)}</strong> current pattern results that completed a separate AI check. Ordered by ${escapeHtml(optionLabel(result.filters.sort_by))}.`
    : emptyResultMessage();
  byId("pattern-results").innerHTML = (result.items || [])
    .map((item) => renderEvaluationCard(item)).join("");
  updatePagination();
}

function renderCandidateResults(result) {
  const start = result.returned ? result.offset + 1 : 0;
  const end = result.offset + result.returned;
  const selection = optionLabel(result.filters?.selection || "all").toLowerCase();
  byId("pattern-query-summary").innerHTML = result.total
    ? `<strong>${format.format(start)}–${format.format(end)}</strong> of <strong>${format.format(result.total)}</strong> explanations for possible matches that were ${escapeHtml(selection)} for <strong>${escapeHtml(result.pattern?.name || result.pattern?.key)}</strong>. ${format.format(result.selected_count)} were selected and ${format.format(result.skipped_count)} were skipped across ${format.format(result.targets_considered)} pieces of code that had enough information to check.`
    : `<strong>No possible matches that were ${escapeHtml(selection)} fit these filters.</strong> AnaxiGraph considered ${format.format(result.targets_considered || 0)} pieces of code that had enough information to check.`;
  byId("pattern-results").innerHTML = (result.items || [])
    .map((item) => renderCandidateCard(item, result.pattern || {})).join("");
  updatePagination();
}

function emptyResultMessage() {
  const patterns = state.semanticStatus?.patterns || {};
  if (!patterns.ready) {
    const pending = Number(patterns.pending || state.semanticStatus?.jobs?.pending || 0);
    return `<strong>No completed pattern results yet.</strong> AI mapping${pending ? ` has ${format.format(pending)} saved tasks waiting` : " is not complete"}; a result appears here only after a separate AI pass checks it.`;
  }
  return "<strong>No current pattern result matches these filters.</strong> Clear a filter or lower the minimum score.";
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
    ? `${format.format(result.returned)} shown · starting at result ${format.format(result.offset + 1)}`
    : "No page";
}

function useResultAsFilter(event) {
  const button = event.target.closest(
    "[data-pattern-target], [data-pattern-key], [data-candidate-key], [data-evaluation-key]",
  );
  if (!button) return;
  if (button.dataset.patternTarget) {
    setQueryMode("evaluations");
    byId("pattern-target-filter").value = button.dataset.patternTarget;
    byId("pattern-key-filter").value = "";
  } else if (button.dataset.patternKey) {
    setQueryMode("evaluations");
    byId("pattern-key-filter").value = button.dataset.patternKey;
    byId("pattern-target-filter").value = "";
  } else if (button.dataset.candidateKey) {
    setQueryMode("candidates");
    byId("pattern-key-filter").value = button.dataset.candidateKey;
    byId("pattern-target-filter").value = "";
    byId("pattern-selection-filter").value = "skipped";
  } else {
    setQueryMode("evaluations");
    byId("pattern-key-filter").value = button.dataset.evaluationKey;
    byId("pattern-target-filter").value = button.dataset.evaluationTarget;
  }
  currentOffset = 0;
  byId("patterns-query-form").scrollIntoView({ behavior: "smooth", block: "start" });
  loadPatterns();
}

function queryMode() {
  return byId("pattern-mode-filter").value;
}

function setQueryMode(value) {
  byId("pattern-mode-filter").value = value;
  configureQueryMode();
}

function configureQueryMode() {
  const candidates = queryMode() === "candidates";
  byId("pattern-selection-filter").disabled = !candidates;
  document.querySelectorAll("[data-evaluation-only]").forEach((label) => {
    label.classList.toggle("pattern-control-disabled", candidates);
    label.querySelector("input, select").disabled = candidates;
  });
  byId("pattern-key-requirement").textContent = candidates ? "· required" : "";
  byId("pattern-key-filter").required = candidates;
  byId("pattern-query-submit").textContent = candidates
    ? "Explain why code was selected or skipped" : "Show completed pattern results";
}

function renderCandidatePrompt() {
  currentResult = null;
  byId("pattern-query-summary").innerHTML = "<strong>Enter one exact pattern library key.</strong> AnaxiGraph explains matching code only when you ask, so it does not save a score for every possible file-and-pattern pair.";
  byId("pattern-results").innerHTML = "";
  updatePagination();
}
