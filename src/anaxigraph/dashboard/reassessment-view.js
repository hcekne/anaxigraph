import {
  byId,
  escapeHtml,
  format,
  humanize,
  state,
} from "/assets/dashboard-core.js";

export function setupReassessmentView() {
  if (byId("architecture-reassessment")) return;
  installStylesheet();
  const article = document.createElement("article");
  article.id = "architecture-reassessment";
  article.className = "panel reassessment-panel";
  byId("view-history").prepend(article);
  renderReassessment();
}

export function renderReassessment() {
  const element = byId("architecture-reassessment");
  if (!element) return;
  const value = state.reassessment;
  if (!value) {
    element.innerHTML = `<p class="eyebrow">Continuous architecture sidekick</p>
      <h2>Checking the latest saved change…</h2>`;
    return;
  }
  const language = value.plain_language || {};
  element.innerHTML = `<div class="reassessment-heading"><div>
      <p class="eyebrow">Continuous architecture sidekick</p>
      <h2>What changed—and should the architecture change with it?</h2>
      <p class="panel-copy">${escapeHtml(language.conclusion || fallbackConclusion(value))}</p>
    </div>${stateBadge(value.state)}</div>
    ${snapshotComparison(value)}
    ${refreshScope(value.semantic_refresh || {})}
    <div class="reassessment-effects">${effectCards(value.architectural_effects || [])}</div>
    ${safeConclusion(value)}`;
}

function installStylesheet() {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/assets/reassessment.css";
  link.dataset.reassessmentStyles = "true";
  document.head.append(link);
}

function stateBadge(value) {
  return `<span class="reassessment-state state-${escapeHtml(value)}">${escapeHtml(humanize(value))}</span>`;
}

function snapshotComparison(value) {
  const baseline = value.baseline_snapshot;
  const target = value.target_snapshot;
  if (!target) return "";
  if (!baseline) {
    return `<p class="reassessment-baseline">Current map #${escapeHtml(target.id)} has no earlier
      compatible map yet. The next real change becomes comparable automatically.</p>`;
  }
  const changed = Number(value.evidence_work?.changed_modules || 0);
  const affected = Number(value.evidence_work?.affected_context_modules || 0);
  return `<div class="reassessment-comparison">
    <span><strong>${escapeHtml(shortCommit(baseline))}</strong><small>Earlier saved map</small></span>
    <i>→</i><span><strong>${escapeHtml(shortCommit(target))}</strong><small>Current saved map</small></span>
    <span><strong>${format.format(changed)}</strong><small>Changed files</small></span>
    <span><strong>${format.format(affected)}</strong><small>Bounded context files</small></span>
  </div>`;
}

function shortCommit(snapshot) {
  const sha = String(snapshot.commit_sha || "working tree");
  return sha === "working tree" ? sha : sha.slice(0, 10);
}

function refreshScope(value) {
  const changed = value.changed_modules || [];
  const affected = value.affected_modules || [];
  const groups = value.affected_groups || [];
  if (!changed.length && !affected.length && !groups.length) return "";
  const readiness = value.semantically_ready
    ? "Affected AI descriptions and the Architecture Charter are current."
    : value.enabled
      ? "Only affected AI descriptions and Charter sections are queued or refreshing."
      : "Static comparison is current; optional AI descriptions are disabled.";
  return `<details class="reassessment-scope"><summary>${escapeHtml(readiness)}</summary>
    ${pathList("Changed files", changed)}${pathList("Context checked again", affected)}
    ${pathList("Responsibility groups checked again", groups)}
    <p>No repository-wide semantic rerun is required.</p></details>`;
}

function pathList(label, values) {
  if (!values.length) return "";
  return `<div><strong>${escapeHtml(label)}</strong><ul>${values.slice(0, 20).map((value) => (
    `<li><code>${escapeHtml(value)}</code></li>`
  )).join("")}</ul></div>`;
}

function effectCards(effects) {
  if (!effects.length) {
    return `<div class="reassessment-empty"><strong>No supported architecture change</strong>
      <p>The compatible maps do not justify a structural rewrite. Keep the design coherent and
      check behavior instead.</p></div>`;
  }
  return effects.slice(0, 10).map(effectCard).join("");
}

function effectCard(effect) {
  const confidence = effect.confidence || {};
  return `<article class="reassessment-effect effect-${escapeHtml(effect.classification)}">
    <div class="effect-heading"><div><span>${escapeHtml(humanize(effect.category))}</span>
      <h3>${escapeHtml(effect.subject)}</h3></div>
      <small>${escapeHtml(humanize(effect.classification))} · ${escapeHtml(confidence.label || "limited")} confidence</small></div>
    ${statement("What changed", effect.observed_change)}
    ${statement("Why it may matter", effect.architectural_consequence)}
    ${statement("Recommendation", effect.recommendation, "recommendation")}
    ${stringList("Counter-evidence", effect.counter_evidence)}
    ${stringList("Reasons to leave it alone", effect.reasons_to_leave_alone)}
    <div class="effect-follow-up">${statement("Smallest safe next step", effect.smallest_safe_follow_up)}
      ${statement("How to check", effect.verification)}</div>
  </article>`;
}

function statement(label, value, className = "") {
  if (!value) return "";
  return `<div class="effect-statement ${className}"><strong>${escapeHtml(label)}</strong>
    <p>${escapeHtml(value)}</p></div>`;
}

function stringList(label, values = []) {
  if (!values.length) return "";
  return `<div class="effect-list"><strong>${escapeHtml(label)}</strong><ul>${values.map((value) => (
    `<li>${escapeHtml(value)}</li>`
  )).join("")}</ul></div>`;
}

function safeConclusion(value) {
  const safety = value.safety || {};
  return `<p class="reassessment-safety"><strong>Advice, not an automatic edit.</strong>
    AnaxiGraph did not change the repository or create an approval workflow. Test the smallest
    coherent step, refresh the map, and ask again.</p>`;
}

function fallbackConclusion(value) {
  return value.state === "no_compatible_baseline"
    ? "No earlier compatible saved map is available yet."
    : "AnaxiGraph compared the latest compatible saved maps.";
}
