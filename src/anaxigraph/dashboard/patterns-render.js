import {
  escapeAttr,
  escapeHtml,
  format,
  humanize,
} from "/assets/dashboard-core.js";

const CANDIDATE_REASON_COPY = {
  selected: "This target is in the current sparse evaluation plan.",
  no_positive_evidence: "The repository evidence has no positive signal for this pattern here.",
  counter_evidence: "Counter-signals outweigh the positive evidence at this target.",
  below_priority: "The evidence is relevant, but its priority is below the candidate threshold.",
  sparse_plan_bound: "The target qualified, but a higher-priority candidate occupied the bounded plan.",
  plan_not_ready: "The target qualifies, but the current sparse plan has not been finalized.",
};

export function renderEvaluationCard(item) {
  const target = item.target || {};
  const pattern = item.pattern || {};
  const review = item.review || {};
  const language = patternLanguage(item);
  return `<article class="panel pattern-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family)} · ${escapeHtml(humanize(pattern.kind))}</p>
      <h2>${escapeHtml(pattern.name)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge recommendation">${escapeHtml(humanize(item.recommendation))}</span>
      <span class="pattern-badge">${escapeHtml(humanize(item.presence))}</span></div></div>
    ${targetMarkup(target)}
    <div class="pattern-conclusion"><strong>Conclusion</strong><p>${escapeHtml(language.conclusion)}</p></div>
    <div class="pattern-story-grid">
      ${storyList("What AnaxiGraph saw", language.what_anaxigraph_saw)}
      ${storyText("Why this may matter", language.why_it_may_matter)}
      ${storyText("What to do", language.what_to_do)}
      ${storyList("Reasons not to change the code", language.reasons_not_to_change_the_code)}
      ${storyList("How to check the result", language.how_to_check)}
    </div>
    <div class="pattern-score-story">${(language.score_meanings || []).map(scoreMeaning).join("")}</div>
    <div class="pattern-review"><div><strong>Independent critique · ${escapeHtml(humanize(review.verdict || "complete"))}</strong>
      <span>${escapeHtml(language.independent_review || review.summary || "A second agent completed its check.")}</span></div></div>
    ${item.details ? evaluationDetails(item.details) : ""}
    <div class="pattern-result-footer"><span>${escapeHtml(item.provenance?.provider || "provider unknown")} · ${escapeHtml(item.provenance?.model || "runtime model")} · ${escapeHtml(item.provenance?.created_at || "")}</span>
      <div><button class="text-button" data-pattern-target="${escapeAttr(target.key)}">Compare patterns for target</button>
      <button class="text-button" data-pattern-key="${escapeAttr(pattern.key)}">Find this pattern elsewhere</button>
      <button class="text-button" data-candidate-key="${escapeAttr(pattern.key)}">Explain skipped candidates</button></div></div>
  </article>`;
}

function patternLanguage(item) {
  if (item.plain_language) return item.plain_language;
  return {
    conclusion: "This result does not include the current plain-language explanation contract.",
    what_anaxigraph_saw: [],
    why_it_may_matter: "The older response is incomplete, so its recommendation is not safe to use by itself.",
    what_to_do: "Query the current AnaxiGraph service for a complete pattern explanation.",
    reasons_not_to_change_the_code: ["Do not refactor from an incomplete pattern response."],
    how_to_check: ["Confirm the response includes pattern-explanation-v1 before acting."],
    score_meanings: [],
    independent_review: item.review?.summary || "A second agent completed its check.",
  };
}

function scoreMeaning(item) {
  const values = Object.entries(item.scores || {}).map(([name, value]) => (
    `${humanize(name)} ${format.format(Number(value || 0))}/100`
  )).join(" · ");
  return `<section><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(item.meaning)}</p><span>${escapeHtml(values)}</span></section>`;
}

function storyText(title, value) {
  if (!value) return "";
  return `<section><strong>${escapeHtml(title)}</strong><p>${escapeHtml(value)}</p></section>`;
}

function storyList(title, values = []) {
  if (!values.length) return "";
  return `<section><strong>${escapeHtml(title)}</strong><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}

export function renderCandidateCard(item, pattern) {
  const target = item.target || {};
  const reason = item.reason || "unknown";
  const selected = Boolean(item.selected_for_evaluation);
  const status = selected ? "selected" : "skipped";
  return `<article class="panel pattern-result-card candidate-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family || "catalog")} · candidate selection</p>
      <h2>${escapeHtml(pattern.name || pattern.key)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge ${selected ? "recommendation" : ""}">${status}</span>
      <span class="pattern-badge">${escapeHtml(humanize(reason))}</span></div></div>
    ${targetMarkup(target)}
    <p class="pattern-summary">${escapeHtml(CANDIDATE_REASON_COPY[reason] || humanize(reason))}</p>
    <div class="candidate-metric-grid">
      ${metric("Priority", item.priority)}
      ${metric("Matched signals", item.matched_signal_count)}
      ${metric("Counter-signals", item.counter_signal_count)}
      ${metric("Capability gaps", item.capability_gaps?.length || 0)}
    </div>
    ${candidateFactors(item)}
    ${item.details ? candidateDetails(item.details) : ""}
    <div class="pattern-result-footer"><span>Decision reason: ${escapeHtml(reason)}</span>
      <div><button class="text-button" data-evaluation-target="${escapeAttr(target.key)}"
        data-evaluation-key="${escapeAttr(pattern.key)}">Look for finalized evaluation</button></div></div>
  </article>`;
}

function targetMarkup(target) {
  return `<div class="pattern-target"><div><strong>${escapeHtml(target.label)}</strong>
    <span>${escapeHtml(target.path || target.qualified_name || target.key)}</span></div>
    <span class="pattern-level">${escapeHtml(target.level)}</span></div>`;
}

function metric(label, value) {
  return `<div class="pattern-score"><span>${escapeHtml(label)}</span><strong>${format.format(Number(value || 0))}</strong></div>`;
}

function evaluationDetails(details) {
  const lists = ["evidence", "counter_evidence", "alternatives", "prerequisites", "risks"];
  const sections = lists.map((name) => textGroup(name, details[name])).join("");
  const issues = (details.review_issues || []).map((issue) => (
    `<li><strong>${escapeHtml(humanize(issue.kind))}</strong> · ${escapeHtml(issue.explanation)}</li>`
  )).join("");
  return `<details class="pattern-details"><summary>Detailed evidence and critique</summary>
    <div class="pattern-evidence-grid">${sections}${issues ? `<section><h3>Review issues</h3><ul>${issues}</ul></section>` : ""}</div></details>`;
}

function candidateFactors(item) {
  const groups = [
    textGroup("Selection reasons", item.selection_reasons),
    textGroup("Missing evidence", item.missing_evidence),
    textGroup("Capability gaps", item.capability_gaps),
  ].join("");
  return groups ? `<div class="pattern-evidence-grid candidate-factors">${groups}</div>` : "";
}

function candidateDetails(details) {
  const signals = (details.signals || []).map((signal) => (
    `<li><strong>${escapeHtml(humanize(signal.role))}</strong> · ${escapeHtml(signal.feature)}
      ${escapeHtml(signal.operator)} · ${escapeHtml(humanize(signal.outcome))}
      (${format.format(signal.confidence || 0)}/100)</li>`
  )).join("");
  const capabilities = (details.capabilities || []).map((item) => (
    `<li><strong>${escapeHtml(item.fact)}</strong> · ${escapeHtml(item.best_level)} / ${escapeHtml(item.minimum)}
      (${Math.round(Number(item.ratio || 0) * 100)}%)</li>`
  )).join("");
  return `<details class="pattern-details"><summary>Detailed candidate evidence</summary>
    <div class="pattern-evidence-grid">
      ${signals ? `<section><h3>Signals</h3><ul>${signals}</ul></section>` : ""}
      ${capabilities ? `<section><h3>Capabilities</h3><ul>${capabilities}</ul></section>` : ""}
      ${textGroup("Semantic questions", details.semantic_questions)}
    </div></details>`;
}

function textGroup(name, values) {
  if (!values?.length) return "";
  return `<section><h3>${escapeHtml(humanize(name))}</h3><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}
