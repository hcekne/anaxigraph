import {
  api,
  byId,
  escapeHtml,
  humanize,
  request,
  state,
  toast,
} from "/assets/dashboard-core.js";

let current = null;
let loadedRepositoryId = null;
let selectedGeneration = "";
let liveGeneration = null;

export function setupFreshEyesView() {
  if (byId("view-fresh-eyes")) return;
  installStylesheet();
  const section = document.createElement("section");
  section.id = "view-fresh-eyes";
  section.className = "view";
  section.innerHTML = markup();
  (byId("view-patterns") || byId("view-architecture")).after(section);
  bindEvents();
  renderWaiting();
}

export function resetFreshEyesView() {
  current = null;
  loadedRepositoryId = null;
  selectedGeneration = "";
  liveGeneration = null;
  renderWaiting();
  if (byId("view-fresh-eyes")?.classList.contains("active")) {
    window.setTimeout(loadFreshEyes, 0);
  }
}

function installStylesheet() {
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/assets/fresh-eyes.css";
  link.dataset.freshEyesStyles = "true";
  document.head.append(link);
}

function markup() {
  return `
    <article class="panel fresh-eyes-intro">
      <div><p class="eyebrow">Fresh eyes without architectural amnesia</p>
        <h2>Compare today’s system with a clean-sheet design</h2>
        <p class="panel-copy">Independent agents receive only the software’s behavior and
          constraints. A blind adjudicator combines their strongest ideas. Only then does a
          repository-aware pass compare that reference with the code and keep changes that
          materially advance the mission.</p></div>
      <div class="fresh-eyes-start"><label>Independent proposals
        <select id="fresh-eyes-proposal-count"><option value="1">1 · lower cost</option>
          <option value="2" selected>2 · recommended</option><option value="3">3 · broader</option>
        </select></label><button id="fresh-eyes-start" class="button" type="button">
          Start fresh-eyes review</button></div>
    </article>
    <article class="panel"><div class="fresh-eyes-heading"><div>
      <p class="eyebrow">Resumable agent-funded review</p><h2 id="fresh-eyes-title">Not started</h2>
      </div><div class="fresh-eyes-controls">
      <label id="fresh-eyes-generation-label" hidden>Generation
        <select id="fresh-eyes-generation"></select></label>
      <button id="fresh-eyes-refresh" class="secondary-button" type="button">Refresh</button>
      </div></div><div id="fresh-eyes-snapshot"></div>
      <p id="fresh-eyes-summary" class="panel-copy"></p>
      <div id="fresh-eyes-stages" class="fresh-eyes-stages"></div>
      <div id="fresh-eyes-diversity" class="fresh-eyes-diversity"></div></article>
    <div id="fresh-eyes-recommendations" class="fresh-eyes-recommendations"></div>
    <article id="fresh-eyes-details" class="panel fresh-eyes-details"></article>`;
}

function bindEvents() {
  window.addEventListener("anaxigraph:viewchange", (event) => {
    if (event.detail?.name === "fresh-eyes" && loadedRepositoryId !== state.repositoryId) {
      loadFreshEyes();
    }
  });
  byId("fresh-eyes-refresh").addEventListener("click", loadFreshEyes);
  byId("fresh-eyes-start").addEventListener("click", startFreshEyes);
  byId("fresh-eyes-generation").addEventListener("change", (event) => {
    selectedGeneration = event.target.value;
    loadFreshEyes();
  });
}

async function loadFreshEyes() {
  const token = state.repositoryLoadToken;
  setBusy(true);
  try {
    const value = await request(api("/api/fresh-eyes", { generation: selectedGeneration }));
    if (token !== state.repositoryLoadToken) return;
    if (selectedGeneration === "") liveGeneration = value.review_generation ?? null;
    current = value;
    loadedRepositoryId = state.repositoryId;
    render(value);
  } catch (error) {
    if (token === state.repositoryLoadToken) toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

async function startFreshEyes() {
  const token = state.repositoryLoadToken;
  setBusy(true);
  try {
    const response = await request("/api/fresh-eyes", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        repository_id: state.repositoryId,
        proposal_count: Number(byId("fresh-eyes-proposal-count").value),
        retry_failed: current?.state === "failed",
      }),
    });
    if (token !== state.repositoryLoadToken) return;
    current = response.review;
    loadedRepositoryId = state.repositoryId;
    render(current);
    toast(response.status === "started" ? "Fresh-eyes review started." : "Review already active.");
  } catch (error) {
    if (token === state.repositoryLoadToken) toast(error.message, true);
  } finally {
    setBusy(false);
  }
}

function render(value) {
  const ready = value.ready === true;
  byId("fresh-eyes-title").textContent = stateLabel(value.state);
  byId("fresh-eyes-summary").textContent = value.strategy?.summary
    || value.next_action || "No review has been requested for this saved scan.";
  renderGenerationControl(value);
  byId("fresh-eyes-snapshot").innerHTML = snapshotWarning(value.snapshot);
  renderStartControl(value, ready);
  byId("fresh-eyes-stages").innerHTML = stageMarkup(value.stages || []);
  byId("fresh-eyes-diversity").innerHTML = diversityMarkup(value.diversity || {});
  byId("fresh-eyes-recommendations").innerHTML = recommendationMarkup(value);
  byId("fresh-eyes-details").innerHTML = detailMarkup(value);
}

function renderGenerationControl(value) {
  const label = byId("fresh-eyes-generation-label");
  const select = byId("fresh-eyes-generation");
  const numbers = [...new Set((value.generations || []).map((item) => Number(item.generation)))]
    .sort((left, right) => right - left);
  label.hidden = numbers.length < 2 && liveGeneration != null;
  const options = numbers.map((number) => {
    const live = number === liveGeneration;
    const text = `Generation ${number} · ${live ? "current" : "recorded"}`;
    return `<option value="${live ? "" : number}">${escapeHtml(text)}</option>`;
  });
  if (liveGeneration === null) options.unshift('<option value="">Current review</option>');
  select.innerHTML = options.join("");
  select.value = selectedGeneration;
}

function renderStartControl(value, ready = value.ready === true) {
  const live = selectedGeneration === "";
  const canStart = live && ["not_started", "stale", "failed"].includes(value.state);
  byId("fresh-eyes-start").textContent = !live ? "Reading a recorded generation"
    : value.state === "failed" ? "Retry failed stage"
      : ["not_started", "stale"].includes(value.state) ? "Start fresh-eyes review"
        : ready ? "Review complete" : "Review in progress";
  byId("fresh-eyes-start").disabled = !canStart;
  byId("fresh-eyes-proposal-count").disabled = !canStart
    || !["not_started", "stale"].includes(value.state);
}

function snapshotWarning(snapshot) {
  if (!snapshot?.dirty) return "";
  const commit = snapshot.commit_sha
    ? String(snapshot.commit_sha).slice(0, 12)
    : "an unrecorded commit";
  const fingerprint = snapshot.working_tree_fingerprint;
  const traced = fingerprint
    ? `working-tree fingerprint ${String(fingerprint).slice(0, 12)}`
    : "no working-tree fingerprint was recorded";
  return `<p class="fresh-eyes-warning">Produced from a dirty checkout of
    ${escapeHtml(commit)} (uncommitted changes; ${escapeHtml(traced)}). Another model given only
    that commit would not read the same code, so this review cannot be compared as reproduced.</p>`;
}

function stageMarkup(stages) {
  if (!stages.length) return '<p class="muted">The five-stage recipe appears here after it starts.</p>';
  return stages.map((stage, index) => {
    const stateName = stage.state === "current" ? "complete"
      : String(stage.state).startsWith("failed") ? "failed"
        : String(stage.state).startsWith("pending") ? "active" : "waiting";
    return `<div class="fresh-stage ${stateName}"><span>${stage.state === "current" ? "✓" : index + 1}</span>
      <div><strong>${escapeHtml(stage.label)}</strong><small>${escapeHtml(stage.reason)}</small>
      ${telemetryMarkup(stage.telemetry)}</div></div>`;
  }).join("");
}

function telemetryMarkup(telemetry) {
  if (!telemetry) return "";
  const attempts = Number(telemetry.attempts_observed || 0);
  const facts = [
    telemetry.duration_ms ? duration(telemetry.duration_ms) : "",
    telemetry.output_bytes ? `${bytes(telemetry.output_bytes)} written` : "",
    tokenText(telemetry),
    attempts ? `${attempts} attempt${attempts === 1 ? "" : "s"} observed` : "",
  ].filter(Boolean);
  if (!facts.length) return "";
  return `<small class="fresh-stage-telemetry">${escapeHtml(facts.join(" · "))}</small>`;
}

function tokenText(telemetry) {
  if (!telemetry.token_counts_reported) return "tokens not reported";
  const counts = `${telemetry.input_tokens} in / ${telemetry.output_tokens} out tokens`;
  return telemetry.input_tokens_plausible ? counts : `${counts} (input count implausible)`;
}

function duration(milliseconds) {
  const seconds = Math.max(0, Number(milliseconds || 0)) / 1000;
  if (seconds < 1) return `${Math.round(seconds * 1000)} ms`;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

function bytes(value) {
  const size = Math.max(0, Number(value || 0));
  if (size < 1024) return `${size} B`;
  if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KiB`;
  return `${(size / 1024 ** 2).toFixed(1)} MiB`;
}

function diversityMarkup(diversity) {
  const count = Number(diversity.proposal_count || 0);
  if (!count) return "";
  const families = (diversity.executor_families || []).filter((item) => item !== "unspecified");
  const familyText = families.length ? `Proposals from ${families.join(" and ")}. ` : "";
  const providerText = diversity.cross_provider
    ? `${familyText}Different providers are recorded.`
    : `${familyText}This is not cross-provider agreement.`;
  return `<strong>${count} proposal${count === 1 ? "" : "s"}</strong><span>${escapeHtml(providerText)}
    ${escapeHtml((diversity.models || []).join(", ") || "Model not reported")}</span>`;
}

function recommendationMarkup(value) {
  const recommendations = value.recommendations || [];
  if (!recommendations.length) {
    return `<article class="panel"><p class="eyebrow">Ranked strategy</p><h2>No final advice yet</h2>
      <p class="muted">Partial clean-sheet proposals are deliberately not shown as a refactor plan.
      ${escapeHtml(value.next_action || "")}</p></article>`;
  }
  return recommendations.map((item) => `<article class="panel fresh-recommendation">
    <div class="fresh-rank">${item.rank}</div><div><p class="eyebrow">${escapeHtml(humanize(item.action))}
      · ${Math.round(Number(item.confidence || 0) * 100)}% confidence</p>
      <h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.smallest_change)}</p>
      <p class="fresh-benefit"><strong>Expected benefit</strong> ${escapeHtml(item.expected_benefit)}</p>
      ${groundingMarkup(item.grounding)}
      ${stringList("Reasons not to proceed", item.reasons_not_to_proceed)}
      ${stringList("How to verify", item.verification)}</div></article>`).join("");
}

function groundingMarkup(grounding) {
  if (!grounding) return "";
  const unresolved = (grounding.checks || []).filter((check) => check.result !== "exists");
  const detail = unresolved.length
    ? `<details class="fresh-grounding-checks"><summary>${unresolved.length} citation${
      unresolved.length === 1 ? "" : "s"} that did not resolve</summary><ul>${unresolved.map(
      (check) => `<li>${escapeHtml(`${check.kind} ${check.value} — ${check.result}`)}</li>`,
    ).join("")}</ul></details>`
    : "";
  return `<p class="fresh-grounding ${escapeHtml(String(grounding.status))}">
    <strong>${escapeHtml(humanize(grounding.status))}</strong>
    ${escapeHtml(grounding.reason || "")}</p>${detail}`;
}

function detailMarkup(value) {
  const caveats = value.caveats || [];
  const rejected = value.strategy?.rejected_ideas || [];
  return `<p class="eyebrow">How to read this review</p><h2>Evidence, disagreement, and limits</h2>
    ${stringList("Caveats", caveats)}
    ${stringList("Meaningful disagreements preserved", value.adjudication?.disagreements?.map(
      (item) => `${item.topic}: ${item.adjudication}`,
    ) || [])}
    ${stringList("Ideas rejected by the mission filter", rejected.map(
      (item) => `${item.idea}: ${item.reason}`,
    ))}`;
}

function stringList(title, items = []) {
  if (!items.length) return "";
  return `<h3>${escapeHtml(title)}</h3><ul>${items.map((item) => (
    `<li>${escapeHtml(String(item))}</li>`
  )).join("")}</ul>`;
}

function stateLabel(value) {
  return {
    current: "Review complete",
    in_progress: "Review in progress",
    waiting_for_understanding: "Waiting for repository understanding",
    failed: "A review task needs another attempt",
    stale: "Earlier review available; current scan not reviewed",
    superseded: "Recorded earlier generation",
    incomplete: "Recorded generation that never completed",
    not_indexed: "Repository not scanned",
    not_started: "Fresh-eyes review not started",
  }[value] || humanize(value);
}

function setBusy(busy) {
  byId("fresh-eyes-refresh").disabled = busy;
  byId("fresh-eyes-generation").disabled = busy;
  if (busy) {
    byId("fresh-eyes-start").disabled = true;
    byId("fresh-eyes-proposal-count").disabled = true;
    byId("fresh-eyes-summary").textContent = "Reading the saved review…";
  } else if (current) {
    renderStartControl(current);
  }
}

function renderWaiting() {
  if (!byId("fresh-eyes-title")) return;
  byId("fresh-eyes-title").textContent = "Open this view to read the current review";
  byId("fresh-eyes-summary").textContent = "The review is stored per repository and saved scan.";
  byId("fresh-eyes-snapshot").innerHTML = "";
  byId("fresh-eyes-stages").innerHTML = "";
  byId("fresh-eyes-diversity").innerHTML = "";
  byId("fresh-eyes-recommendations").innerHTML = "";
  byId("fresh-eyes-details").innerHTML = "";
}
