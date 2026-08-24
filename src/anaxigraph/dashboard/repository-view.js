import {
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  state,
} from "/assets/dashboard-core.js";

function onboardingStorageKey() {
  return `anaxigraph.onboarding.${state.repositoryId || "unknown"}`;
}

function onboardingState() {
  try {
    return JSON.parse(window.localStorage.getItem(onboardingStorageKey()) || "{}");
  } catch (_) {
    return {};
  }
}

export function updateOnboarding(values) {
  const next = { ...onboardingState(), ...values };
  try {
    window.localStorage.setItem(onboardingStorageKey(), JSON.stringify(next));
  } catch (_) {
    // The tour remains usable when browser storage is unavailable.
  }
  renderOnboarding();
}

export function renderOnboarding() {
  const guide = byId("onboarding-guide");
  const progress = onboardingState();
  guide.hidden = progress.dismissed === true;
  if (guide.hidden) return;
  const indexed = Boolean(state.overview?.snapshot);
  const completed = [indexed, progress.explored, progress.reviewed, progress.agent]
    .filter(Boolean).length;
  const mcpUrl = `${window.location.origin}/mcp`;
  const historyFrames = Number(state.historyInfo?.analyzed_commits || 0);
  const historyCopy = historyFrames > 1
    ? `${format.format(historyFrames)} Git graph frames are ready to replay.`
    : "The Git biography imports in the background after the current scan.";
  const steps = [
    {
      complete: indexed,
      title: "Index the repository",
      copy: indexed
        ? `${format.format(state.overview.files || 0)} files are mapped. ${historyCopy}`
        : "The first read-only scan is still building AnaxiIndex.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="modules">Browse modules</button>',
    },
    {
      complete: progress.explored,
      title: "See the system",
      copy: "Explore the autonomous semantic hierarchy and dependency paths, or replay Git history.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="graph">Open architecture graph</button>',
    },
    {
      complete: progress.reviewed,
      title: "Turn a signal into a plan",
      copy: "Review findings, dismiss noise, or mark one Planned for an agent-ready handoff.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="architecture">Open review workflow</button>',
    },
    {
      complete: progress.agent,
      title: "Connect your coding agent",
      copy: "Run this once in a normal terminal on the machine where Codex runs—not inside a chat. Future sessions on that host can then query the same repository evidence.",
      code: `codex mcp add anaxigraph --url ${mcpUrl}`,
      action: '<button class="secondary-button" type="button" data-onboarding-action="copy-agent">Copy Codex command</button>',
    },
  ];
  byId("onboarding-progress-value").textContent = `${completed}/4`;
  byId("onboarding-steps").innerHTML = steps.map((step, index) => (
    `<section class="onboarding-step ${step.complete ? "complete" : ""}"><div class="onboarding-step-header"><span class="onboarding-step-number">${step.complete ? "✓" : index + 1}</span><span class="onboarding-step-status">${step.complete ? "Complete" : "Next"}</span></div><h3>${escapeHtml(step.title)}</h3><p>${escapeHtml(step.copy)}</p>${step.code ? `<code>${escapeHtml(step.code)}</code>` : ""}${step.action}</section>`
  )).join("");
}

export function markOnboardingView(name) {
  if (["modules", "graph", "history"].includes(name)) updateOnboarding({ explored: true });
  else if (name === "architecture") updateOnboarding({ reviewed: true });
}

export function renderRepositorySelector() {
  const select = byId("repository-select");
  select.innerHTML = state.repositories.map((item) => {
    const suffix = item.scannable ? "" : " · indexed";
    return `<option value="${item.id}" title="${escapeAttr(item.path)}">${escapeHtml(item.name)}${suffix}</option>`;
  }).join("");
  select.value = String(state.repositoryId);
  select.title = state.repositories.length === 1
    ? "One repository is indexed. Additional indexed repositories will appear here."
    : "Switch every dashboard view to another indexed repository.";
}

export function renderSettings() {
  const selectedId = Number(state.repositoryId);
  byId("settings-repositories").innerHTML = state.repositories.map((item) => {
    const current = Number(item.id) === selectedId;
    const scanState = item.scannable ? "Mounted read-only · refresh enabled" : "Indexed only";
    return `<article class="settings-repository ${current ? "current" : ""}"><div><strong>${escapeHtml(item.name)}</strong>${current ? "<span>current</span>" : ""}</div><dl><dt>Registry key</dt><dd><code>${escapeHtml(item.registry_key || "not registered")}</code></dd><dt>Container path</dt><dd><code>${escapeHtml(item.path)}</code></dd><dt>Policy</dt><dd><code>${escapeHtml(item.config_path || "automatic discovery")}</code></dd><dt>Git frames</dt><dd>${item.history_snapshots === "auto" ? "Auto" : item.history_snapshots == null ? "—" : format.format(item.history_snapshots)}</dd><dt>Access</dt><dd>${escapeHtml(scanState)}</dd></dl></article>`;
  }).join("");
  const mcpUrl = `${window.location.origin}/mcp`;
  byId("settings-mcp-url").textContent = mcpUrl;
  byId("settings-codex-command").textContent = `codex mcp add anaxigraph --url ${mcpUrl}`;
  const semantic = state.semanticStatus || {};
  const coverage = semantic.coverage == null ? "not started" : `${(semantic.coverage * 100).toFixed(1)}%`;
  const provider = semantic.enabled
    ? `${semantic.provider || "configured provider"}${semantic.model ? ` · ${semantic.model}` : ""}`
    : "disabled";
  const agentFunded = semantic.provider === "agent";
  const taxonomy = semantic.taxonomy || {};
  const taxonomySummary = taxonomy.enabled
    ? taxonomy.ready
      ? ` The semantic map is current after ${format.format(taxonomy.current?.review_passes || 0)} autonomous critic pass(es).`
      : " The semantic hierarchy is still being proposed and reviewed."
    : " Semantic taxonomy generation is disabled.";
  byId("settings-semantic-summary").textContent = semantic.enabled
    ? agentFunded
      ? `${coverage} of eligible modules are current. A connected coding agent executes ${format.format(semantic.pending || 0)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) with its own model and tokens.${taxonomySummary}`
      : `${coverage} of eligible modules are current through ${provider}. Refresh policy: ${humanize(semantic.refresh || "manual")}. ${format.format(semantic.pending || 0)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) remain.${taxonomySummary}`
    : "Disabled for this repository. Deterministic analysis still works; enable semantic.provider: agent to use the connected coding agent without adding a model key to AnaxiGraph, or configure a hosted worker.";
  byId("settings-semantic-command").textContent = agentFunded
    ? "Call ANAXIGRAPH_SEMANTIC_SCHEMA once, then repeat WORK → optional EVIDENCE → SUBMIT until WORK reports complete."
    : semantic.enabled && semantic.refresh === "periodic"
      ? "docker compose -f compose.anaxigraph.yml --profile ai up -d"
      : "anaxigraph understand /path/to/repository";
}

export function displaySnapshot(snapshot, historical = false) {
  if (!snapshot) {
    byId("snapshot-label").textContent = "No snapshot";
    return;
  }
  const branch = snapshot.branch || "unknown";
  const commit = String(snapshot.commit_sha || "unknown").slice(0, 10);
  const prefix = historical ? "Historical · " : "";
  byId("snapshot-label").textContent = `${prefix}${branch} · ${commit}${snapshot.dirty ? " + dirty" : ""}`;
}
