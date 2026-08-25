import {
  api,
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  mix,
  request,
  selectedRepository,
  state,
  toast,
} from "/assets/dashboard-core.js";
import {
  consolidationMarkup,
  deadCodeList,
  detailList,
  patternOpportunityList,
} from "/assets/dashboard-format.js";
import { findingCards } from "/assets/findings-view.js";
import {
  architectureColor,
  architectureMixTarget,
  groupColor,
} from "/assets/graph-model.js";

export function selectedHierarchy() {
  const hierarchies = state.overview?.group_hierarchies || {};
  return hierarchies[state.mapLayer] || state.overview?.group_hierarchy || [];
}

export function renderOverview() {
  const value = state.overview || {};
  const graphQuality = value.graph_quality || {};
  const findingCount = Object.values(value.findings || {}).reduce((sum, item) => sum + item, 0);
  const semantic = state.semanticStatus || value.semantic || {};
  const metrics = [
    ["Files", value.files],
    ["Lines of code", value.lines_of_code],
    ["Named code parts", value.symbols],
    ["Direct code links", value.relationships],
    ["Code links matched to files", graphQuality.resolution_rate == null
      ? "No internal refs" : `${(graphQuality.resolution_rate * 100).toFixed(1)}%`],
    ["Decision branches per file (average)", Number(value.average_complexity || 0).toFixed(1)],
    ["Active findings", findingCount],
    ["Files with current AI descriptions", semantic.enabled === false ? "Off"
      : semantic.coverage == null ? "Not started" : `${(semantic.coverage * 100).toFixed(1)}%`],
    ["Line coverage", value.coverage?.line_coverage == null
      ? "No report" : `${(value.coverage.line_coverage * 100).toFixed(1)}%`],
    ["Code links covered by tests", value.coverage?.relationship_coverage == null
      ? "No links" : `${(value.coverage.relationship_coverage * 100).toFixed(1)}%`],
  ];
  byId("metric-grid").innerHTML = metrics.map(([label, metric]) => (
    `<div class="metric"><span>${escapeHtml(label)}</span><strong>${typeof metric === "number" ? format.format(metric) : escapeHtml(metric ?? "—")}</strong></div>`
  )).join("");
  renderBars("language-bars", value.languages || []);
  renderGroupHierarchy(selectedHierarchy());
  byId("finding-preview").innerHTML = findingCards(
    state.findings.slice(0, 10), { glossary: state.glossary, actions: false },
  );
  renderSemanticNotice(semantic);
  renderRepositoryIntelligence(semantic);
  renderGraphQualityNotice(graphQuality);
  renderCoverageNotice(value.coverage || {});
}

function renderGraphQualityNotice(graphQuality) {
  const notice = byId("graph-quality-notice");
  const unresolved = Number(graphQuality.unresolved_internal || 0);
  const ambiguous = Number(graphQuality.ambiguous_internal || 0);
  const fallback = Number(graphQuality.fallback_files || 0);
  const parseErrors = Number(graphQuality.parse_error_files || 0);
  const partial = graphQuality.status === "partial" || fallback > 0 || parseErrors > 0;
  notice.hidden = !partial;
  if (!partial) return;
  const language = graphQuality.plain_language || graphQualityFallback(
    graphQuality, ambiguous, unresolved, fallback, parseErrors,
  );
  const limits = (language.what_this_limits || []).map(
    (item) => `<li>${escapeHtml(item)}</li>`,
  ).join("");
  const actions = (language.what_to_do || []).map(
    (item) => `<li>${escapeHtml(item)}</li>`,
  ).join("");
  notice.innerHTML = `<strong>${escapeHtml(language.conclusion)}</strong>
    <p>${escapeHtml(language.what_was_checked)}</p>
    ${limits ? `<h3>What this limits</h3><ul>${limits}</ul>` : ""}
    ${actions ? `<div class="coverage-next"><strong>What to do</strong><ul>${actions}</ul></div>` : ""}`;
}

function graphQualityFallback(graphQuality, ambiguous, unresolved, fallback, parseErrors) {
  const internal = Number(graphQuality.internal_references || 0);
  const resolved = Number(graphQuality.resolved_internal || 0);
  const missing = ambiguous + unresolved;
  const reasons = [
    missing ? `${countLabel(missing, "likely internal link did", "likely internal links did")} not point to exactly one file` : "",
    fallback ? `${countLabel(fallback, "file was", "files were")} read only as plain text` : "",
    parseErrors ? `${countLabel(parseErrors, "file could", "files could")} not be parsed` : "",
  ].filter(Boolean);
  return {
    conclusion: `The map may miss connections because ${reasons.join("; ")}.`,
    what_was_checked: `AnaxiGraph checked ${countLabel(internal, "likely link", "likely links")} between files. ${format.format(resolved)} pointed to exactly one indexed file.`,
    what_this_limits: [
      "Direct code-link, change-impact, and unused-code advice may be incomplete.",
      "Connections created only while the program runs may not appear in a source-code map.",
    ],
    what_to_do: ["Inspect unclear or missing links before acting on code-link or deletion advice."],
  };
}

function countLabel(value, singular, plural) {
  return `${format.format(value)} ${value === 1 ? singular : plural}`;
}

function renderCoverageNotice(coverage) {
  const notice = byId("coverage-notice");
  const missing = coverage.line_coverage == null;
  notice.hidden = !missing || coverage.required !== true;
  if (notice.hidden) return;
  const inputs = coverage.configured_inputs || [];
  const found = inputs.filter((item) => item.exists).length;
  const rows = inputs.map((item) => (
    `<li><code>${escapeHtml(item.path)}</code><span>${item.exists ? "found" : "missing"}</span></li>`
  )).join("");
  const reason = coverage.state === "unmatched"
    ? "A configured report exists, but none of its file paths matched files in this saved scan."
    : "The selected repository has not generated any configured coverage report. AnaxiGraph deliberately does not execute target code during a scan.";
  notice.innerHTML = `<strong>Required line coverage is unavailable.</strong><p>${escapeHtml(reason)}</p><details><summary>Coverage inputs · ${found}/${inputs.length} found</summary><ul class="coverage-inputs">${rows || "<li>No coverage paths are configured.</li>"}</ul></details><p class="coverage-next">Run the repository's own test or CI command first. <strong>Refresh scan</strong> only imports a report that already exists.</p>`;
}

function renderRepositoryIntelligence(semantic) {
  const panel = byId("repository-intelligence");
  const document = semantic.repository_dossier;
  const value = document?.value;
  panel.hidden = !value;
  if (!value) {
    panel.innerHTML = "";
    return;
  }
  panel.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Whole-repository AI description</p><h2>What this repository does</h2><p class="panel-copy">${escapeHtml(value.summary || "The AI map did not record a repository summary.")}</p><p class="inspector-provenance">Created by ${escapeHtml(semanticProviderLabel(document))}. This is an AI explanation based on indexed evidence; check that evidence before changing code.</p></div></div><div class="repository-intelligence-grid"><div><h3>Role of this repository</h3><p>${escapeHtml(value.architecture_role || value.detailed_summary || "The AI map did not record the repository's role.")}</p><h3>Where new work belongs</h3><p>${escapeHtml(value.placement_guidance || "The AI map did not record where new repository-wide work belongs.")}</p></div><div><h3>Patterns that may fit</h3>${patternOpportunityList(value.pattern_opportunities || [])}${consolidationMarkup(value.consolidation_assessment)}</div><div><h3>Code that may no longer be used</h3>${deadCodeList(value.dead_code_candidates || [])}<h3>Risks and uncertainty</h3>${detailList(value.risks || [], "The AI map did not record a repository-wide risk")}</div></div>`;
}

export function semanticProviderLabel(document = {}) {
  const provider = document.provider || "the configured AI worker";
  if (document.executor_id) {
    return `${provider} via ${document.executor_id}${document.executor_model ? ` · ${document.executor_model}` : ""}`;
  }
  return `${provider}${document.model ? ` · ${document.model}` : ""}`;
}

function renderSemanticNotice(semantic) {
  const notice = byId("semantic-notice");
  const repository = selectedRepository();
  const running = semanticWorkIsActive(semantic);
  if (semantic.semantically_ready && !running) {
    notice.hidden = true;
    return;
  }
  notice.hidden = false;
  const agentFunded = semantic.provider === "agent";
  const current = Number(semantic.current || 0);
  const language = semantic.plain_language || semanticStatusFallback(semantic, running);
  const action = repository?.scannable && semantic.enabled
    ? `<button class="secondary-button" type="button" data-semantic-refresh ${running ? "disabled" : ""}>${agentFunded ? running ? "Agent is mapping…" : "Prepare AI tasks" : running ? "Mapping repository…" : current ? "Resume AI mapping" : "Build AI map"}</button>`
    : "";
  notice.innerHTML = `<div class="semantic-notice-heading"><div>
    <strong>${escapeHtml(language.conclusion)}</strong>
    <p>${escapeHtml(language.progress)}</p><p>${escapeHtml(language.work_state)}</p>
    ${semanticStatusList("Work still to finish", language.remaining_work)}
    ${semanticStatusList("What to do", language.what_to_do)}
    <div class="coverage-next">${(language.how_to_read_progress || []).map((item) => `<p>${escapeHtml(item)}</p>`).join("")}</div>
    </div>${action}</div>`;
}

function semanticStatusFallback(semantic, running) {
  const total = Number(semantic.eligible_modules || 0);
  const current = Number(semantic.current || 0);
  const pending = Number(semantic.pending || 0);
  const pendingMap = Number(semantic.pending_scopes || 0);
  const enabled = Boolean(semantic.enabled);
  return {
    conclusion: !enabled ? "AI mapping is turned off for this repository."
      : running ? "AI mapping is running now and still has work left."
        : "AI mapping is incomplete, and no worker is running right now.",
    progress: enabled
      ? `${format.format(current)} of ${format.format(total)} included files have a current AI description.`
      : "The non-AI file and direct-link map remains available.",
    work_state: running
      ? "A worker is processing saved work now; each completed result is stored immediately."
      : "Unfinished work is safely saved, but it will not finish until a worker starts.",
    remaining_work: [
      `${format.format(pending)} file descriptions and ${format.format(pendingMap)} whole-map steps remain.`,
    ],
    what_to_do: semanticFallbackActions(semantic),
    how_to_read_progress: [
      "Progress counts current file descriptions; it is not a grade for the code.",
      "AI mapping updates only AnaxiGraph's external index; it does not edit repository source.",
      ...(semantic.provider === "agent" ? ["The connected coding agent chooses its runtime model and reasoning effort; AnaxiGraph does not hardcode either one."] : []),
    ],
  };
}

function semanticFallbackActions(semantic) {
  const action = semantic.recommended_action || {};
  if (action.kind === "enable_semantics") {
    return ["Enable AI mapping in the repository's active AnaxiGraph settings."];
  }
  if (action.kind === "scan_required") {
    return ["Run a read-only repository scan, then prepare AI mapping again."];
  }
  if (action.kind === "monitor") {
    return ["Keep the current worker running until this status says the map is complete."];
  }
  if (action.kind === "durable_host_executor") {
    return ["Start a background coding-agent worker and keep it running until the map is complete."];
  }
  if (action.kind === "bounded_mcp_fallback") {
    return ["Have a connected coding agent process each saved task until the map reports complete."];
  }
  return ["Start or resume an AI worker, then keep it running until the map is complete."];
}

function semanticStatusList(title, values = []) {
  if (!values.length) return "";
  return `<div><h3>${escapeHtml(title)}</h3><ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

export function scheduleSemanticPoll() {
  window.clearTimeout(state.semanticPollTimer);
  const worker = state.semanticStatus?.worker || {};
  if (!semanticWorkIsActive(state.semanticStatus || {})) return;
  state.semanticPollTimer = window.setTimeout(async () => {
    try {
      const previous = worker.status;
      state.semanticStatus = await request(api("/api/semantic"));
      renderOverview();
      if (semanticWorkIsActive(state.semanticStatus || {})) {
        scheduleSemanticPoll();
      } else {
        if (previous === "running") toast("Repository understanding refresh finished.");
        await state.reloadRepository?.();
      }
    } catch (error) {
      toast(error.message, true);
    }
  }, 1800);
}

function semanticWorkIsActive(semantic) {
  const worker = semantic.worker || {};
  const jobs = semantic.jobs || {};
  const runningJobs = jobs.running_live == null ? jobs.running : jobs.running_live;
  return ["queued", "running"].includes(worker.status) || Number(runningJobs || 0) > 0;
}

function renderBars(id, items) {
  const maximum = Math.max(...items.map((item) => Number(item.lines_of_code || item.files || 0)), 1);
  byId(id).innerHTML = items.slice(0, 12).map((item) => {
    const value = Number(item.lines_of_code || item.files || 0);
    return `<div class="bar-row"><span>${escapeHtml(item.language || item.name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value / maximum * 100)}%"></div></div><span class="bar-value">${format.format(value)} code lines</span></div>`;
  }).join("") || '<p class="muted">No data yet.</p>';
}

function renderGroupHierarchy(groups) {
  const container = byId("group-bars");
  if (!groups.length) {
    container.innerHTML = '<p class="muted">No groups were detected.</p>';
    return;
  }
  const maximum = Math.max(...groups.map((group) => Number(group.lines_of_code || 0)), 1);
  const repositoryLoc = Math.max(Number(state.overview?.lines_of_code || 0), 1);
  container.innerHTML = groups.slice(0, 14).map((group) => groupMarkup(
    group, maximum, repositoryLoc,
  )).join("");
}

function groupMarkup(group, maximum, repositoryLoc) {
  const color = groupColor(group.name);
  const direct = group.direct_files > 0 && group.children?.length ? [{
    name: `other-${group.name}`,
    label: `Other ${humanize(group.name)}`,
    files: group.direct_files,
    lines_of_code: group.direct_lines_of_code,
    description: "Files not assigned to a smaller group inside this area.",
  }] : [];
  const children = [...(group.children || []), ...direct];
  const description = group.description || group.responsibility
    || (children.length ? `This area contains ${children.length} smaller groups of related work.` : "A group of files with related work.");
  const share = Number(group.lines_of_code || 0) / repositoryLoc * 100;
  const scale = Number(group.lines_of_code || 0) / maximum * 100;
  const childColor = (child) => child.name.startsWith("other-")
    ? mix(color, architectureMixTarget(), 0.22) : architectureColor(child.name);
  const segments = children.length ? children.map((child) => {
    const width = Number(child.lines_of_code || 0) / Math.max(Number(group.lines_of_code || 0), 1) * 100;
    return `<span class="group-segment" style="width:${width}%;background:${childColor(child)}" title="${escapeAttr(child.label || childLabel(child.name, group.name))} · ${format.format(child.lines_of_code || 0)} code lines"></span>`;
  }).join("") : `<span class="group-segment" style="width:100%;background:${color}"></span>`;
  const childHtml = children.length ? `<div class="group-children">${children.map((child) => (
    `<span class="group-child" style="--child-color:${childColor(child)}" title="${escapeAttr(child.description || child.responsibility || "Smaller group of related files")}"><i class="group-child-dot"></i>${escapeHtml(child.label || childLabel(child.name, group.name))}<em>${format.format(child.lines_of_code || 0)} code lines</em></span>`
  )).join("")}</div>` : "";
  const badge = state.mapLayer === "semantic" ? "AI-created map"
    : children.length ? "includes smaller groups" : sourceLabel(group.source);
  return `<article class="group-family" style="--group-color:${color}"><div class="group-family-header"><strong>${escapeHtml(humanize(group.name))}<span class="source-badge">${escapeHtml(badge)}</span></strong><span>${format.format(group.files)} files · ${format.format(group.lines_of_code)} code lines</span></div><p>${escapeHtml(description)}</p><div class="group-scale"><div class="bar-track"><div class="group-bar-fill" style="width:${Math.max(1, scale)}%">${segments}</div></div><span class="group-scale-label">${share.toFixed(1)}% of repository code lines</span></div>${childHtml}</article>`;
}

function sourceLabel(source) {
  return ({ declared: "project setting", inferred: "file-path guess", mixed: "setting + guess", derived: "includes smaller groups", semantic: "AI-created map" })[source] || source || "code area";
}

function childLabel(name, parent) {
  const prefix = `${parent}-`;
  return humanize(name.startsWith(prefix) ? name.slice(prefix.length) : name);
}
