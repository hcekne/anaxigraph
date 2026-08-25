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

export function renderEvaluationCard(item, scoreOrder) {
  const target = item.target || {};
  const pattern = item.pattern || {};
  const review = item.review || {};
  return `<article class="panel pattern-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family)} · ${escapeHtml(humanize(pattern.kind))}</p>
      <h2>${escapeHtml(pattern.name)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge recommendation">${escapeHtml(humanize(item.recommendation))}</span>
      <span class="pattern-badge">${escapeHtml(humanize(item.presence))}</span></div></div>
    ${targetMarkup(target)}
    <p class="pattern-summary">${escapeHtml(item.summary)}</p>
    <div class="pattern-score-grid">${scoreOrder.map((name) => scoreCell(name, item.scores?.[name])).join("")}</div>
    <div class="pattern-review"><div><strong>Independent critique · ${escapeHtml(humanize(review.verdict || "complete"))}</strong>
      <span>${escapeHtml(review.summary || "Final critique completed.")}</span></div>
      <span>${format.format(review.confidence || 0)}/100 confidence</span></div>
    ${item.details ? evaluationDetails(item.details) : ""}
    <div class="pattern-result-footer"><span>${escapeHtml(item.provenance?.provider || "provider unknown")} · ${escapeHtml(item.provenance?.model || "runtime model")} · ${escapeHtml(item.provenance?.created_at || "")}</span>
      <div><button class="text-button" data-pattern-target="${escapeAttr(target.key)}">Compare patterns for target</button>
      <button class="text-button" data-pattern-key="${escapeAttr(pattern.key)}">Find this pattern elsewhere</button>
      <button class="text-button" data-candidate-key="${escapeAttr(pattern.key)}">Explain skipped candidates</button></div></div>
  </article>`;
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

function scoreCell(name, value) {
  const score = Number(value || 0);
  const band = score >= 70 ? "high" : score >= 40 ? "medium" : "low";
  return `<div class="pattern-score" data-score-band="${band}"><span>${escapeHtml(humanize(name))}</span><strong>${score}</strong></div>`;
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
