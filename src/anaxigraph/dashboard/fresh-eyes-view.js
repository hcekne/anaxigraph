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
      </div><button id="fresh-eyes-refresh" class="secondary-button" type="button">Refresh</button>
      </div><p id="fresh-eyes-summary" class="panel-copy"></p>
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
}

async function loadFreshEyes() {
  const token = state.repositoryLoadToken;
  setBusy(true);
  try {
    const value = await request(api("/api/fresh-eyes"));
    if (token !== state.repositoryLoadToken) return;
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
  renderStartControl(value, ready);
  byId("fresh-eyes-stages").innerHTML = stageMarkup(value.stages || []);
  byId("fresh-eyes-diversity").innerHTML = diversityMarkup(value.diversity || {});
  byId("fresh-eyes-recommendations").innerHTML = recommendationMarkup(value);
  byId("fresh-eyes-details").innerHTML = detailMarkup(value);
}

function renderStartControl(value, ready = value.ready === true) {
  const canStart = ["not_started", "stale", "failed"].includes(value.state);
  byId("fresh-eyes-start").textContent = value.state === "failed" ? "Retry failed stage"
    : ["not_started", "stale"].includes(value.state) ? "Start fresh-eyes review"
      : ready ? "Review complete" : "Review in progress";
  byId("fresh-eyes-start").disabled = !canStart;
  byId("fresh-eyes-proposal-count").disabled = !["not_started", "stale"].includes(value.state);
}

function stageMarkup(stages) {
  if (!stages.length) return '<p class="muted">The five-stage recipe appears here after it starts.</p>';
  return stages.map((stage, index) => {
    const stateName = stage.state === "current" ? "complete"
      : String(stage.state).startsWith("failed") ? "failed"
        : String(stage.state).startsWith("pending") ? "active" : "waiting";
    return `<div class="fresh-stage ${stateName}"><span>${stage.state === "current" ? "✓" : index + 1}</span>
      <div><strong>${escapeHtml(stage.label)}</strong><small>${escapeHtml(stage.reason)}</small></div></div>`;
  }).join("");
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
      ${stringList("Reasons not to proceed", item.reasons_not_to_proceed)}
      ${stringList("How to verify", item.verification)}</div></article>`).join("");
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
    not_indexed: "Repository not scanned",
    not_started: "Fresh-eyes review not started",
  }[value] || humanize(value);
}

function setBusy(busy) {
  byId("fresh-eyes-refresh").disabled = busy;
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
  byId("fresh-eyes-stages").innerHTML = "";
  byId("fresh-eyes-diversity").innerHTML = "";
  byId("fresh-eyes-recommendations").innerHTML = "";
  byId("fresh-eyes-details").innerHTML = "";
}
