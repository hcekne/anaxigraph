import {
  escapeAttr,
  escapeHtml,
  format,
  humanize,
} from "/assets/dashboard-core.js";
import { storyList, storyText } from "/assets/dashboard-format.js";

export function renderEvaluationCard(item) {
  const target = item.target || {};
  const pattern = item.pattern || {};
  const review = item.review || {};
  const language = patternLanguage(item);
  return `<article class="panel pattern-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family)} · ${escapeHtml(humanize(pattern.kind))}</p>
      <h2>${escapeHtml(pattern.name)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge recommendation">${escapeHtml(recommendationLabel(item.recommendation))}</span>
      <span class="pattern-badge">${escapeHtml(presenceLabel(item.presence))}</span></div></div>
    ${targetMarkup(target)}
    <div class="pattern-conclusion"><strong>Conclusion</strong><p>${escapeHtml(language.conclusion)}</p></div>
    <div class="pattern-story-grid">
      ${storyText("What this pattern name means", language.what_the_pattern_name_means)}
      ${storyList("What AnaxiGraph saw", language.what_anaxigraph_saw)}
      ${storyText("Why this may matter", language.why_it_may_matter)}
      ${storyText("What to do", language.what_to_do)}
      ${storyList("Reasons not to change the code", language.reasons_not_to_change_the_code)}
      ${storyList("How to check the result", language.how_to_check)}
    </div>
    <div class="pattern-score-story">${(language.score_meanings || []).map(scoreMeaning).join("")}</div>
    <div class="pattern-review"><div><strong>Second AI check · ${escapeHtml(reviewLabel(review.verdict))}</strong>
      <span>${escapeHtml(language.independent_review || review.summary || "A separate AI pass completed its check.")}</span></div></div>
    ${item.details ? evaluationDetails(item.details) : ""}
    <div class="pattern-result-footer"><span>Created by ${escapeHtml(item.provenance?.provider || "an unknown AI provider")} using ${escapeHtml(item.provenance?.model || "the worker's runtime model")}${item.provenance?.created_at ? ` · saved ${escapeHtml(item.provenance.created_at)}` : ""}</span>
      <div><button class="text-button" data-pattern-target="${escapeAttr(target.key)}">Compare patterns for this code</button>
      <button class="text-button" data-pattern-key="${escapeAttr(pattern.key)}">Find this pattern elsewhere</button>
      <button class="text-button" data-candidate-key="${escapeAttr(pattern.key)}">Explain skipped candidates</button></div></div>
  </article>`;
}

function patternLanguage(item) {
  if (item.plain_language) return item.plain_language;
  return {
    conclusion: "This result does not include the current plain-language explanation contract.",
    what_the_pattern_name_means: "The older response does not explain this pattern name.",
    what_anaxigraph_saw: [],
    why_it_may_matter: "The older response is incomplete, so its recommendation is not safe to use by itself.",
    what_to_do: "Query the current AnaxiGraph service for a complete pattern explanation.",
    reasons_not_to_change_the_code: ["Do not refactor from an incomplete pattern response."],
    how_to_check: ["Confirm the response includes pattern-explanation-v2 before acting."],
    score_meanings: [],
    independent_review: item.review?.summary || "A separate AI pass completed its check.",
  };
}

function scoreMeaning(item) {
  const values = Object.entries(item.scores || {}).map(([name, value]) => (
    `${scoreLabel(name)} ${format.format(Number(value || 0))} out of 100`
  )).join(" · ");
  return `<section><strong>${escapeHtml(item.label)}</strong><p>${escapeHtml(item.meaning)}</p><span>${escapeHtml(values)}</span></section>`;
}

export function renderCandidateCard(item, pattern) {
  const target = item.target || {};
  const reason = item.reason || "unknown";
  const selected = Boolean(item.selected_for_evaluation);
  const status = selected ? "selected" : "skipped";
  const language = candidateLanguage(item);
  return `<article class="panel pattern-result-card candidate-result-card">
    <div class="pattern-result-heading"><div><p class="eyebrow">${escapeHtml(pattern.family || "pattern library")} · why this code was considered</p>
      <h2>${escapeHtml(pattern.name || pattern.key)}</h2><code>${escapeHtml(pattern.key)}</code></div>
      <div class="pattern-verdicts"><span class="pattern-badge ${selected ? "recommendation" : ""}">${status}</span>
      <span class="pattern-badge">${escapeHtml(reasonLabel(reason))}</span></div></div>
    ${targetMarkup(target)}
    <div class="pattern-conclusion"><strong>Conclusion</strong><p>${escapeHtml(language.conclusion)}</p></div>
    <div class="pattern-story-grid candidate-story">
      ${storyList("Why AnaxiGraph considered this pair", language.why_this_pair_was_considered)}
      ${storyText("Why it was selected or skipped", language.why_it_was_selected_or_skipped)}
      ${storyList("What AnaxiGraph found", language.what_anaxigraph_found)}
      ${storyList("What AnaxiGraph could not check", language.what_anaxigraph_could_not_check)}
      ${storyText("What happens next", language.what_happens_next)}
    </div>
    <div class="pattern-candidate-rank">${escapeHtml(language.queue_rank?.meaning || "No selection-order explanation was supplied.")}</div>
    ${item.details ? candidateDetails(item.details) : ""}
    <div class="pattern-result-footer"><span>Repeatable code checks selected or skipped this possible match; an AI has not judged it yet.</span>
      <div><button class="text-button" data-evaluation-target="${escapeAttr(target.key)}"
        data-evaluation-key="${escapeAttr(pattern.key)}">Look for a completed pattern result</button></div></div>
  </article>`;
}

function candidateLanguage(item) {
  if (item.plain_language) return item.plain_language;
  return {
    conclusion: "This candidate response does not include the current plain-language explanation.",
    why_this_pair_was_considered: [],
    why_it_was_selected_or_skipped: "The older response is incomplete.",
    what_anaxigraph_found: [],
    what_anaxigraph_could_not_check: ["The missing explanation makes this result unsafe to act on."],
    what_happens_next: "Query the current AnaxiGraph service before making a design change.",
    queue_rank: { meaning: "No trustworthy selection-order explanation was supplied." },
  };
}

function targetMarkup(target) {
  return `<div class="pattern-target"><div><strong>${escapeHtml(target.label)}</strong>
    <span>${escapeHtml(target.path || target.qualified_name || target.key)}</span></div>
    <span class="pattern-level">${escapeHtml(levelLabel(target.level))}</span></div>`;
}

function evaluationDetails(details) {
  const lists = [
    ["Evidence supporting this result", "evidence"],
    ["Evidence against this result", "counter_evidence"],
    ["Other patterns or approaches to consider", "alternatives"],
    ["What must be true before changing code", "prerequisites"],
    ["What could go wrong", "risks"],
  ];
  const sections = lists.map(([label, name]) => textGroup(label, details[name])).join("");
  const issues = (details.review_issues || []).map((issue) => (
    `<li><strong>${escapeHtml(humanize(issue.kind))}</strong> · ${escapeHtml(issue.explanation)}</li>`
  )).join("");
  return `<details class="pattern-details"><summary>Detailed evidence and changes made by the second AI check</summary>
    <div class="pattern-evidence-grid">${sections}${issues ? `<section><h3>Problems the second AI pass found</h3><ul>${issues}</ul></section>` : ""}</div></details>`;
}

function candidateDetails(details) {
  const signals = (details.signals || []).map(signalDetail).join("");
  const capabilities = (details.capabilities || []).map(capabilityDetail).join("");
  return `<details class="pattern-details"><summary>How AnaxiGraph checked this evidence</summary>
    <div class="pattern-evidence-grid">
      ${signals ? `<section><h3>Code observations</h3><ul>${signals}</ul></section>` : ""}
      ${capabilities ? `<section><h3>Information available to the check</h3><ul>${capabilities}</ul></section>` : ""}
      ${textGroup("Questions for the AI evaluation", details.semantic_questions)}
    </div></details>`;
}

function signalDetail(signal) {
  const language = signal.plain_language || {};
  const feature = humanize(signal.feature || "repository evidence");
  const checked = language.what_was_checked
    || `AnaxiGraph checked ${feature} using its ${humanize(signal.operator || "catalog")} rule.`;
  const found = language.what_was_found
    || `The recorded result was ${humanize(signal.outcome || "unknown")}.`;
  const effect = language.how_it_affected_selection
    || "This older response does not explain how the observation affected selection.";
  const strength = language.evidence_strength?.meaning
    || "This older response does not explain how strongly the observation is supported.";
  return `<li><strong>${escapeHtml(feature)}</strong><p>${escapeHtml(checked)}</p>
    <p>${escapeHtml(found)} ${escapeHtml(effect)}</p><p>${escapeHtml(strength)}</p></li>`;
}

function capabilityDetail(item) {
  const language = item.plain_language || {};
  const fact = humanize(item.fact || "required code information");
  const conclusion = language.conclusion
    || `AnaxiGraph checked whether enough ${fact} detail was available.`;
  const requirement = language.required_detail
    || `This response requires ${humanize(item.minimum || "an expected")} detail.`;
  const available = language.available_detail
    || `The best available detail was ${humanize(item.best_level || "unavailable")}.`;
  const use = language.how_to_use_this
    || "This older response does not explain whether the information was complete enough to use.";
  return `<li><strong>${escapeHtml(fact)}</strong><p>${escapeHtml(conclusion)}</p>
    <p>${escapeHtml(requirement)} ${escapeHtml(available)}</p><p>${escapeHtml(use)}</p></li>`;
}

function textGroup(name, values) {
  if (!values?.length) return "";
  return `<section><h3>${escapeHtml(name)}</h3><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}

function recommendationLabel(value) {
  return ({
    retain: "Keep the current pattern",
    introduce: "Consider adding this pattern",
    improve_conformance: "Make the existing pattern more consistent",
    replace: "Consider a different pattern",
    avoid: "Do not use this pattern here",
    no_action: "No code change suggested",
    insufficient_evidence: "Not enough evidence",
  })[value] || humanize(value || "No suggested action");
}

function presenceLabel(value) {
  return ({ present: "Clearly present", partial: "Partly present", absent: "Not present", uncertain: "Not enough evidence" })[value]
    || humanize(value || "Presence unknown");
}

function reviewLabel(value) {
  return ({ approve: "agreed", revise: "corrected the first result", retain_competing: "kept a supported disagreement" })[value]
    || "complete";
}

function levelLabel(value) {
  return ({ symbol: "function or method", type: "class, interface, or type", module: "file", subsystem: "smaller repository area", area: "broad repository area", repository: "whole repository" })[value]
    || humanize(value || "code");
}

function scoreLabel(value) {
  return ({
    problem_match: "Evidence that the problem exists",
    pattern_fit: "How well the pattern fits",
    current_match: "How much of the pattern is already present",
    value_of_change: "Evidence that a change would help",
    expected_benefit: "Likely benefit",
    urgency: "Need to act soon",
    execution_safety: "Safety of making the change in small steps",
    migration_cost: "Work and disruption required",
    evidence_strength: "Support for this result",
  })[value] || humanize(value);
}

function reasonLabel(value) {
  return ({
    selected: "Selected for an AI check",
    no_positive_evidence: "No supporting code evidence",
    counter_evidence: "Evidence points away from this pattern",
    below_priority: "Other possible matches ranked higher",
    sparse_plan_bound: "Available AI tasks were filled",
    plan_not_ready: "AnaxiGraph is still choosing AI tasks",
  })[value] || "Not selected for an AI check";
}
