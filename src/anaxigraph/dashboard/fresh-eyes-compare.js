import {
  api,
  byId,
  escapeHtml,
  humanize,
  request,
  state,
  toast,
} from "/assets/dashboard-core.js";

const TIMING = "Stage wall time and output";
const RANKED = "Recommendations in rank order";
const REJECTED = "Ideas the mission filter rejected";

export function resetComparison() {
  const select = byId("fresh-eyes-compare");
  if (select) select.value = "";
  const panel = byId("fresh-eyes-compare-panel");
  if (panel) panel.innerHTML = "";
}

export function renderComparison(payload, leftSelection) {
  const select = byId("fresh-eyes-compare");
  const label = byId("fresh-eyes-compare-label");
  const panel = byId("fresh-eyes-compare-panel");
  if (!select || !label || !panel) return;
  const numbers = generationNumbers(payload);
  const chosen = numbers.includes(Number(select.value)) ? select.value : "";
  label.hidden = numbers.length < 2;
  select.innerHTML = optionsMarkup(numbers, payload.review_generation);
  select.value = chosen;
  if (label.hidden || chosen === "") panel.innerHTML = "";
  else if (Number(chosen) === Number(payload.review_generation)) {
    panel.innerHTML = noticeMarkup(chosen);
  } else loadComparison(panel, leftSelection, Number(chosen));
}

async function loadComparison(panel, leftSelection, number) {
  const token = state.repositoryLoadToken;
  panel.innerHTML = '<article class="panel"><p class="muted">Reading both generations…</p></article>';
  try {
    const [left, right] = await Promise.all([
      request(api("/api/fresh-eyes", { generation: leftSelection, compare_with: number })),
      request(api("/api/fresh-eyes", { generation: number })),
    ]);
    if (token !== state.repositoryLoadToken) return;
    panel.innerHTML = comparisonMarkup(left, right);
  } catch (error) {
    if (token !== state.repositoryLoadToken) return;
    panel.innerHTML = "";
    toast(error.message, true);
  }
}

function generationNumbers(payload) {
  return [...new Set((payload.generations || []).map((item) => Number(item.generation)))]
    .filter((number) => Number.isFinite(number)).sort((one, other) => other - one);
}

function optionsMarkup(numbers, leftGeneration) {
  const options = numbers.map((number) => {
    const text = `Generation ${number}${number === Number(leftGeneration) ? " · already shown" : ""}`;
    return `<option value="${number}">${escapeHtml(text)}</option>`;
  });
  return ['<option value="">Off</option>', ...options].join("");
}

function noticeMarkup(number) {
  return `<article class="panel fresh-compare"><p class="eyebrow">Nothing to compare</p>
    <h2>Both sides name generation ${escapeHtml(number)}</h2>
    <p class="fresh-compare-notice">Pick a different generation on one side. A review compared with
      itself repeats one column twice and reports a perfect agreement that means nothing.</p></article>`;
}

function comparisonMarkup(left, right) {
  return `<article class="panel fresh-compare">
    <p class="eyebrow">Side by side · evidence, not a verdict</p>
    <h2>Generation ${escapeHtml(left.review_generation)} beside generation
      ${escapeHtml(right.review_generation)}</h2>
    <p class="panel-copy">Two recorded reviews of the same software, read next to each other. Nothing
      below says which generation was right; it says where the two agree, where they clash, and what
      only one of them saw.</p>
    ${alignmentMarkup(left.alignment)}
    <div class="fresh-compare-columns">${columnMarkup(left)}${columnMarkup(right)}</div></article>`;
}

function columnMarkup(payload) {
  return `<section class="fresh-compare-column">
    <h3>Generation ${escapeHtml(payload.review_generation ?? "unrecorded")}</h3>
    <p class="fresh-compare-note">${escapeHtml(humanize(payload.state))}</p>
    ${factsMarkup(payload)}${stageBlock(payload.stages || [])}
    ${recommendationBlock(payload.recommendations || [])}
    ${rejectedBlock(payload.strategy?.rejected_ideas || [])}
    ${disagreementList(payload.adjudication)}</section>`;
}

function disagreementList(adjudication) {
  const topics = (adjudication?.disagreements || [])
    .map((item) => ({ title: item.topic })).filter((item) => item.title);
  return soloList("Disagreements the adjudicator preserved", topics);
}

function factsMarkup(payload) {
  const rows = [
    ["Snapshot", snapshotText(payload)],
    ["Executor models", executorModels(payload).join(", ") || "No executor model recorded"],
    ["Provider diversity", diversityText(payload.diversity || {})],
    ["Summary confidence", confidenceText(payload.strategy)],
  ];
  return `<dl class="fresh-compare-facts">${rows.map(([term, value]) => (
    `<div><dt>${escapeHtml(term)}</dt><dd>${escapeHtml(value)}</dd></div>`)).join("")}</dl>`;
}

function snapshotText(payload) {
  const snapshot = payload.snapshot;
  const identifier = payload.snapshot_id ?? snapshot?.snapshot_id;
  const commit = snapshot?.commit_sha ? [`commit ${String(snapshot.commit_sha).slice(0, 12)}`] : [];
  const checkout = snapshot
    ? (snapshot.dirty ? "dirty checkout" : "clean checkout")
    : "checkout state not recorded for this generation";
  const scan = identifier ? `Saved scan ${identifier}` : "Saved scan not recorded";
  return [scan, ...commit, checkout].join(" · ");
}

function executorModels(payload) {
  const recorded = (payload.stages || [])
    .map((stage) => stage.provenance?.executor_model).filter(Boolean);
  const models = recorded.length ? recorded : (payload.diversity?.models || []);
  return [...new Set(models.map(String))].sort();
}

function confidenceText(strategy) {
  const confidence = Number(strategy?.confidence);
  return Number.isFinite(confidence)
    ? `${Math.round(confidence * 100)}% in the ranked strategy`
    : "Not reported";
}

function diversityText(diversity) {
  const count = Number(diversity.proposal_count || 0);
  if (!count) return "No proposals recorded";
  const families = (diversity.executor_families || []).filter((item) => item !== "unspecified");
  const origin = families.length ? ` from ${families.join(" and ")}` : "";
  const provider = diversity.cross_provider
    ? "different providers are recorded"
    : "not cross-provider agreement";
  return `${count} proposal${count === 1 ? "" : "s"}${origin} · ${provider}`;
}

function stageBlock(stages) {
  const rows = stages.filter((stage) => stage.telemetry).map(stageRow);
  if (!rows.length) return emptyBlock(TIMING, "No per-stage telemetry was recorded here.");
  return `${heading(TIMING)}<ul class="fresh-compare-stages">${rows.join("")}</ul>`;
}

function stageRow(stage) {
  const facts = [
    stage.telemetry.duration_ms ? duration(stage.telemetry.duration_ms) : "",
    stage.telemetry.output_bytes ? `${bytes(stage.telemetry.output_bytes)} written` : "",
  ].filter(Boolean).join(" · ");
  return `<li><span>${escapeHtml(stage.label)}</span><span class="fresh-compare-metric">
    ${escapeHtml(facts || "no wall time or output recorded")}</span></li>`;
}

function recommendationBlock(recommendations) {
  if (!recommendations.length) return emptyBlock(RANKED, "No ranked advice was recorded.");
  const items = [...recommendations]
    .sort((one, other) => Number(one.rank || 0) - Number(other.rank || 0))
    .map((item) => `<li><span class="fresh-compare-rank">${escapeHtml(item.rank)}</span>
      <div><strong>${escapeHtml(item.title)}</strong>
      <small>${escapeHtml(recommendationFacts(item))}</small></div></li>`);
  return `${heading(RANKED)}<ol class="fresh-compare-recommendations">${items.join("")}</ol>`;
}

function recommendationFacts(item) {
  const confidence = `${Math.round(Number(item.confidence || 0) * 100)}% confidence`;
  return [humanize(item.action), confidence].filter(Boolean).join(" · ");
}

function rejectedBlock(ideas) {
  if (!ideas.length) return emptyBlock(REJECTED, "No rejected ideas were recorded.");
  return `${heading(REJECTED)}<ul class="fresh-compare-rejected">${ideas.map((item) => (
    `<li><strong>${escapeHtml(item.idea)}</strong> ${escapeHtml(item.reason || "")}</li>`
  )).join("")}</ul>`;
}

function alignmentMarkup(alignment) {
  if (!alignment) return "";
  const left = alignment.left?.review_generation;
  const right = alignment.right?.review_generation;
  return `<section class="fresh-compare-alignment">
    <h3>Where the two generations line up</h3>
    <p class="fresh-compare-note">Matched by ${escapeHtml(alignment.method || "lexical")} signals
      only: normalized words, quoted file names, and the recorded action.</p>
    <div class="fresh-compare-badges">${badge("Agreed", alignment.aligned)}
      ${badge("Conflicting", alignment.conflicting)}
      ${badge(`Only in ${left}`, alignment.unmatched_left)}
      ${badge(`Only in ${right}`, alignment.unmatched_right)}</div>
    ${pairList("Recommendations both generations made", alignment.aligned)}
    ${pairList("Recommendations that clash", alignment.conflicting)}
    ${soloList(`Only generation ${left} recommended`, alignment.unmatched_left)}
    ${soloList(`Only generation ${right} recommended`, alignment.unmatched_right)}
    ${caveatList(alignment.caveats)}</section>`;
}

function badge(label, entries) {
  return `<span class="fresh-compare-badge">${escapeHtml(label)}
    <strong>${(entries || []).length}</strong></span>`;
}

function pairList(title, entries) {
  if (!(entries || []).length) return "";
  return `${heading(title)}<ul class="fresh-compare-pairs">${entries.map((entry) => (
    `<li><strong>${escapeHtml(entry.left.title)}</strong>
      <span class="fresh-compare-versus">beside</span>
      <strong>${escapeHtml(entry.right.title)}</strong>
      <small>${escapeHtml(entry.detail || pairActions(entry))}</small></li>`
  )).join("")}</ul>`;
}

function pairActions(entry) {
  const action = entry.left.action || entry.right.action;
  return action
    ? `Both generations chose ${humanize(action).toLowerCase()}.`
    : "Both generations propose this change.";
}

function soloList(title, entries) {
  if (!(entries || []).length) return "";
  return `${heading(title)}<ul class="fresh-compare-solo">${entries.map((entry) => (
    `<li>${escapeHtml(entry.title)}</li>`)).join("")}</ul>`;
}

function caveatList(caveats) {
  if (!(caveats || []).length) return "";
  return `<div class="fresh-compare-caveats">${heading("What this alignment cannot tell you")}
    <ul>${caveats.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("")}</ul></div>`;
}

function heading(title) {
  return `<h4>${escapeHtml(title)}</h4>`;
}

function emptyBlock(title, message) {
  return `${heading(title)}<p class="muted fresh-compare-empty">${escapeHtml(message)}</p>`;
}

export function duration(milliseconds) {
  const seconds = Math.max(0, Number(milliseconds || 0)) / 1000;
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

export function bytes(value) {
  const size = Math.max(0, Number(value || 0));
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / 1024 ** 2).toFixed(1)} MiB`;
}
