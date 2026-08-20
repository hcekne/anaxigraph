import { activeHistoryStates, historyStartMessage, historyView } from "/assets/history-view.js";
import {
  bindFindingFilters,
  findingCards,
  findingGroupSummary,
  findingQueryParams,
  findingResultNote,
  renderFindingFilterOptions,
} from "/assets/findings-view.js";

const state = {
  repositories: [],
  repositoryId: null,
  glossary: null,
  overview: null,
  modules: [],
  graph: { nodes: [], edges: [], snapshot: null },
  findings: [],
  findingPage: null,
  snapshots: [],
  trends: [],
  historyInfo: null,
  semanticStatus: null,
  moduleDetails: new Map(),
  selectedNode: null,
  highlightedPaths: new Set(),
  protectedPaths: new Set(),
  conflictPaths: new Set(),
  transform: { x: 0, y: 0, scale: 1 },
  positions: new Map(),
  groupRegions: [],
  groupParents: new Map(),
  groupRoots: [],
  hiddenGroups: new Set(),
  historyPlayToken: 0,
  historyPlaying: false,
  historyPollTimer: null,
  semanticPollTimer: null,
  lastAgentPrompt: "",
  moduleSort: { key: "lines_of_code", direction: "desc" },
  modulePage: 1,
  expandedModuleId: null,
  themeColors: null,
};

const supportedThemes = new Set([
  "constellation-light", "constellation-dark", "high-contrast", "anaxigraph",
]);
const architecturePalettes = {
  "constellation-light": [
    "#167a96", "#315f9f", "#b87513", "#7652a4",
    "#a12b43", "#327b82", "#6d7a29", "#a04b78",
  ],
  "constellation-dark": [
    "#7ae5ff", "#8eb7ff", "#ffcf72", "#c0a3ff",
    "#ff9aa8", "#66d6d9", "#d4df80", "#f2a9cf",
  ],
  "high-contrast": [
    "#00ffff", "#66ccff", "#ffff00", "#ff66ff",
    "#ff4d4d", "#00ff99", "#ccff33", "#ff99cc",
  ],
  anaxigraph: [
    "#72e0b3", "#7db8ff", "#f4bd69", "#b99cf7",
    "#f07970", "#5fd0df", "#d2e274", "#f3a9d0",
  ],
};
const byId = (id) => document.getElementById(id);
const format = new Intl.NumberFormat();

function currentTheme() {
  const value = document.documentElement.dataset.theme;
  return supportedThemes.has(value) ? value : "constellation-light";
}

function readThemeColors() {
  const styles = window.getComputedStyle(document.documentElement);
  const value = (name) => styles.getPropertyValue(name).trim();
  return {
    cool: value("--graph-cool"),
    hot: value("--graph-hot"),
    warm: value("--graph-warm"),
    low: value("--graph-low"),
    missing: value("--graph-missing"),
    drift: value("--graph-drift"),
    idle: value("--graph-idle"),
    safe: value("--graph-safe"),
    edge: value("--graph-edge"),
    nodeStroke: value("--graph-node-stroke"),
    selected: value("--graph-selected"),
    label: value("--graph-label"),
  };
}

function applyTheme(theme, persist = true) {
  const value = supportedThemes.has(theme) ? theme : "constellation-light";
  document.documentElement.dataset.theme = value;
  if (persist) {
    try {
      window.localStorage.setItem("anaxigraph.theme", value);
    } catch (_) {
      // The theme still applies when storage is unavailable.
    }
  }
  if (byId("theme-select")) byId("theme-select").value = value;
  const styles = window.getComputedStyle(document.documentElement);
  const meta = byId("theme-color");
  if (meta) meta.content = styles.getPropertyValue("--bg").trim();
  state.themeColors = readThemeColors();
  if (state.overview) {
    renderOverview();
    renderGraphAreaOptions();
    layoutGraph(false);
    drawGraph();
  }
}

function setupTheme() {
  applyTheme(currentTheme(), false);
}

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      message = (await response.json()).detail || message;
    } catch (_) {
      // The response was not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

function api(path, params = {}) {
  const query = new URLSearchParams();
  if (state.repositoryId != null) query.set("repository_id", state.repositoryId);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

function selectedRepository() {
  return state.repositories.find((item) => Number(item.id) === Number(state.repositoryId));
}

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

function updateOnboarding(values) {
  const next = { ...onboardingState(), ...values };
  try {
    window.localStorage.setItem(onboardingStorageKey(), JSON.stringify(next));
  } catch (_) {
    // The tour still works when browser storage is disabled; progress simply is not persisted.
  }
  renderOnboarding();
}

function renderOnboarding() {
  const guide = byId("onboarding-guide");
  const progress = onboardingState();
  guide.hidden = progress.dismissed === true;
  if (guide.hidden) return;

  const indexed = Boolean(state.overview?.snapshot);
  const completed = [indexed, progress.explored, progress.reviewed, progress.agent].filter(Boolean).length;
  const mcpUrl = `${window.location.origin}/mcp`;
  const codexCommand = `codex mcp add anaxigraph --url ${mcpUrl}`;
  const historyFrames = Number(state.historyInfo?.analyzed_commits || 0);
  const historyCopy = historyFrames > 1
    ? `${format.format(historyFrames)} Git graph frames are ready to replay.`
    : "The Git biography imports in the background after the current scan.";
  byId("onboarding-progress-value").textContent = `${completed}/4`;
  byId("onboarding-steps").innerHTML = [
    {
      complete: indexed,
      title: "Index the repository",
      copy: indexed
        ? `${format.format(state.overview.files || 0)} files are mapped from the current snapshot. ${historyCopy}`
        : "The first read-only scan is still building AnaxiIndex.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="modules">Browse modules</button>',
    },
    {
      complete: progress.explored,
      title: "See the system",
      copy: "Explore architecture regions and dependency paths, or replay how the graph grew across Git history.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="graph">Open architecture graph</button>',
    },
    {
      complete: progress.reviewed,
      title: "Turn a signal into a plan",
      copy: "Review findings, dismiss noise, or mark one Planned when you want an agent-ready work handoff.",
      action: '<button class="secondary-button" type="button" data-onboarding-view="architecture">Open review workflow</button>',
    },
    {
      complete: progress.agent,
      title: "Connect your coding agent",
      copy: "Run this once in a normal terminal on the machine where Codex runs—not inside a chat. Future sessions on that host can then query the same repository evidence.",
      code: codexCommand,
      action: '<button class="secondary-button" type="button" data-onboarding-action="copy-agent">Copy Codex command</button>',
    },
  ].map((step, index) => (
    `<section class="onboarding-step ${step.complete ? "complete" : ""}"><div class="onboarding-step-header"><span class="onboarding-step-number">${step.complete ? "✓" : index + 1}</span><span class="onboarding-step-status">${step.complete ? "Complete" : "Next"}</span></div><h3>${escapeHtml(step.title)}</h3><p>${escapeHtml(step.copy)}</p>${step.code ? `<code>${escapeHtml(step.code)}</code>` : ""}${step.action}</section>`
  )).join("");
}

async function load() {
  try {
    const [repositories, glossary] = await Promise.all([
      request("/api/repositories"),
      request("/api/glossary"),
    ]);
    state.repositories = repositories;
    state.glossary = glossary;
    if (!repositories.length) throw new Error("No repository has been indexed yet.");

    const requested = Number(new URLSearchParams(window.location.search).get("repository"));
    const remembered = Number(window.localStorage.getItem("anaxigraph.repository"));
    const candidate = repositories.find((item) => Number(item.id) === requested)
      || repositories.find((item) => Number(item.id) === remembered)
      || repositories.find((item) => item.default)
      || repositories[0];
    state.repositoryId = Number(candidate.id);
    renderRepositorySelector();
    renderWorkflowGuide();
    await loadRepository();
  } catch (error) {
    toast(error.message, true);
  }
}

async function loadRepository() {
  stopHistoryPlayback();
  window.clearTimeout(state.historyPollTimer);
  window.clearTimeout(state.semanticPollTimer);
  try {
    const [overview, modules, graph, findings, snapshots, trends, historyInfo, semanticStatus] = await Promise.all([
      request(api("/api/overview")),
      request(api("/api/modules")),
      request(api("/api/graph")),
      request(api("/api/findings", findingQueryParams())),
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
      request(api("/api/semantic")),
    ]);
    state.overview = overview;
    state.modules = modules;
    state.graph = graph;
    state.findingPage = findings;
    state.findings = findings.items || [];
    state.snapshots = snapshots;
    state.trends = trends.snapshots || [];
    state.historyInfo = historyInfo;
    state.semanticStatus = semanticStatus;
    state.moduleDetails.clear();
    state.selectedNode = null;
    state.highlightedPaths.clear();
    state.protectedPaths.clear();
    state.conflictPaths.clear();
    state.modulePage = 1;
    state.expandedModuleId = null;
    state.hiddenGroups.clear();
    buildGroupIndex(overview.group_hierarchy || []);
    renderGraphAreaOptions();

    const repository = selectedRepository();
    byId("project-name").textContent = repository?.name || "No repository";
    document.title = `${repository?.name || "Repository"} · AnaxiGraph`;
    displaySnapshot(overview.snapshot);
    const refresh = byId("refresh-button");
    refresh.disabled = !repository?.scannable;
    refresh.title = repository?.scannable
      ? "Refresh the configured read-only scan target"
      : "This repository is indexed but is not mounted as this server's scan target";

    renderOverview();
    scheduleSemanticPoll();
    renderOnboarding();
    renderModuleFilters();
    renderModules();
    renderSettings();
    renderFindings();
    renderHistory();
    renderOverlayHelp();
    layoutGraph();
    drawGraph();
  } catch (error) {
    toast(error.message, true);
  }
}

function renderRepositorySelector() {
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

function renderSettings() {
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
  const coverage = semantic.coverage == null
    ? "not started"
    : `${(semantic.coverage * 100).toFixed(1)}%`;
  const provider = semantic.enabled
    ? `${semantic.provider || "configured provider"}${semantic.model ? ` · ${semantic.model}` : ""}`
    : "disabled";
  const agentFunded = semantic.provider === "agent";
  byId("settings-semantic-summary").textContent = semantic.enabled
    ? agentFunded
      ? `${coverage} of eligible modules are current. A connected coding agent executes ${format.format(semantic.pending || 0)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) with its own model and tokens.`
      : `${coverage} of eligible modules are current through ${provider}. Refresh policy: ${humanize(semantic.refresh || "manual")}. ${format.format(semantic.pending || 0)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) remain.`
    : "Disabled for this repository. Deterministic analysis still works; enable semantic.provider: agent to use the connected coding agent without adding a model key to AnaxiGraph, or configure a hosted worker.";
  byId("settings-semantic-command").textContent = agentFunded
    ? "Use AnaxiGraph to build or resume the semantic baseline. Call ANAXIGRAPH_SEMANTIC_SCHEMA once, then repeat WORK → optional EVIDENCE pages → SUBMIT until WORK returns complete. Do not edit source during mapping."
    : semantic.enabled && semantic.refresh === "periodic"
      ? "docker compose -f compose.anaxigraph.yml --profile ai up -d"
      : "anaxigraph understand /path/to/repository";
}

function displaySnapshot(snapshot, historical = false) {
  if (!snapshot) {
    byId("snapshot-label").textContent = "No snapshot";
    return;
  }
  const branch = snapshot.branch || "unknown";
  const commit = String(snapshot.commit_sha || "unknown").slice(0, 10);
  const prefix = historical ? "Historical · " : "";
  byId("snapshot-label").textContent = `${prefix}${branch} · ${commit}${snapshot.dirty ? " + dirty" : ""}`;
}

function renderOverview() {
  const value = state.overview || {};
  const graphQuality = value.graph_quality || {};
  const findingCount = Object.values(value.findings || {}).reduce((sum, item) => sum + item, 0);
  const semantic = state.semanticStatus || value.semantic || {};
  const metrics = [
    ["Files", value.files],
    ["Lines of code", value.lines_of_code],
    ["Symbols", value.symbols],
    ["Dependencies", value.relationships],
    [
      "Internal link resolution",
      graphQuality.resolution_rate == null
        ? "No internal refs"
        : `${(graphQuality.resolution_rate * 100).toFixed(1)}%`,
    ],
    ["Avg complexity", Number(value.average_complexity || 0).toFixed(1)],
    ["Active findings", findingCount],
    [
      "AI understanding",
      semantic.enabled === false
        ? "Off"
        : semantic.coverage == null
          ? "Not started"
          : `${(semantic.coverage * 100).toFixed(1)}%`,
    ],
    [
      "Line coverage",
      value.coverage?.line_coverage == null
        ? "No report"
        : `${(value.coverage.line_coverage * 100).toFixed(1)}%`,
    ],
    [
      "Test-linked dependencies",
      value.coverage?.relationship_coverage == null
        ? "No links"
        : `${(value.coverage.relationship_coverage * 100).toFixed(1)}%`,
    ],
  ];
  byId("metric-grid").innerHTML = metrics.map(([label, metric]) => (
    `<div class="metric"><span>${escapeHtml(label)}</span><strong>${typeof metric === "number" ? format.format(metric) : escapeHtml(metric ?? "—")}</strong></div>`
  )).join("");
  renderBars("language-bars", value.languages || []);
  renderGroupHierarchy(value.group_hierarchy || []);
  byId("finding-preview").innerHTML = findingCards(
    state.findings.slice(0, 10),
    { glossary: state.glossary, actions: false },
  );

  renderSemanticNotice(semantic);
  renderRepositoryIntelligence(semantic);

  const qualityNotice = byId("graph-quality-notice");
  const unresolved = Number(graphQuality.unresolved_internal || 0);
  const ambiguous = Number(graphQuality.ambiguous_internal || 0);
  const fallback = Number(graphQuality.fallback_files || 0);
  const parseErrors = Number(graphQuality.parse_error_files || 0);
  const evidencePartial = graphQuality.status === "partial" || fallback > 0 || parseErrors > 0;
  qualityNotice.hidden = !evidencePartial;
  if (evidencePartial) {
    const resolution = graphQuality.resolution_rate == null
      ? "No internal references were available to score."
      : `${(graphQuality.resolution_rate * 100).toFixed(1)}% of likely internal references resolved to one indexed module.`;
    qualityNotice.innerHTML = `<strong>Graph evidence is partial, and advice is confidence-gated.</strong><p>${escapeHtml(resolution)} ${format.format(ambiguous)} ambiguous and ${format.format(unresolved)} unresolved internal reference(s) are retained rather than silently discarded. ${format.format(fallback)} file(s) use fallback analysis${parseErrors ? `; ${format.format(parseErrors)} file(s) have parse errors` : ""}. Dead-code suggestions are suppressed when relationship resolution is too weak.</p><p class="coverage-next">${escapeHtml(graphQuality.extraction_caveat || graphQuality.caveat || "Dynamic runtime wiring may not appear in a static graph.")}</p>`;
  }

  const notice = byId("coverage-notice");
  const coverage = value.coverage || {};
  const coverageMissing = coverage.line_coverage == null;
  const coverageRequired = coverage.required === true;
  notice.hidden = !coverageMissing || !coverageRequired;
  if (coverageMissing && coverageRequired) {
    const inputs = coverage.configured_inputs || [];
    const found = inputs.filter((item) => item.exists).length;
    const inputRows = inputs.map((item) => (
      `<li><code>${escapeHtml(item.path)}</code><span>${item.exists ? "found" : "missing"}</span></li>`
    )).join("");
    const reason = coverage.state === "unmatched"
      ? "A configured report exists, but none of its file paths matched modules in this snapshot."
      : "The selected repository has not generated any of its configured coverage reports. Coverage is produced by the repository's test runner; AnaxiGraph deliberately does not execute target code during a scan.";
    notice.innerHTML = `<strong>Required line coverage is unavailable.</strong><p>${escapeHtml(reason)}</p><details><summary>Coverage inputs · ${found}/${inputs.length} found</summary><ul class="coverage-inputs">${inputRows || "<li>No coverage paths are configured.</li>"}</ul></details><p class="coverage-next">Run the repository's own test or CI command first. <strong>Refresh scan</strong> only imports a report that already exists; it does not execute target code. Static test-linked dependencies are still reported separately above.</p>`;
  }
}

function renderRepositoryIntelligence(semantic = {}) {
  const panel = byId("repository-intelligence");
  const document = semantic.repository_dossier;
  const value = document?.value;
  panel.hidden = !value;
  if (!value) {
    panel.innerHTML = "";
    return;
  }
  panel.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Repository-level AI synthesis</p><h2>Architectural understanding</h2><p class="panel-copy">${escapeHtml(value.summary || "No repository summary recorded.")}</p><p class="inspector-provenance">${escapeHtml(semanticProviderLabel(document))} · ${(Number(document.confidence || 0) * 100).toFixed(0)}% confidence</p></div></div><div class="repository-intelligence-grid"><div><h3>Architecture role</h3><p>${escapeHtml(value.architecture_role || value.detailed_summary || "No architecture role recorded.")}</p><h3>Where new work belongs</h3><p>${escapeHtml(value.placement_guidance || "No repository-level placement guidance recorded.")}</p></div><div><h3>Pattern opportunities</h3>${patternOpportunityList(value.pattern_opportunities || [])}${consolidationMarkup(value.consolidation_assessment)}</div><div><h3>Possible dead code</h3>${deadCodeList(value.dead_code_candidates || [])}<h3>Risks and uncertainty</h3>${detailList(value.risks || [], "No repository-level semantic risk recorded")}</div></div>`;
}

function semanticProviderLabel(document = {}) {
  const provider = document.provider || "semantic provider";
  if (document.executor_id) {
    return `${provider} via ${document.executor_id}${document.executor_model ? ` · ${document.executor_model}` : ""}`;
  }
  return `${provider}${document.model ? ` · ${document.model}` : ""}`;
}

function renderSemanticNotice(semantic = {}) {
  const notice = byId("semantic-notice");
  const repository = selectedRepository();
  const worker = semantic.worker || {};
  const running = ["queued", "running"].includes(worker.status)
    || Number(semantic.jobs?.running || 0) > 0;
  const total = Number(semantic.eligible_modules || 0);
  const current = Number(semantic.current || 0);
  const pending = Number(semantic.pending || 0);
  const failed = Number(semantic.failed || 0);
  const failedScopes = Number(semantic.failed_scopes || 0);
  const excluded = Number(semantic.excluded || 0);
  const agentFunded = semantic.provider === "agent";
  if (semantic.semantically_ready && !running) {
    notice.hidden = true;
    return;
  }
  notice.hidden = false;
  if (!semantic.enabled) {
    notice.innerHTML = `<strong>AI module understanding is not enabled.</strong><p>The deterministic graph is available, but modules have not been semantically digested. Enable <code>semantic.provider: agent</code> in the selected repository policy to let your connected coding agent build the baseline with its own tokens, or configure a model worker.</p>`;
    return;
  }
  const statusCopy = agentFunded
    ? running
      ? "A connected coding agent has leased semantic work and is mapping the repository."
      : `${format.format(current)} of ${format.format(total)} eligible modules have current dossiers. The remaining queue is ready for a connected coding agent through AnaxiMCP.`
    : running
      ? "The semantic worker is reading stale modules and synthesizing their architectural context."
      : worker.status === "failed"
        ? `The semantic worker stopped: ${worker.error || "unknown error"}`
        : `${format.format(current)} of ${format.format(total)} eligible modules have current intrinsic and contextual dossiers.`;
  const action = repository?.scannable
    ? `<button class="secondary-button" type="button" data-semantic-refresh ${running ? "disabled" : ""}>${agentFunded ? running ? "Agent is mapping…" : "Prepare semantic work" : running ? "Understanding repository…" : current ? "Resume understanding" : "Understand repository"}</button>`
    : "";
  const budget = semantic.budget || {};
  const budgetCopy = !agentFunded && budget.paused
    ? ` The daily model budget is paused with $${Number(budget.remaining_today_usd || 0).toFixed(4)} remaining; the next job is estimated at $${Number(budget.next_job_estimated_usd || 0).toFixed(4)}.`
    : "";
  const heading = agentFunded
    ? running ? "Coding-agent semantic mapping is active." : "Coding-agent semantic mapping is incomplete."
    : running ? "Semantic bootstrap is running." : "Repository understanding is incomplete.";
  const incrementalCopy = agentFunded
    ? "The coding agent uses its own model and tokens. Hashes ensure later sessions receive only missing or stale work."
    : "Hashes keep later refreshes incremental; unchanged source is not sent to the model again unless the configured age policy expires it.";
  notice.innerHTML = `<div class="semantic-notice-heading"><div><strong>${heading}</strong><p>${escapeHtml(statusCopy)} ${format.format(pending)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) are pending; ${format.format(failed)} module(s) and ${format.format(failedScopes)} synthesis scope(s) failed; ${format.format(excluded)} module(s) are explicitly excluded.${escapeHtml(budgetCopy)}</p><p class="coverage-next">${escapeHtml(incrementalCopy)}</p></div>${action}</div>`;
}

function scheduleSemanticPoll() {
  window.clearTimeout(state.semanticPollTimer);
  const worker = state.semanticStatus?.worker || {};
  if (!["queued", "running"].includes(worker.status) && !Number(state.semanticStatus?.jobs?.running || 0)) return;
  state.semanticPollTimer = window.setTimeout(async () => {
    try {
      const previous = worker.status;
      state.semanticStatus = await request(api("/api/semantic"));
      renderOverview();
      if (["queued", "running"].includes(state.semanticStatus?.worker?.status) || Number(state.semanticStatus?.jobs?.running || 0)) {
        scheduleSemanticPoll();
      } else {
        if (previous === "running") toast("Repository understanding refresh finished.");
        await loadRepository();
      }
    } catch (error) {
      toast(error.message, true);
    }
  }, 1800);
}

function renderBars(id, items) {
  const maximum = Math.max(...items.map((item) => Number(item.lines_of_code || item.files || 0)), 1);
  byId(id).innerHTML = items.slice(0, 12).map((item) => {
    const value = Number(item.lines_of_code || item.files || 0);
    return `<div class="bar-row"><span>${escapeHtml(item.language || item.name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value / maximum * 100)}%"></div></div><span class="bar-value">${format.format(value)} LOC</span></div>`;
  }).join("") || `<p class="muted">No data yet.</p>`;
}

function renderGroupHierarchy(groups) {
  const container = byId("group-bars");
  if (!groups.length) {
    container.innerHTML = `<p class="muted">No groups were detected.</p>`;
    return;
  }
  const maximum = Math.max(...groups.map((group) => Number(group.lines_of_code || 0)), 1);
  const repositoryLoc = Math.max(Number(state.overview?.lines_of_code || 0), 1);
  container.innerHTML = groups.slice(0, 14).map((group) => {
    const color = groupColor(group.name);
    const direct = group.direct_files > 0 && group.children?.length
      ? [{
        name: `other-${group.name}`,
        label: `Other ${humanize(group.name)}`,
        files: group.direct_files,
        lines_of_code: group.direct_lines_of_code,
        description: "Files in this area that do not match a more specific configured subsystem.",
      }]
      : [];
    const children = [...(group.children || []), ...direct];
    const description = group.description
      || (children.length
        ? `Roll-up of ${children.length} architecture subgroups.`
        : `${humanize(group.name)} modules grouped by repository policy or path inference.`);
    const share = Number(group.lines_of_code || 0) / repositoryLoc * 100;
    const scale = Number(group.lines_of_code || 0) / maximum * 100;
    const segments = children.length
      ? children.map((child) => {
        const childColor = child.name.startsWith("other-")
          ? mix(color, architectureMixTarget(), 0.22)
          : architectureColor(child.name);
        const width = Number(child.lines_of_code || 0) / Math.max(Number(group.lines_of_code || 0), 1) * 100;
        const label = child.label || childLabel(child.name, group.name);
        return `<span class="group-segment" style="width:${width}%;background:${childColor}" title="${escapeAttr(label)} · ${format.format(child.lines_of_code || 0)} LOC"></span>`;
      }).join("")
      : `<span class="group-segment" style="width:100%;background:${color}" title="${escapeAttr(humanize(group.name))} · ${format.format(group.lines_of_code || 0)} LOC"></span>`;
    const childHtml = children.length
      ? `<div class="group-children">${children.map((child) => {
        const childColor = child.name.startsWith("other-")
          ? mix(color, architectureMixTarget(), 0.22)
          : architectureColor(child.name);
        return `<span class="group-child" style="--child-color:${childColor}" title="${escapeAttr(child.description || "Architecture subgroup")}"><i class="group-child-dot"></i>${escapeHtml(child.label || childLabel(child.name, group.name))}<em>${format.format(child.lines_of_code || 0)} LOC</em></span>`;
      }).join("")}</div>`
      : "";
    const badge = children.length
      ? group.direct_files > 0 ? "area + other files" : "area roll-up"
      : sourceLabel(group.source);
    return `<article class="group-family" style="--group-color:${color}"><div class="group-family-header"><strong>${escapeHtml(humanize(group.name))}<span class="source-badge">${escapeHtml(badge)}</span></strong><span>${format.format(group.files)} files · ${format.format(group.lines_of_code)} LOC</span></div><p>${escapeHtml(description)}</p><div class="group-scale"><div class="bar-track" title="Colored length is relative LOC; segments are subsystem shares"><div class="group-bar-fill" style="width:${Math.max(1, scale)}%">${segments}</div></div><span class="group-scale-label">${share.toFixed(1)}% of repo LOC</span></div>${childHtml}</article>`;
  }).join("");
}

function sourceLabel(source) {
  return ({
    declared: "configured",
    inferred: "inferred fallback",
    mixed: "configured + fallback",
    derived: "area roll-up",
  })[source] || source || "group";
}

function childLabel(name, parent) {
  const prefix = `${parent}-`;
  return humanize(name.startsWith(prefix) ? name.slice(prefix.length) : name);
}

function renderModuleFilters() {
  const options = (key) => [...new Set(state.modules.map((item) => item[key]).filter(Boolean))]
    .sort((left, right) => String(left).localeCompare(String(right)));
  const populate = (id, values, label) => {
    byId(id).innerHTML = `<option value="">All ${label}</option>${values.map((value) => (
      `<option value="${escapeAttr(value)}">${escapeHtml(humanize(value))}</option>`
    )).join("")}`;
  };
  populate("module-area-filter", options("architecture_area"), "areas");
  populate("module-subsystem-filter", options("architecture_subsystem"), "subsystems");
  populate("module-language-filter", options("language"), "languages");
}

function moduleValue(item, key) {
  if (key === "coupling") return Number(item.fan_in || 0) + Number(item.fan_out || 0);
  if (key === "attention_score") {
    const score = item.evaluation?.attention_score;
    return score == null ? null : Number(score);
  }
  return item[key];
}

function filteredModules() {
  const query = byId("module-search").value.trim().toLowerCase();
  const area = byId("module-area-filter").value;
  const subsystem = byId("module-subsystem-filter").value;
  const language = byId("module-language-filter").value;
  const includeReference = byId("module-include-reference").checked;
  const filtered = state.modules.filter((item) => {
    const evaluation = item.evaluation || {};
    const haystack = [
      item.path,
      item.summary,
      item.architecture_area,
      item.architecture_subsystem,
      ...(item.responsibilities || []),
      ...(evaluation.pattern_candidates || []),
    ].join(" ").toLowerCase();
    return (includeReference || evaluation.monitored_by_default !== false)
      && (!query || haystack.includes(query))
      && (!area || item.architecture_area === area)
      && (!subsystem || item.architecture_subsystem === subsystem)
      && (!language || item.language === language);
  });
  const { key, direction } = state.moduleSort;
  filtered.sort((left, right) => {
    const a = moduleValue(left, key);
    const b = moduleValue(right, key);
    if (a == null && b == null) return left.path.localeCompare(right.path);
    if (a == null) return 1;
    if (b == null) return -1;
    const comparison = typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b));
    return (direction === "asc" ? comparison : -comparison)
      || left.path.localeCompare(right.path);
  });
  return filtered;
}

function renderModules() {
  const items = filteredModules();
  const pageSize = Number(byId("module-page-size").value || 100);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  state.modulePage = Math.min(Math.max(1, state.modulePage), pages);
  const start = (state.modulePage - 1) * pageSize;
  const visible = items.slice(start, start + pageSize);
  const reviewable = state.modules.filter((item) => item.evaluation?.monitored_by_default !== false).length;
  const hidden = state.modules.length - reviewable;
  byId("module-result-count").textContent = byId("module-include-reference").checked
    ? `${format.format(items.length)} of ${format.format(state.modules.length)} modules`
    : `${format.format(items.length)} reviewable modules · ${format.format(hidden)} reference artifacts hidden`;
  byId("module-page-label").textContent = `Page ${state.modulePage} of ${pages}`;
  byId("module-previous").disabled = state.modulePage <= 1;
  byId("module-next").disabled = state.modulePage >= pages;
  document.querySelectorAll("[data-module-sort]").forEach((button) => {
    const active = button.dataset.moduleSort === state.moduleSort.key;
    button.classList.toggle("active", active);
    if (active) button.dataset.direction = state.moduleSort.direction === "asc" ? "↑" : "↓";
    else delete button.dataset.direction;
  });
  byId("module-table-body").innerHTML = visible.map((item) => {
    const evaluation = item.evaluation || {};
    const coverage = item.line_coverage == null
      ? `<span class="coverage-value missing">—</span>`
      : `<span class="coverage-value">${(Number(item.line_coverage) * 100).toFixed(0)}%</span>`;
    const architecture = item.architecture_subsystem
      ? `<strong>${escapeHtml(humanize(item.architecture_area))}</strong><span>${escapeHtml(humanize(item.architecture_subsystem))}</span>`
      : `<strong>${escapeHtml(humanize(item.architecture_area))}</strong><span>${escapeHtml(item.architecture_source)}</span>`;
    const attention = String(evaluation.attention_label || "low").toLowerCase();
    const semanticCandidates = item.semantic?.pattern_opportunities || [];
    const candidates = semanticCandidates.length
      ? semanticCandidates
      : evaluation.pattern_candidates || [];
    const candidateLabels = candidates.map(patternOpportunityLabel);
    const pattern = candidates.length
      ? `<span class="pattern-candidate" title="${escapeAttr(candidates.map(patternOpportunityExplanation).join(" · "))}">${escapeHtml(candidateLabels[0])}${candidates.length > 1 ? ` +${candidates.length - 1}` : ""}${semanticCandidates.length ? " · AI" : ""}</span>`
      : `<span class="pattern-none">${evaluation.monitored_by_default === false ? "Not evaluated" : "No grounded proposal"}</span>`;
    const attentionValue = evaluation.attention_score == null
      ? `<span class="attention-pill reference" title="${escapeAttr(evaluation.monitoring_reason || "Reference artifact")}">—</span>`
      : `<span class="attention-pill ${escapeAttr(attention)}" title="${escapeAttr((evaluation.attention_reasons || []).join(" · "))}">${format.format(evaluation.attention_score)}</span>`;
    const expanded = Number(state.expandedModuleId) === Number(item.artifact_id);
    const row = `<tr class="module-row" data-module-id="${item.artifact_id}" aria-expanded="${expanded}"><td><span class="module-name">${escapeHtml(item.name)}</span><code class="module-path">${escapeHtml(item.path)}</code></td><td class="architecture-cell">${architecture}</td><td class="module-summary">${escapeHtml(item.summary)}</td><td class="pattern-cell">${pattern}</td><td class="numeric">${format.format(item.lines_of_code)}</td><td class="numeric">${format.format(item.complexity)}</td><td class="numeric" title="${format.format(item.fan_in)} incoming · ${format.format(item.fan_out)} outgoing">${format.format(Number(item.fan_in || 0) + Number(item.fan_out || 0))}</td><td class="numeric">${coverage}</td><td class="numeric">${format.format(item.change_count || 0)}</td><td>${formatDate(item.first_changed_at)}</td><td>${formatDate(item.last_commit_at)}</td><td class="numeric">${attentionValue}</td></tr>`;
    return expanded ? row + moduleDetailRow(item) : row;
  }).join("") || `<tr><td colspan="12"><p class="muted">No modules match these filters.</p></td></tr>`;
}

function moduleDetailRow(item) {
  const evaluation = item.evaluation || {};
  const candidates = item.semantic?.pattern_opportunities?.length
    ? item.semantic.pattern_opportunities
    : evaluation.pattern_candidates || [];
  const responsibilities = item.responsibilities || [];
  const semanticState = item.semantic || {};
  const detail = state.moduleDetails.get(item.path);
  const intrinsic = detail?.semantic_dossiers?.intrinsic?.value || {};
  const contextual = detail?.semantic_dossiers?.context?.value || {};
  const semanticPurpose = contextual.summary || intrinsic.summary || item.summary;
  const semanticRole = contextual.architecture_role || intrinsic.architecture_role;
  const semanticInsights = [
    ...(contextual.similar_modules || intrinsic.similar_modules || []),
    ...(contextual.overlaps || intrinsic.overlaps || []),
    ...(contextual.extension_points || intrinsic.extension_points || []),
  ];
  const semanticPatterns = contextual.pattern_opportunities || intrinsic.pattern_opportunities || [];
  const semanticDeadCode = contextual.dead_code_candidates || intrinsic.dead_code_candidates || [];
  const consolidation = contextual.consolidation_assessment || intrinsic.consolidation_assessment;
  const semanticRisks = contextual.risks || intrinsic.risks || [];
  const history = [
    item.first_change_commit
      ? `First indexed change ${String(item.first_change_commit).slice(0, 8)} · ${formatDate(item.first_changed_at)}`
      : "No indexed first-change commit",
    item.last_change_commit
      ? `Last change ${String(item.last_change_commit).slice(0, 8)} · ${formatDate(item.last_commit_at)}`
      : "No indexed last-change commit",
    item.last_change_subject || "No commit subject indexed",
  ];
  const semanticPanel = !detail
    ? `<div><h3>AI understanding · ${escapeHtml(humanize(semanticState.status || "not started"))}</h3><p>Loading the current semantic dossier…</p></div>`
    : `<div><h3>AI understanding · ${escapeHtml(humanize(semanticState.status || "not started"))}</h3><p>${escapeHtml(semanticPurpose || "No model-backed dossier is current for this module.")}</p>${semanticRole ? `<h3>Architecture role</h3><p>${escapeHtml(semanticRole)}</p>` : ""}${contextual.change_summary ? `<h3>Meaning changed</h3><p>${escapeHtml(contextual.change_summary)}</p>` : ""}<h3>Related responsibilities and extension seams</h3>${detailList(semanticInsights, "No evidence-backed overlap or extension seam recorded")}<h3>Pattern opportunities</h3>${patternOpportunityList(semanticPatterns)}${consolidationMarkup(consolidation)}${contextual.placement_guidance ? `<h3>Where new work belongs</h3><p>${escapeHtml(contextual.placement_guidance)}</p>` : ""}<h3>Possible dead code</h3>${deadCodeList(semanticDeadCode)}<h3>Risks and uncertainty</h3>${detailList(semanticRisks, semanticState.reason || "No semantic risk recorded")}</div>`;
  return `<tr class="module-detail-row"><td colspan="12"><div class="module-detail"><div><h3>Purpose · ${escapeHtml(item.summary_source)}</h3><p>${escapeHtml(item.summary)}</p><p><code class="module-path">raw ${escapeHtml(String(item.raw_hash).slice(0, 12))} · structure ${escapeHtml(String(item.structural_hash).slice(0, 12))}</code></p><div class="module-detail-actions"><button class="secondary-button" data-module-graph="${escapeAttr(item.path)}" type="button">Open in graph</button></div></div><div><h3>Responsibilities</h3>${detailList(responsibilities, "No structured responsibilities detected")}<h3>Git biography</h3>${detailList(history)}</div>${semanticPanel}<div><h3>Review scope · ${evaluation.monitored_by_default === false ? "Reference" : "Monitored"}</h3><p>${escapeHtml(evaluation.monitoring_reason || "Included in attention triage.")}</p><h3>Attention · ${escapeHtml(evaluation.attention_label || "Low")}</h3>${detailList(evaluation.attention_reasons)}<h3>Pattern review</h3>${patternOpportunityList(candidates, "No detector-grounded pattern candidate yet")}<p>${escapeHtml(evaluation.note || "")}</p></div></div></td></tr>`;
}

function detailList(values = [], empty = "No data") {
  const items = values || [];
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>${escapeHtml(empty)}</li>`}</ul>`;
}

function patternOpportunityLabel(item) {
  if (!item || typeof item !== "object") return String(item || "Unnamed pattern");
  return `${item.name || "Unnamed pattern"} · ${format.format(Number(item.score || 0))}/100`;
}

function patternOpportunityExplanation(item) {
  if (!item || typeof item !== "object") return String(item || "");
  const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% confidence`;
  return [patternOpportunityLabel(item), item.rationale, confidence, `${item.migration_cost || "unknown"} migration cost`]
    .filter(Boolean)
    .join(" · ");
}

function patternOpportunityList(values = [], empty = "No contextual pattern opportunity recorded") {
  return detailList((values || []).map(patternOpportunityExplanation), empty);
}

function consolidationMarkup(value) {
  if (!value || typeof value !== "object") {
    return value ? `<h3>Merge or split assessment</h3><p>${escapeHtml(String(value))}</p>` : "";
  }
  if (value.recommendation === "insufficient_evidence" && !value.rationale) return "";
  const candidates = value.candidates?.length ? ` Candidates: ${value.candidates.join(", ")}.` : "";
  return `<h3>Merge or split assessment</h3><p><strong>${escapeHtml(humanize(value.recommendation || "review"))} · ${format.format(Number(value.score || 0))}/100.</strong> ${escapeHtml(value.rationale || "No rationale supplied.")}${escapeHtml(candidates)}</p>`;
}

function deadCodeList(values = []) {
  const descriptions = (values || []).map((item) => {
    if (!item || typeof item !== "object") return String(item || "");
    const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% confidence`;
    return [item.path_or_symbol, confidence, item.rationale, item.verification].filter(Boolean).join(" · ");
  });
  return detailList(descriptions, "No evidence-backed dead-code candidate recorded");
}

function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 10);
  return parsed.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

function renderFindings() {
  const page = state.findingPage;
  byId("finding-result-note").textContent = findingResultNote(page, state.findings.length);
  byId("finding-groups").innerHTML = findingGroupSummary(
    page?.view === "diagnostics" ? page.groups || [] : [],
  );
  const more = byId("finding-show-all");
  more.hidden = !page?.next_cursor;
  more.textContent = `Load next ${format.format(page?.page_size || 20)}`;
  renderFindingFilterOptions(page);
  byId("findings-table").innerHTML = findingCards(state.findings, {
    glossary: state.glossary,
  });
}

function renderWorkflowGuide() {
  const statuses = state.glossary?.findings?.statuses || {};
  const ordered = ["new", "acknowledged", "planned", "accepted", "resolved", "dismissed"];
  byId("finding-workflow").innerHTML = ordered.map((name) => {
    const item = statuses[name] || { label: humanize(name), meaning: "" };
    return `<div class="workflow-step"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.meaning)}</span></div>`;
  }).join("");
}

function buildGroupIndex(groups) {
  state.groupParents.clear();
  state.groupRoots = groups;
  const visit = (group, root) => {
    state.groupParents.set(group.name, root);
    (group.children || []).forEach((child) => visit(child, root));
  };
  groups.forEach((group) => visit(group, group.name));
}

function effectiveGroup(node) {
  return node.declared_group || node.inferred_group || "ungrouped";
}

function rootGroup(node) {
  const group = effectiveGroup(node);
  return state.groupParents.get(group) || group;
}

function visibleGraphNodes() {
  return (state.graph.nodes || []).filter((node) => !state.hiddenGroups.has(rootGroup(node)));
}

function renderGraphAreaOptions() {
  const counts = new Map();
  (state.graph.nodes || []).forEach((node) => {
    const root = rootGroup(node);
    counts.set(root, (counts.get(root) || 0) + 1);
  });
  const order = new Map(state.groupRoots.map((group, index) => [group.name, index]));
  const roots = [...counts].sort(([left], [right]) => (
    (order.get(left) ?? 10_000) - (order.get(right) ?? 10_000)
      || left.localeCompare(right)
  ));
  byId("graph-area-options").innerHTML = roots.map(([root, count]) => (
    `<label><input type="checkbox" data-graph-area="${escapeAttr(root)}" ${state.hiddenGroups.has(root) ? "" : "checked"} /><i style="background:${groupColor(root)}"></i><span>${escapeHtml(humanize(root))}</span><em>${format.format(count)}</em></label>`
  )).join("");
  const visible = roots.filter(([root]) => !state.hiddenGroups.has(root)).length;
  byId("graph-area-count").textContent = visible === roots.length
    ? `all ${roots.length}`
    : `${visible}/${roots.length}`;
}

function architectureColor(group) {
  const parent = state.groupParents.get(group) || group;
  const base = groupColor(parent);
  if (parent === group) return base;
  return mix(base, architectureMixTarget(), 0.08 + (hash(group) % 13) / 100);
}

function architectureMixTarget() {
  return currentTheme() === "high-contrast" ? "#000000" : "#ffffff";
}

function weightedRectangles(items, bounds, gap = 8) {
  const rectangles = new Map();
  const partition = (entries, rectangle) => {
    if (!entries.length) return;
    if (entries.length === 1) {
      const inset = Math.min(gap, rectangle.width * 0.08, rectangle.height * 0.08);
      rectangles.set(entries[0].key, {
        x: rectangle.x + inset,
        y: rectangle.y + inset,
        width: Math.max(10, rectangle.width - inset * 2),
        height: Math.max(10, rectangle.height - inset * 2),
      });
      return;
    }
    const total = entries.reduce((sum, item) => sum + item.weight, 0);
    let split = 1;
    let firstWeight = entries[0].weight;
    while (split < entries.length - 1 && firstWeight + entries[split].weight <= total / 2) {
      firstWeight += entries[split].weight;
      split += 1;
    }
    const ratio = Math.max(0.08, Math.min(0.92, firstWeight / total));
    if (rectangle.width >= rectangle.height) {
      const firstWidth = rectangle.width * ratio;
      partition(entries.slice(0, split), { ...rectangle, width: firstWidth });
      partition(entries.slice(split), {
        x: rectangle.x + firstWidth,
        y: rectangle.y,
        width: rectangle.width - firstWidth,
        height: rectangle.height,
      });
    } else {
      const firstHeight = rectangle.height * ratio;
      partition(entries.slice(0, split), { ...rectangle, height: firstHeight });
      partition(entries.slice(split), {
        x: rectangle.x,
        y: rectangle.y + firstHeight,
        width: rectangle.width,
        height: rectangle.height - firstHeight,
      });
    }
  };
  partition(items, bounds);
  return rectangles;
}

function squarifiedRectangles(items, bounds, gap = 8) {
  const rectangles = new Map();
  if (!items.length || bounds.width <= 0 || bounds.height <= 0) return rectangles;
  const totalWeight = items.reduce((sum, item) => sum + item.weight, 0) || 1;
  const areaScale = bounds.width * bounds.height / totalWeight;
  const remainingItems = [...items]
    .sort((left, right) => right.weight - left.weight || left.key.localeCompare(right.key))
    .map((item) => ({ ...item, area: item.weight * areaScale }));
  let remaining = { ...bounds };
  let row = [];

  const worstAspect = (entries, side) => {
    if (!entries.length || side <= 0) return Number.POSITIVE_INFINITY;
    const total = entries.reduce((sum, item) => sum + item.area, 0);
    const largest = Math.max(...entries.map((item) => item.area));
    const smallest = Math.min(...entries.map((item) => item.area));
    return Math.max(
      side * side * largest / (total * total),
      total * total / (side * side * smallest),
    );
  };

  const placeRow = (entries) => {
    const total = entries.reduce((sum, item) => sum + item.area, 0);
    const inset = gap / 2;
    if (remaining.width >= remaining.height) {
      const rowWidth = total / Math.max(remaining.height, 1);
      let cursor = remaining.y;
      entries.forEach((item) => {
        const itemHeight = item.area / Math.max(rowWidth, 1);
        rectangles.set(item.key, {
          x: remaining.x + inset,
          y: cursor + inset,
          width: Math.max(10, rowWidth - gap),
          height: Math.max(10, itemHeight - gap),
        });
        cursor += itemHeight;
      });
      remaining = {
        x: remaining.x + rowWidth,
        y: remaining.y,
        width: Math.max(0, remaining.width - rowWidth),
        height: remaining.height,
      };
    } else {
      const rowHeight = total / Math.max(remaining.width, 1);
      let cursor = remaining.x;
      entries.forEach((item) => {
        const itemWidth = item.area / Math.max(rowHeight, 1);
        rectangles.set(item.key, {
          x: cursor + inset,
          y: remaining.y + inset,
          width: Math.max(10, itemWidth - gap),
          height: Math.max(10, rowHeight - gap),
        });
        cursor += itemWidth;
      });
      remaining = {
        x: remaining.x,
        y: remaining.y + rowHeight,
        width: remaining.width,
        height: Math.max(0, remaining.height - rowHeight),
      };
    }
  };

  while (remainingItems.length) {
    const candidate = remainingItems[0];
    const side = Math.min(remaining.width, remaining.height);
    if (!row.length || worstAspect([...row, candidate], side) <= worstAspect(row, side)) {
      row.push(remainingItems.shift());
    } else {
      placeRow(row);
      row = [];
    }
  }
  if (row.length) placeRow(row);
  return rectangles;
}

function layoutGraph(resetView = true) {
  const nodes = visibleGraphNodes();
  const canvas = byId("graph-canvas");
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const grouped = new Map();
  nodes.forEach((node) => {
    const group = effectiveGroup(node);
    if (!grouped.has(group)) grouped.set(group, []);
    grouped.get(group).push(node);
  });
  const rootOrder = new Map(state.groupRoots.map((group, index) => [group.name, index]));
  const roots = new Map();
  const seedGroup = (map, group) => {
    if (!map.has(group.name)) map.set(group.name, []);
    (group.children || []).forEach((child) => seedGroup(map, child));
  };
  state.groupRoots.filter((root) => !state.hiddenGroups.has(root.name)).forEach((root) => {
    const map = new Map();
    seedGroup(map, root);
    roots.set(root.name, map);
  });
  grouped.forEach((members, group) => {
    const root = state.groupParents.get(group) || group;
    if (!roots.has(root)) roots.set(root, new Map());
    roots.get(root).set(group, members);
  });
  const rootNames = [...roots.keys()]
    .filter((root) => [...roots.get(root).values()].some((members) => members.length))
    .sort((left, right) => {
      const leftOrder = rootOrder.get(left) ?? 10_000;
      const rightOrder = rootOrder.get(right) ?? 10_000;
      return leftOrder - rightOrder || left.localeCompare(right);
    });
  const rootEntries = rootNames.map((root) => {
    const nodeCount = [...roots.get(root).values()]
      .reduce((sum, members) => sum + members.length, 0);
    const labelFloor = 28 + humanize(root).length * 2.4;
    return { key: root, weight: Math.max(48, labelFloor, nodeCount) };
  });
  const rootRectangles = squarifiedRectangles(
    rootEntries,
    { x: 0, y: 0, width, height },
    10,
  );
  state.positions.clear();
  state.groupRegions = [];
  rootNames.forEach((root) => {
    const rectangle = rootRectangles.get(root);
    if (!rectangle) return;
    const nodeCount = [...roots.get(root).values()]
      .reduce((sum, members) => sum + members.length, 0);
    const region = {
      root,
      ...rectangle,
      nodeCount,
      color: groupColor(root),
    };
    region.labelLines = regionLabelLines(region);
    region.labelOverflow = region.labelLines.some((line) => (
      estimateLabelWidth(line) > Math.max(1, region.width - 20)
    )) || region.height < region.labelLines.length * 14 + 18;
    state.groupRegions.push(region);
    const headerHeight = Math.min(
      Math.max(28, region.labelLines.length * 14 + 8),
      Math.max(28, region.height * 0.34),
    );
    const subgroupEntries = [...roots.get(root).entries()]
      .filter(([, members]) => members.length)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([group, members]) => ({ key: group, weight: members.length }));
    const subgroupRectangles = weightedRectangles(
      subgroupEntries,
      {
        x: region.x + 5,
        y: region.y + headerHeight,
        width: Math.max(10, region.width - 10),
        height: Math.max(10, region.height - headerHeight - 5),
      },
      3,
    );
    subgroupEntries.forEach(({ key: group }) => {
      const subregion = subgroupRectangles.get(group);
      const members = [...roots.get(root).get(group)].sort((left, right) => (
        left.path.localeCompare(right.path)
      ));
      if (!subregion || !members.length) return;
      const innerWidth = Math.max(8, subregion.width - 8);
      const innerHeight = Math.max(8, subregion.height - 8);
      const columns = Math.max(
        1,
        Math.ceil(Math.sqrt(members.length * innerWidth / Math.max(innerHeight, 1))),
      );
      const rows = Math.ceil(members.length / columns);
      const cellWidth = innerWidth / columns;
      const cellHeight = innerHeight / Math.max(rows, 1);
      members.forEach((node, index) => {
        const value = hash(node.path);
        const column = index % columns;
        const row = Math.floor(index / columns);
        const jitter = Math.min(cellWidth, cellHeight) * 0.12;
        const jitterX = (((value & 255) / 255) - 0.5) * jitter;
        const jitterY = ((((value >>> 8) & 255) / 255) - 0.5) * jitter;
        state.positions.set(String(node.id), {
          x: subregion.x + 4 + (column + 0.5) * cellWidth + jitterX,
          y: subregion.y + 4 + (row + 0.5) * cellHeight + jitterY,
          group,
        });
      });
    });
  });
  canvas.dataset.regionCount = String(state.groupRegions.length);
  canvas.dataset.visibleNodeCount = String(nodes.length);
  canvas.dataset.labelOverflow = String(
    state.groupRegions.filter((region) => region.labelOverflow).length,
  );
  if (resetView) state.transform = { x: 0, y: 0, scale: 1 };
  renderLegend();
}

function estimateLabelWidth(value) {
  return String(value).length * 6.35;
}

function regionLabelLines(region) {
  const name = humanize(region.root);
  const count = `${format.format(region.nodeCount)} module${region.nodeCount === 1 ? "" : "s"}`;
  const available = Math.max(40, region.width - 20);
  if (estimateLabelWidth(`${name} · ${format.format(region.nodeCount)}`) <= available) {
    return [`${name} · ${format.format(region.nodeCount)}`];
  }
  const lines = [];
  let current = "";
  name.split(" ").forEach((word) => {
    const candidate = current ? `${current} ${word}` : word;
    if (current && estimateLabelWidth(candidate) > available) {
      lines.push(current);
      current = word;
    } else {
      current = candidate;
    }
  });
  if (current) lines.push(current);
  lines.push(count);
  return lines;
}

function nodeMetric(node) {
  return Math.max(0, Number(node[byId("size-select").value] || 0));
}

function nodeRadius(node, maximum) {
  return 3.2 + Math.sqrt(nodeMetric(node) / Math.max(maximum, 1)) * 10;
}

function groupColor(group) {
  const colors = architecturePalettes[currentTheme()] || architecturePalettes["constellation-light"];
  return colors[Math.abs(hash(group)) % colors.length];
}

function heat(value, maximum, cool = null, hot = null) {
  const theme = state.themeColors || readThemeColors();
  const amount = Math.min(1, Math.max(0, value / Math.max(maximum, 1)));
  return mix(cool || theme.cool, hot || theme.hot, amount);
}

function nodeColor(node) {
  const overlay = byId("overlay-select").value;
  const theme = state.themeColors || readThemeColors();
  if (overlay === "architecture") return architectureColor(effectiveGroup(node));
  if (overlay === "coupling") return heat(Number(node.fan_in) + Number(node.fan_out), 25, theme.low, theme.hot);
  if (overlay === "complexity") return heat(Number(node.complexity), 60, theme.cool, theme.hot);
  if (overlay === "coverage") return node.line_coverage == null ? theme.missing : heat(1 - Number(node.line_coverage), 1, theme.cool, theme.hot);
  if (overlay === "change") return heat(Number(node.change_count || 0), 30, theme.low, theme.warm);
  if (overlay === "drift") return node.declared_group && node.inferred_group && node.declared_group !== node.inferred_group ? theme.hot : theme.drift;
  if (overlay === "dead-code") {
    const module = state.modules.find((item) => item.path === node.path);
    const dead = module?.active_findings?.some(
      (finding) => finding.finding_type === "possible_dead_code",
    );
    return dead ? theme.warm : theme.idle;
  }
  if (overlay === "agent") {
    if (state.conflictPaths.has(node.path)) return theme.hot;
    if (state.protectedPaths.has(node.path)) return theme.warm;
    if (state.highlightedPaths.has(node.path)) return theme.cool;
    return theme.safe;
  }
  return theme.cool;
}

function drawGraph() {
  const canvas = byId("graph-canvas");
  if (!canvas) return;
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  if (canvas.width !== Math.floor(width * ratio) || canvas.height !== Math.floor(height * ratio)) {
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
  }
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);
  const { x, y, scale } = state.transform;
  context.save();
  context.translate(x, y);
  context.scale(scale, scale);
  const visibleNodes = visibleGraphNodes();
  const visibleIds = new Set(visibleNodes.map((node) => String(node.id)));
  const metricMaximum = Math.max(...visibleNodes.map(nodeMetric), 1);
  const theme = state.themeColors || readThemeColors();
  context.lineCap = "round";
  if (byId("architecture-regions-toggle").checked) {
    state.groupRegions.forEach((region) => {
      context.globalAlpha = 0.075;
      context.fillStyle = region.color;
      roundedRectangle(context, region.x, region.y, region.width, region.height, 12 / scale);
      context.fill();
      context.globalAlpha = 0.34;
      context.strokeStyle = region.color;
      context.lineWidth = 1 / scale;
      context.stroke();
      context.save();
      roundedRectangle(context, region.x, region.y, region.width, region.height, 12 / scale);
      context.clip();
      context.globalAlpha = 0.82;
      context.fillStyle = region.color;
      context.font = `${11 / scale}px ui-sans-serif, system-ui, sans-serif`;
      region.labelLines.forEach((line, index) => {
        context.fillText(
          line,
          region.x + 10 / scale,
          region.y + (17 + index * 14) / scale,
          Math.max(10, region.width - 20 / scale),
        );
      });
      context.restore();
    });
    context.globalAlpha = 1;
  }
  const edgeLimit = scale < 0.8 ? 1600 : 5000;
  state.graph.edges.slice(0, edgeLimit).forEach((edge) => {
    const source = state.positions.get(String(edge.source));
    const target = state.positions.get(String(edge.target));
    if (!source || !target || !visibleIds.has(String(edge.target))) return;
    context.strokeStyle = theme.edge;
    context.lineWidth = Math.min(2.4, 0.35 + Math.log2(Number(edge.weight || 1) + 1) * 0.35) / scale;
    context.beginPath();
    context.moveTo(source.x, source.y);
    context.lineTo(target.x, target.y);
    context.stroke();
  });
  const search = byId("graph-search").value.trim().toLowerCase();
  visibleNodes.forEach((node) => {
    const position = state.positions.get(String(node.id));
    if (!position) return;
    const radius = nodeRadius(node, metricMaximum);
    const matches = !search || `${node.path} ${node.summary}`.toLowerCase().includes(search);
    context.globalAlpha = matches ? 1 : 0.12;
    context.fillStyle = nodeColor(node);
    context.beginPath();
    context.arc(position.x, position.y, radius, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = theme.nodeStroke;
    context.lineWidth = 1.25 / scale;
    context.stroke();
    if (state.selectedNode && String(state.selectedNode.id) === String(node.id)) {
      context.beginPath();
      context.arc(position.x, position.y, radius + 2.5 / scale, 0, Math.PI * 2);
      context.strokeStyle = theme.selected;
      context.lineWidth = 2 / scale;
      context.stroke();
    }
    if (scale > 1.25 && radius > 4.5 && matches) {
      context.fillStyle = theme.label;
      context.font = `${10 / scale}px ui-monospace, monospace`;
      context.fillText(node.path.split("/").pop(), position.x + radius + 3 / scale, position.y + 3 / scale);
    }
  });
  context.globalAlpha = 1;
  context.restore();
}

function roundedRectangle(context, x, y, width, height, radius) {
  const bounded = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + bounded, y);
  context.arcTo(x + width, y, x + width, y + height, bounded);
  context.arcTo(x + width, y + height, x, y + height, bounded);
  context.arcTo(x, y + height, x, y, bounded);
  context.arcTo(x, y, x + width, y, bounded);
  context.closePath();
}

function renderLegend() {
  const overlay = byId("overlay-select").value;
  const theme = state.themeColors || readThemeColors();
  let items;
  if (overlay === "architecture") {
    items = state.groupRoots
      .filter((group) => !state.hiddenGroups.has(group.name))
      .slice(0, 12)
      .map((group) => [humanize(group.name), groupColor(group.name)]);
  } else if (overlay === "agent") {
    items = [["Task context", theme.cool], ["Protected", theme.warm], ["Branch collision", theme.hot]];
  } else if (overlay === "coverage" && visibleGraphNodes().every((node) => node.line_coverage == null)) {
    items = [["No imported coverage", theme.missing]];
  } else if (overlay === "drift") {
    items = [["Matches / no declaration", theme.drift], ["Configured and inferred differ", theme.hot]];
  } else if (overlay === "dead-code") {
    items = [["No signal", theme.idle], ["Inspect static reachability", theme.warm]];
  } else {
    items = [["Lower signal", theme.low], ["Higher signal", overlay === "change" ? theme.warm : theme.hot]];
  }
  byId("graph-legend").innerHTML = items.map(([label, color]) => (
    `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${escapeHtml(label)}</span>`
  )).join("");
}

function renderOverlayHelp() {
  const overlay = byId("overlay-select").value;
  let message = state.glossary?.overlays?.[overlay] || "Select an overlay to inspect the repository.";
  if (overlay === "agent" && !state.highlightedPaths.size) {
    message += " Plan a coding task or open a planned finding to populate this overlay.";
  }
  byId("overlay-help").textContent = message;
}

async function inspectNode(node) {
  state.selectedNode = node;
  drawGraph();
  const panel = byId("inspector");
  const displayName = String(node.path).split("/").pop();
  panel.innerHTML = `<p class="eyebrow">Module inspector</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(node.path)}</code><p class="muted">Loading details…</p>`;
  if (String(node.id).startsWith("external:")) {
    panel.innerHTML = `<p class="eyebrow">External dependency</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(node.path)}</code><p class="muted">This node is referenced by repository code but is not a file analyzed inside this repository.</p>`;
    return;
  }
  try {
    const detail = await request(api("/api/file", {
      path: node.path,
      snapshot_id: state.graph.snapshot?.id,
    }));
    const file = detail.file;
    const relationships = detail.relationships.slice(0, 14).map((item) => (
      `<button data-path="${escapeAttr(item.target_path || "")}">${escapeHtml(item.relationship_type)} → ${escapeHtml(item.target_path || item.target_external)}</button>`
    )).join("");
    const dependants = detail.dependants.slice(0, 14).map((item) => (
      `<button data-path="${escapeAttr(item.source_path || "")}">${escapeHtml(item.source_path || "")}</button>`
    )).join("");
    const responsibilities = (file.responsibilities || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("");
    const inventory = state.modules.find((item) => item.path === file.path) || {};
    const intrinsicDocument = detail.semantic_dossiers?.intrinsic;
    const contextDocument = detail.semantic_dossiers?.context;
    const intrinsic = intrinsicDocument?.value || {};
    const contextual = contextDocument?.value || {};
    const semantic = contextDocument || intrinsicDocument;
    const semanticValue = contextual.summary ? contextual : intrinsic;
    const purpose = semanticValue.summary || inventory.summary || file.summary;
    const purposeSource = semantic
      ? `${semanticProviderLabel(semantic)} ${contextDocument ? "contextual" : "intrinsic"} interpretation · ${(Number(semantic.confidence || 0) * 100).toFixed(0)}% confidence`
      : "Deterministic analyzer summary";
    const area = inventory.architecture_area || state.groupParents.get(effectiveGroup(file)) || effectiveGroup(file);
    const subsystem = inventory.architecture_subsystem || effectiveGroup(file);
    const coverage = node.line_coverage == null
      ? "Not imported"
      : `${(Number(node.line_coverage) * 100).toFixed(1)}%`;
    const evaluation = inventory.evaluation || {};
    const patternCandidates = evaluation.pattern_candidates || [];
    const semanticResponsibilities = semanticValue.responsibilities || [];
    const semanticRelations = semanticValue.overlaps || [];
    const semanticExtensions = semanticValue.extension_points || [];
    const semanticSimilar = semanticValue.similar_modules || [];
    const semanticPatterns = semanticValue.pattern_opportunities || [];
    const semanticDeadCode = semanticValue.dead_code_candidates || [];
    const semanticRisks = semanticValue.risks || [];
    const semanticSection = semantic
      ? `<h3>AI architecture role</h3><p class="muted">${escapeHtml(semanticValue.architecture_role || "No architecture role recorded")}</p>${semanticValue.change_summary ? `<h3>Meaning changed</h3><p class="muted">${escapeHtml(semanticValue.change_summary)}</p>` : ""}<h3>AI-understood responsibilities</h3>${detailList(semanticResponsibilities, "No semantic responsibilities recorded")}<h3>Similar or overlapping modules</h3>${detailList([...semanticSimilar, ...semanticRelations], "No evidence-backed overlap recorded")}<h3>Pattern opportunities</h3>${patternOpportunityList(semanticPatterns)}${consolidationMarkup(semanticValue.consolidation_assessment)}${semanticValue.placement_guidance ? `<h3>Where new work belongs</h3><p class="muted">${escapeHtml(semanticValue.placement_guidance)}</p>` : ""}<h3>Possible dead code</h3>${deadCodeList(semanticDeadCode)}<h3>Extension seams</h3>${detailList(semanticExtensions, "No extension seam recorded")}<h3>Semantic risks</h3>${detailList(semanticRisks, "No semantic risk recorded")}`
      : `<h3>AI understanding</h3><p class="muted">${escapeHtml(detail.semantic_state?.reason || "No current model-backed dossier. Run the repository semantic bootstrap to add one.")}</p>`;
    panel.innerHTML = `<p class="eyebrow">${escapeHtml(humanize(area))} · ${escapeHtml(humanize(subsystem))}</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(file.path)}</code><h3>Purpose</h3><p class="muted">${escapeHtml(purpose)}</p><p class="inspector-provenance">${escapeHtml(purposeSource)}</p><dl><dt>Language</dt><dd>${escapeHtml(file.language)}</dd><dt>Runtime</dt><dd>${escapeHtml(file.runtime || "—")}</dd><dt>LOC</dt><dd>${format.format(file.lines_of_code)}</dd><dt>Complexity</dt><dd>${file.complexity}</dd><dt>Incoming links</dt><dd>${format.format(node.fan_in || 0)}</dd><dt>Outgoing links</dt><dd>${format.format(node.fan_out || 0)}</dd><dt>Line coverage</dt><dd>${coverage}</dd><dt>Indexed changes</dt><dd>${format.format(node.change_count || 0)}</dd><dt>First indexed</dt><dd>${formatDate(inventory.first_changed_at)}</dd><dt>Last worked</dt><dd>${formatDate(inventory.last_commit_at)}</dd><dt title="Changes when any source byte changes">Raw hash</dt><dd><code>${escapeHtml(String(file.raw_hash || "").slice(0, 10))}</code></dd><dt title="Tracks normalized code structure and ignores some metadata-only edits">Structural hash</dt><dd><code>${escapeHtml(String(file.structural_hash || "").slice(0, 10))}</code></dd><dt>Analysis state</dt><dd>${escapeHtml(file.analysis_status)}</dd><dt>Frame reason</dt><dd>${escapeHtml(humanize(file.metadata?.invalidation_reason || "not recorded"))}</dd><dt>Semantic state</dt><dd>${escapeHtml(humanize(detail.semantic_state?.status || "not started"))}</dd></dl>${semanticSection}<h3>Detected responsibilities</h3><div class="tag-list">${responsibilities || `<span class="muted">No structured responsibility detected</span>`}</div><h3>Deterministic pattern review</h3><div class="tag-list">${patternCandidates.map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || `<span class="muted">No detector-grounded pattern candidate yet</span>`}</div><h3>Public interfaces</h3><div class="tag-list">${(file.public_interfaces || []).slice(0, 18).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || `<span class="muted">None detected</span>`}</div><h3>Uses</h3><div class="relation-list">${relationships || `<span class="muted">No outgoing relationship detected</span>`}</div><h3>Used by</h3><div class="relation-list">${dependants || `<span class="muted">No incoming relationship detected</span>`}</div><h3>Recent changes</h3><div class="relation-list">${detail.history.slice(0, 6).map((item) => `<span class="muted">${escapeHtml(item.commit_sha.slice(0, 8))} · ${escapeHtml(item.subject)}</span>`).join("") || `<span class="muted">No Git history loaded</span>`}</div>`;
  } catch (error) {
    panel.innerHTML += `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderHistory() {
  const snapshots = state.snapshots, info = state.historyInfo || {};
  const model = historyView(info, snapshots);
  const range = byId("history-range");
  range.max = Math.max(0, snapshots.length - 1);
  range.value = Math.max(0, snapshots.length - 1);
  range.disabled = snapshots.length < 2;
  byId("history-commits").innerHTML = snapshots.length
    ? `<span>${escapeHtml(String(snapshots[0].commit_sha).slice(0, 8))}</span><span>${escapeHtml(String(snapshots.at(-1).commit_sha).slice(0, 8))}</span>`
    : "";
  byId("history-help").textContent = model.help;
  byId("history-job-detail").innerHTML = model.details.map(([label, value]) => `<span><strong>${escapeHtml(label)}</strong>${escapeHtml(value)}</span>`).join("");
  byId("history-play-button").disabled = snapshots.length < 2;
  byId("graph-history-play-button").disabled = snapshots.length < 2;
  const importButton = byId("history-import-button");
  importButton.disabled = model.importDisabled;
  importButton.textContent = model.importLabel;
  const cancelButton = byId("history-cancel-button");
  cancelButton.hidden = !model.active;
  cancelButton.disabled = model.cancelRequested;
  showHistoryIndex(Number(range.value));
  updatePlaybackButtons();
  scheduleHistoryRefresh();
}

function scheduleHistoryRefresh() {
  window.clearTimeout(state.historyPollTimer);
  if (!activeHistoryStates.has(state.historyInfo?.job?.status)) return;
  state.historyPollTimer = window.setTimeout(refreshHistoryData, 2500);
}

async function refreshHistoryData() {
  try {
    const [snapshots, trends, historyInfo] = await Promise.all([
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
    ]);
    state.snapshots = snapshots;
    state.trends = trends.snapshots || [];
    state.historyInfo = historyInfo;
    renderHistory();
    renderOnboarding();
  } catch (error) {
    toast(error.message, true);
  }
}

function showHistoryIndex(index) {
  const snapshot = state.snapshots[index];
  if (!snapshot) return;
  byId("history-range").value = String(index);
  const timestamp = snapshot.commit_timestamp || snapshot.analysis_timestamp;
  byId("history-value").textContent = `${String(snapshot.commit_sha).slice(0, 10)} · ${new Date(timestamp).toLocaleString()}`;
  const trend = state.trends.find((item) => Number(item.snapshot_id) === Number(snapshot.id));
  const metrics = trend?.metrics || {};
  const values = [
    ["LOC", metrics.total_loc ?? snapshot.lines_of_code],
    ["Artifacts", metrics.artifact_count ?? snapshot.file_count],
    ["Dependencies", metrics.dependency_count ?? snapshot.relationship_count],
    ["Cycles", metrics.cycle_count],
    ["Average degree", metrics.average_degree == null ? null : Number(metrics.average_degree).toFixed(1)],
    ["Violations", metrics.architecture_violation_count],
  ];
  byId("trend-grid").innerHTML = values.map(([label, value]) => (
    `<div class="metric"><span>${escapeHtml(label)}</span><strong>${value == null ? "—" : format.format(value)}</strong></div>`
  )).join("");
}

async function graphAtSnapshot(snapshotId, preserveCamera = true) {
  const selectedPath = state.selectedNode?.path;
  state.graph = await request(api("/api/graph", {
    snapshot_id: snapshotId,
    include_external: byId("external-toggle").checked,
  }));
  state.selectedNode = selectedPath
    ? state.graph.nodes.find((node) => node.path === selectedPath) || null
    : null;
  renderGraphAreaOptions();
  const currentId = Number(state.overview?.snapshot?.id);
  displaySnapshot(state.graph.snapshot, Number(snapshotId) !== currentId);
  layoutGraph(!preserveCamera);
  drawGraph();
}

async function toggleHistoryPlayback() {
  if (state.historyPlaying) {
    stopHistoryPlayback();
    return;
  }
  if (state.snapshots.length < 2) {
    toast("Import at least two historical snapshots before replaying.", true);
    return;
  }
  state.historyPlaying = true;
  const token = ++state.historyPlayToken;
  updatePlaybackButtons();
  switchView("graph", true);
  for (let index = 0; index < state.snapshots.length && token === state.historyPlayToken; index += 1) {
    showHistoryIndex(index);
    try {
      await graphAtSnapshot(state.snapshots[index].id, true);
    } catch (error) {
      toast(error.message, true);
      break;
    }
    await delay(900);
  }
  if (token === state.historyPlayToken) {
    state.historyPlaying = false;
    updatePlaybackButtons();
  }
}

function stopHistoryPlayback() {
  state.historyPlayToken += 1;
  state.historyPlaying = false;
  updatePlaybackButtons();
}

function updatePlaybackButtons() {
  const label = state.historyPlaying ? "Pause replay" : "Replay history";
  if (byId("graph-history-play-button")) byId("graph-history-play-button").textContent = label;
  if (byId("history-play-button")) byId("history-play-button").textContent = state.historyPlaying ? "Pause" : "Play";
}

function renderAgentResult(value, kind) {
  const result = byId("agent-result");
  const risk = value.risk || "low";
  if (kind === "scope") {
    state.highlightedPaths = new Set([
      ...(value.primary_files || []),
      ...(value.related_files || []),
    ].map((item) => item.path));
    state.protectedPaths = new Set((value.protected_files || []).map((item) => item.path));
    state.conflictPaths = new Set((value.active_branch_conflicts || []).map((item) => item.path));
    byId("overlay-select").value = "agent";
    renderOverlayHelp();
    renderLegend();
    drawGraph();
    const findings = (value.known_findings || []).map((item) => `#${item.id} ${item.summary} (${item.status})`);
    const rules = (value.architecture_rules || []).map((item) => `${item.rule_id}: ${item.description || humanize(item.rule_type)}`);
    result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Recommended coding context</p><h2>${escapeHtml(value.goal)}</h2><p class="panel-copy">Primary files are the strongest matches. Related files are connected context, not a suggestion to edit all of them.</p></div><span class="risk ${escapeHtml(risk)}">${escapeHtml(risk)} risk</span></div>${(value.risk_reasons || []).map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}<div class="result-columns">${resultList("Likely implementation files", value.primary_files?.map((item) => item.path))}${resultList("Connected context", value.related_files?.map((item) => item.path))}${resultList("Relevant tests", value.tests)}${resultList("Existing findings", findings)}${resultList("Applicable rules", rules)}${resultList("Branch collisions", value.active_branch_conflicts?.map((item) => `${item.branch}: ${item.path}`))}</div>`;
  } else {
    result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Change impact</p><h2>${escapeHtml(value.target.path)}</h2><p class="panel-copy">Dependants are files that use this target and may need verification if its behavior or interface changes.</p></div><span class="risk ${escapeHtml(risk)}">${escapeHtml(risk)} risk</span></div><div class="result-columns">${resultList("Direct dependants", value.direct_dependants?.map((item) => item.path))}${resultList("Indirect dependants", value.second_order_dependants?.map((item) => item.path))}${resultList("This file uses", value.outgoing_dependencies?.map((item) => item.path))}${resultList("Relevant tests", value.tests_relevant)}${resultList("Protected paths", value.critical_paths_affected)}${resultList("Possible migrations", value.database_migrations_possibly_affected)}</div>`;
  }
}

function renderFindingHandoff(value) {
  const result = byId("agent-result");
  const finding = value.finding;
  const scope = value.scope || {};
  state.lastAgentPrompt = value.agent_prompt || "";
  state.highlightedPaths = new Set((value.recommended_context || []).map(String));
  state.protectedPaths = new Set((value.protected_paths || []).map(String));
  state.conflictPaths = new Set((scope.active_branch_conflicts || []).map((item) => item.path));
  byId("overlay-select").value = "agent";
  renderOverlayHelp();
  renderLegend();
  drawGraph();
  result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Finding #${finding.id} · agent handoff</p><h2>${escapeHtml(finding.summary)}</h2><p class="panel-copy">${escapeHtml(value.workflow_note)}</p></div><span class="risk ${escapeHtml(value.risk)}">${escapeHtml(value.risk)} risk</span></div><div class="result-columns">${resultList("Recommended context", value.recommended_context)}${resultList("Relevant tests", value.relevant_tests)}${resultList("Protected paths", value.protected_paths)}${resultList("Verification", value.verification)}</div><h3>Copy this into Codex</h3><textarea id="agent-prompt" class="agent-prompt" readonly>${escapeHtml(state.lastAgentPrompt)}</textarea><div class="handoff-actions"><button id="copy-agent-prompt" class="button" type="button">Copy agent prompt</button><span class="muted">The structured version is available through ANAXIGRAPH_FINDING_CONTEXT.</span></div>`;
}

function resultList(title, values = []) {
  const safeValues = values || [];
  return `<div><h3>${escapeHtml(title)} · ${safeValues.length}</h3><ul>${safeValues.slice(0, 30).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>None detected</li>`}</ul></div>`;
}

async function updateFindingStatus(findingId, status) {
  await request(api(`/api/findings/${findingId}/status`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await reloadFindings();
}

async function openFindingHandoff(findingId) {
  switchView("agents");
  byId("agent-result").innerHTML = `<p class="muted">Building affected-file, test, and dependency context for finding #${findingId}…</p>`;
  const value = await request(api(`/api/findings/${findingId}/context`));
  renderFindingHandoff(value);
}

async function handleFindingAction(button) {
  const findingId = Number(button.dataset.finding);
  const action = button.dataset.action;
  button.disabled = true;
  try {
    if (action === "review") {
      await updateFindingStatus(findingId, "acknowledged");
      toast("Finding reviewed; it remains active and monitored.");
    } else if (action === "dismiss") {
      await updateFindingStatus(findingId, "dismissed");
      toast("Finding marked not actionable.");
    } else if (action === "accept") {
      await updateFindingStatus(findingId, "accepted");
      toast("Risk accepted; later scans will continue to monitor the condition.");
    } else if (action === "reopen") {
      await updateFindingStatus(findingId, "acknowledged");
      toast("Finding reopened for review.");
    } else if (action === "plan") {
      await updateFindingStatus(findingId, "planned");
      toast("Finding added to the human-approved agent queue.");
      await openFindingHandoff(findingId);
    } else if (action === "handoff") {
      await openFindingHandoff(findingId);
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

function setupEvents() {
  byId("theme-select").addEventListener("change", (event) => {
    applyTheme(event.target.value);
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      markOnboardingView(button.dataset.view);
      switchView(button.dataset.view);
    });
  });
  document.querySelectorAll("[data-switch]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.switch));
  });
  byId("module-search").addEventListener("input", () => {
    state.modulePage = 1;
    renderModules();
  });
  ["module-area-filter", "module-subsystem-filter", "module-language-filter", "module-include-reference", "module-page-size"]
    .forEach((id) => byId(id).addEventListener("change", () => {
      state.modulePage = 1;
      renderModules();
    }));
  document.querySelectorAll("[data-module-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      const key = button.dataset.moduleSort;
      state.moduleSort = state.moduleSort.key === key
        ? { key, direction: state.moduleSort.direction === "asc" ? "desc" : "asc" }
        : { key, direction: ["path", "architecture_area", "summary"].includes(key) ? "asc" : "desc" };
      state.modulePage = 1;
      renderModules();
    });
  });
  byId("module-previous").addEventListener("click", () => {
    state.modulePage -= 1;
    renderModules();
  });
  byId("module-next").addEventListener("click", () => {
    state.modulePage += 1;
    renderModules();
  });
  byId("module-table-body").addEventListener("click", async (event) => {
    const graphButton = event.target.closest("[data-module-graph]");
    if (graphButton) {
      const node = state.graph.nodes.find((item) => item.path === graphButton.dataset.moduleGraph);
      if (node) {
        switchView("graph");
        window.setTimeout(() => inspectNode(node), 0);
      }
      return;
    }
    const row = event.target.closest(".module-row");
    if (!row) return;
    const id = Number(row.dataset.moduleId);
    state.expandedModuleId = Number(state.expandedModuleId) === id ? null : id;
    renderModules();
    if (Number(state.expandedModuleId) === id) {
      const item = state.modules.find((candidate) => Number(candidate.artifact_id) === id);
      if (item && !state.moduleDetails.has(item.path)) {
        try {
          const detail = await request(api("/api/file", {
            path: item.path,
            snapshot_id: state.overview?.snapshot?.id,
          }));
          state.moduleDetails.set(item.path, detail);
          if (Number(state.expandedModuleId) === id) renderModules();
        } catch (error) {
          toast(error.message, true);
        }
      }
    }
  });
  byId("repository-select").addEventListener("change", async (event) => {
    state.repositoryId = Number(event.target.value);
    window.localStorage.setItem("anaxigraph.repository", state.repositoryId);
    const url = new URL(window.location.href);
    url.searchParams.set("repository", state.repositoryId);
    window.history.replaceState({}, "", url);
    await loadRepository();
  });
  ["overlay-select", "size-select"].forEach((id) => {
    byId(id).addEventListener("change", () => {
      renderOverlayHelp();
      renderLegend();
      drawGraph();
    });
  });
  byId("height-select").addEventListener("change", (event) => {
    const value = event.target.value === "viewport" ? "calc(100vh - 250px)" : `${event.target.value}px`;
    byId("view-graph").style.setProperty("--graph-height", value);
    window.setTimeout(() => {
      layoutGraph();
      drawGraph();
    }, 0);
  });
  byId("fit-graph-button").addEventListener("click", () => {
    layoutGraph();
    drawGraph();
  });
  byId("focus-graph-button").addEventListener("click", () => {
    const layout = document.querySelector(".graph-layout");
    const focused = layout.classList.toggle("focused");
    byId("focus-graph-button").textContent = focused ? "Show inspector" : "Focus";
    window.setTimeout(() => {
      layoutGraph();
      drawGraph();
    }, 0);
  });
  byId("fullscreen-graph-button").addEventListener("click", async () => {
    const panel = document.querySelector(".graph-panel");
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await panel.requestFullscreen();
    } catch (error) {
      toast(`Fullscreen is unavailable: ${error.message}`, true);
    }
  });
  document.addEventListener("fullscreenchange", () => {
    byId("fullscreen-graph-button").textContent = document.fullscreenElement ? "Exit fullscreen" : "Fullscreen";
    window.setTimeout(() => {
      layoutGraph();
      drawGraph();
    }, 0);
  });
  byId("graph-search").addEventListener("input", drawGraph);
  byId("architecture-regions-toggle").addEventListener("change", drawGraph);
  byId("graph-area-options").addEventListener("change", (event) => {
    const input = event.target.closest("[data-graph-area]");
    if (!input) return;
    if (input.checked) state.hiddenGroups.delete(input.dataset.graphArea);
    else state.hiddenGroups.add(input.dataset.graphArea);
    if (state.selectedNode && state.hiddenGroups.has(rootGroup(state.selectedNode))) {
      state.selectedNode = null;
      byId("inspector").innerHTML = `<p class="eyebrow">Module inspector</p><h2>Select a node</h2><p class="muted">Click a graph node to inspect its purpose, interfaces, dependencies, history, and findings.</p>`;
    }
    renderGraphAreaOptions();
    layoutGraph(true);
    drawGraph();
  });
  byId("graph-area-all").addEventListener("click", () => {
    state.hiddenGroups.clear();
    renderGraphAreaOptions();
    layoutGraph(true);
    drawGraph();
  });
  byId("external-toggle").addEventListener("change", async () => {
    const snapshotId = state.graph.snapshot?.id || state.overview?.snapshot?.id;
    state.graph = await request(api("/api/graph", {
      snapshot_id: snapshotId,
      include_external: byId("external-toggle").checked,
    }));
    renderGraphAreaOptions();
    layoutGraph(false);
    drawGraph();
  });
  bindFindingFilters(() => reloadFindings());
  byId("finding-show-all").addEventListener("click", () => reloadFindings({ append: true }));
  byId("findings-table").addEventListener("click", (event) => {
    const button = event.target.closest("[data-finding]");
    if (button) handleFindingAction(button);
  });
  byId("history-range").addEventListener("input", (event) => showHistoryIndex(Number(event.target.value)));
  byId("history-range").addEventListener("change", async (event) => {
    stopHistoryPlayback();
    await graphAtSnapshot(state.snapshots[Number(event.target.value)]?.id);
  });
  byId("history-play-button").addEventListener("click", toggleHistoryPlayback);
  byId("graph-history-play-button").addEventListener("click", toggleHistoryPlayback);
  byId("history-import-button").addEventListener("click", async (event) => {
    event.target.disabled = true;
    try {
      const result = await request(api("/api/history/import"), { method: "POST" });
      toast(historyStartMessage(result.status));
      state.historyInfo = await request(api("/api/history"));
      renderHistory();
    } catch (error) {
      toast(error.message, true);
      event.target.disabled = false;
    }
  });
  byId("history-cancel-button").addEventListener("click", async (event) => {
    try {
      await request(api("/api/history/cancel"), { method: "POST" });
      toast("History import will stop after the current frame.");
      await refreshHistoryData();
    } catch (error) {
      toast(error.message, true);
    }
  });
  byId("refresh-button").addEventListener("click", async (event) => {
    event.target.disabled = true;
    try {
      const stats = await request(api("/api/scan"), { method: "POST" });
      toast(`Scan complete: ${stats.analyzed} analyzed, ${stats.reused} reused`);
      await loadRepository();
    } catch (error) {
      toast(error.message, true);
    } finally {
      event.target.disabled = !selectedRepository()?.scannable;
    }
  });
  byId("semantic-notice").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-semantic-refresh]");
    if (!button) return;
    button.disabled = true;
    try {
      const result = await request(api("/api/semantic/refresh"), { method: "POST" });
      toast(result.status === "started" ? "Repository understanding started." : "Repository understanding is already running.");
      state.semanticStatus = await request(api("/api/semantic"));
      renderOverview();
      scheduleSemanticPoll();
    } catch (error) {
      toast(error.message, true);
      button.disabled = false;
    }
  });
  byId("scope-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await request("/api/agent-scope", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          goal: byId("scope-goal").value,
          branch: byId("scope-branch").value || null,
          repository_id: state.repositoryId,
        }),
      });
      renderAgentResult(value, "scope");
    } catch (error) {
      toast(error.message, true);
    }
  });
  byId("impact-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const value = await request("/api/impact", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          target: byId("impact-target").value,
          repository_id: state.repositoryId,
        }),
      });
      renderAgentResult(value, "impact");
    } catch (error) {
      toast(error.message, true);
    }
  });
  byId("agent-result").addEventListener("click", async (event) => {
    if (event.target.id !== "copy-agent-prompt") return;
    try {
      await navigator.clipboard.writeText(state.lastAgentPrompt);
      toast("Agent prompt copied.");
    } catch (_) {
      byId("agent-prompt")?.select();
      toast("Select and copy the highlighted prompt.");
    }
  });
  byId("onboarding-guide").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-onboarding-action], [data-onboarding-view]");
    if (!button) return;
    if (button.dataset.onboardingAction === "dismiss") {
      updateOnboarding({ dismissed: true });
      return;
    }
    if (button.dataset.onboardingAction === "copy-agent") {
      const command = `codex mcp add anaxigraph --url ${window.location.origin}/mcp`;
      try {
        await navigator.clipboard.writeText(command);
        updateOnboarding({ agent: true });
        toast("Codex MCP command copied.");
      } catch (_) {
        toast("Clipboard access is unavailable; copy the command shown in the guide.", true);
      }
      return;
    }
    if (button.dataset.onboardingView) {
      markOnboardingView(button.dataset.onboardingView);
      switchView(button.dataset.onboardingView);
    }
  });
  byId("view-settings").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-copy-target]");
    if (!button) return;
    const target = byId(button.dataset.copyTarget);
    try {
      await navigator.clipboard.writeText(target?.textContent || "");
      toast("Copied to clipboard.");
    } catch (_) {
      toast("Clipboard access is unavailable; select the text to copy it.", true);
    }
  });
  byId("show-onboarding-button").addEventListener("click", () => {
    updateOnboarding({ dismissed: false });
    switchView("overview");
    byId("onboarding-guide").scrollIntoView({ behavior: "smooth", block: "start" });
  });
  byId("inspector").addEventListener("click", (event) => {
    const target = event.target.closest("[data-path]");
    if (!target?.dataset.path) return;
    const node = state.graph.nodes.find((item) => item.path === target.dataset.path);
    if (node) inspectNode(node);
  });
  setupCanvasEvents();
  let resizeFrame = null;
  const resize = () => {
    window.cancelAnimationFrame(resizeFrame);
    resizeFrame = window.requestAnimationFrame(() => {
      layoutGraph(false);
      drawGraph();
    });
  };
  window.addEventListener("resize", resize);
  if (window.ResizeObserver) new ResizeObserver(resize).observe(document.querySelector(".canvas-wrap"));
}

function setupCanvasEvents() {
  const canvas = byId("graph-canvas");
  let dragging = false;
  let moved = false;
  let last = null;
  canvas.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const px = event.clientX - rect.left;
    const py = event.clientY - rect.top;
    const old = state.transform.scale;
    const next = Math.min(5, Math.max(0.35, old * Math.exp(-event.deltaY * 0.001)));
    state.transform.x = px - (px - state.transform.x) * next / old;
    state.transform.y = py - (py - state.transform.y) * next / old;
    state.transform.scale = next;
    drawGraph();
  }, { passive: false });
  canvas.addEventListener("pointerdown", (event) => {
    dragging = true;
    moved = false;
    last = { x: event.clientX, y: event.clientY };
    canvas.setPointerCapture(event.pointerId);
    canvas.classList.add("dragging");
  });
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const dx = event.clientX - last.x;
    const dy = event.clientY - last.y;
    if (Math.abs(dx) + Math.abs(dy) > 2) moved = true;
    state.transform.x += dx;
    state.transform.y += dy;
    last = { x: event.clientX, y: event.clientY };
    drawGraph();
  });
  canvas.addEventListener("pointerup", (event) => {
    dragging = false;
    canvas.classList.remove("dragging");
    if (moved) return;
    const rect = canvas.getBoundingClientRect();
    const x = (event.clientX - rect.left - state.transform.x) / state.transform.scale;
    const y = (event.clientY - rect.top - state.transform.y) / state.transform.scale;
    const nodes = visibleGraphNodes();
    const metricMaximum = Math.max(...nodes.map(nodeMetric), 1);
    const node = [...nodes].reverse().find((item) => {
      const position = state.positions.get(String(item.id));
      return position && Math.hypot(position.x - x, position.y - y) <= nodeRadius(item, metricMaximum) + 3;
    });
    if (node) inspectNode(node);
  });
}

function markOnboardingView(name) {
  if (["modules", "graph", "history"].includes(name)) {
    updateOnboarding({ explored: true });
  } else if (name === "architecture") {
    updateOnboarding({ reviewed: true });
  }
}

async function reloadFindings({ append = false } = {}) {
  const more = byId("finding-show-all");
  const cursor = append ? state.findingPage?.next_cursor || "" : "";
  if (append && !cursor) return;
  more.disabled = true;
  try {
    const page = await request(api("/api/findings", findingQueryParams(cursor)));
    const items = append ? [...state.findings, ...(page.items || [])] : page.items || [];
    state.findings = items;
    state.findingPage = {
      ...page,
      items,
      shown: items.length,
      omitted: { ...page.omitted, before_cursor: 0 },
    };
    renderFindings();
    renderOverview();
    drawGraph();
  } catch (error) {
    toast(error.message, true);
  } finally {
    more.disabled = false;
  }
}

function switchView(name, preserveGraphCamera = false) {
  document.querySelectorAll(".tab").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((item) => {
    item.classList.toggle("active", item.id === `view-${name}`);
  });
  if (name === "graph") {
    window.setTimeout(() => {
      layoutGraph(!preserveGraphCamera);
      drawGraph();
    }, 0);
  }
}

function toast(message, error = false) {
  const element = byId("toast");
  element.textContent = message;
  element.style.borderColor = error ? "var(--red)" : "";
  element.classList.add("visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("visible"), 4200);
}

function humanize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

function hash(value) {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}

function mix(left, right, amount) {
  const parse = (value) => [1, 3, 5].map((index) => parseInt(value.slice(index, index + 2), 16));
  const a = parse(left);
  const b = parse(right);
  return `rgb(${a.map((value, index) => Math.round(value + (b[index] - value) * amount)).join(",")})`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[character]);
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

setupTheme();
setupEvents();
load();
