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
        <p class="eyebrow">Autonomous, evidence-backed design review</p>
        <h2>Pattern intelligence</h2>
        <p class="panel-copy">Explore current evaluations that completed independent agent
          critique, or ask why an eligible target was selected or skipped before evaluation.
          Query by target or pattern across the full code hierarchy.</p>
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
        <label>View<select id="pattern-mode-filter">
          <option value="evaluations">Finalized evaluations</option>
          <option value="candidates">Candidate explanations</option></select></label>
        <label>Candidate selection<select id="pattern-selection-filter" disabled>
          ${options(["skipped", "selected", "all"], "skipped")}</select></label>
        <label class="pattern-query-wide">Target key, path, or qualified name
          <input id="pattern-target-filter" placeholder="module:src/service.py or src/service.py" />
        </label>
        <label class="pattern-query-wide">Pattern catalog key <span id="pattern-key-requirement"></span>
          <input id="pattern-key-filter" placeholder="strategy" />
        </label>
        <label>Level<select id="pattern-level-filter"><option value="">All levels</option>
          ${options(["symbol", "type", "module", "subsystem", "area", "repository"])}</select>
        </label>
        <label data-evaluation-only>Presence<select id="pattern-presence-filter"><option value="">Any presence</option>
          ${options(["present", "partial", "absent", "uncertain"])}</select></label>
        <label data-evaluation-only>Recommendation<select id="pattern-recommendation-filter">
          <option value="">Any recommendation</option>${options([
            "retain", "introduce", "improve_conformance", "replace", "avoid", "no_action",
            "insufficient_evidence",
          ])}</select></label>
        <label data-evaluation-only>Rank by<select id="pattern-sort-filter">${options(SCORE_ORDER, "opportunity")}
        </select></label>
        <label data-evaluation-only>Minimum score<input id="pattern-minimum-score" type="number" min="0" max="100"
          value="0" /></label>
        <label>Rows<select id="pattern-page-size">${options([20, 50, 100], 20)}</select></label>
        <label class="checkbox-label pattern-evidence-toggle"><input id="pattern-include-evidence"
          type="checkbox" />Include detailed evidence &amp; critique</label>
        <div class="pattern-query-actions"><button id="pattern-query-submit" class="button"
          type="submit">Query finalized evaluations</button><button id="pattern-query-reset" class="secondary-button"
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
  const mode = queryMode();
  if (mode === "candidates" && !byId("pattern-key-filter").value.trim()) {
    renderCandidatePrompt();
    return;
  }
  const submit = byId("pattern-query-submit");
  submit.disabled = true;
  byId("pattern-query-summary").textContent = mode === "candidates"
    ? "Explaining current sparse-plan candidate decisions…"
    : "Reading current finalized evaluations…";
  try {
    const endpoint = mode === "candidates" ? "/api/patterns/candidates" : "/api/patterns";
    currentResult = await request(api(endpoint, queryParameters()));
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
  byId("pattern-query-summary").textContent = "Open this view to query current pattern intelligence.";
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
    ? `<strong>${format.format(start)}–${format.format(end)}</strong> of <strong>${format.format(result.total)}</strong> current, independently critiqued evaluation(s). Ranked by ${escapeHtml(humanize(result.filters.sort_by))}.`
    : emptyResultMessage();
  byId("pattern-results").innerHTML = (result.items || [])
    .map((item) => renderEvaluationCard(item)).join("");
  updatePagination();
}

function renderCandidateResults(result) {
  const start = result.returned ? result.offset + 1 : 0;
  const end = result.offset + result.returned;
  const selection = humanize(result.filters?.selection || "all");
  byId("pattern-query-summary").innerHTML = result.total
    ? `<strong>${format.format(start)}–${format.format(end)}</strong> of <strong>${format.format(result.total)}</strong> ${escapeHtml(selection)} candidate explanation(s) for <strong>${escapeHtml(result.pattern?.name || result.pattern?.key)}</strong>. ${format.format(result.selected_count)} selected and ${format.format(result.skipped_count)} skipped across ${format.format(result.targets_considered)} eligible target(s).`
    : `<strong>No ${escapeHtml(selection)} candidates match.</strong> The current plan considered ${format.format(result.targets_considered || 0)} eligible target(s).`;
  byId("pattern-results").innerHTML = (result.items || [])
    .map((item) => renderCandidateCard(item, result.pattern || {})).join("");
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
    ? "Explain candidate selection" : "Query finalized evaluations";
}

function renderCandidatePrompt() {
  currentResult = null;
  byId("pattern-query-summary").innerHTML = "<strong>Enter one exact pattern catalog key.</strong> Candidate explanations are computed on demand without storing a dense target-by-pattern matrix.";
  byId("pattern-results").innerHTML = "";
  updatePagination();
}
