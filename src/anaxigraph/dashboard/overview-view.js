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
    ["Symbols", value.symbols],
    ["Dependencies", value.relationships],
    ["Internal link resolution", graphQuality.resolution_rate == null
      ? "No internal refs" : `${(graphQuality.resolution_rate * 100).toFixed(1)}%`],
    ["Avg complexity", Number(value.average_complexity || 0).toFixed(1)],
    ["Active findings", findingCount],
    ["AI understanding", semantic.enabled === false ? "Off"
      : semantic.coverage == null ? "Not started" : `${(semantic.coverage * 100).toFixed(1)}%`],
    ["Line coverage", value.coverage?.line_coverage == null
      ? "No report" : `${(value.coverage.line_coverage * 100).toFixed(1)}%`],
    ["Test-linked dependencies", value.coverage?.relationship_coverage == null
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
  const resolution = graphQuality.resolution_rate == null
    ? "No internal references were available to score."
    : `${(graphQuality.resolution_rate * 100).toFixed(1)}% of likely internal references resolved to one indexed module.`;
  notice.innerHTML = `<strong>Graph evidence is partial, and advice is confidence-gated.</strong><p>${escapeHtml(resolution)} ${format.format(ambiguous)} ambiguous and ${format.format(unresolved)} unresolved internal reference(s) are retained rather than silently discarded. ${format.format(fallback)} file(s) use fallback analysis${parseErrors ? `; ${format.format(parseErrors)} file(s) have parse errors` : ""}. Dead-code suggestions are suppressed when relationship resolution is too weak.</p><p class="coverage-next">${escapeHtml(graphQuality.extraction_caveat || graphQuality.caveat || "Dynamic runtime wiring may not appear in a static graph.")}</p>`;
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
    ? "A configured report exists, but none of its file paths matched modules in this snapshot."
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
  panel.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Repository-level AI synthesis</p><h2>Architectural understanding</h2><p class="panel-copy">${escapeHtml(value.summary || "No repository summary recorded.")}</p><p class="inspector-provenance">${escapeHtml(semanticProviderLabel(document))} · AI-generated interpretation; check its evidence before changing code.</p></div></div><div class="repository-intelligence-grid"><div><h3>Architecture role</h3><p>${escapeHtml(value.architecture_role || value.detailed_summary || "No architecture role recorded.")}</p><h3>Where new work belongs</h3><p>${escapeHtml(value.placement_guidance || "No repository-level placement guidance recorded.")}</p></div><div><h3>Pattern opportunities</h3>${patternOpportunityList(value.pattern_opportunities || [])}${consolidationMarkup(value.consolidation_assessment)}</div><div><h3>Code that may no longer be used</h3>${deadCodeList(value.dead_code_candidates || [])}<h3>Risks and uncertainty</h3>${detailList(value.risks || [], "No repository-level semantic risk recorded")}</div></div>`;
}

export function semanticProviderLabel(document = {}) {
  const provider = document.provider || "semantic provider";
  if (document.executor_id) {
    return `${provider} via ${document.executor_id}${document.executor_model ? ` · ${document.executor_model}` : ""}`;
  }
  return `${provider}${document.model ? ` · ${document.model}` : ""}`;
}

function renderSemanticNotice(semantic) {
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
  const taxonomy = semantic.taxonomy || {};
  if (semantic.semantically_ready && !running) {
    notice.hidden = true;
    return;
  }
  notice.hidden = false;
  if (!semantic.enabled) {
    notice.innerHTML = '<strong>AI module understanding is not enabled.</strong><p>The deterministic graph is available. Enable <code>semantic.provider: agent</code> to build the semantic map with a connected coding agent.</p>';
    return;
  }
  const agentFunded = semantic.provider === "agent";
  const taxonomyCopy = taxonomy.enabled
    ? taxonomy.ready
      ? ` The semantic hierarchy passed ${format.format(taxonomy.current?.review_passes || 0)} autonomous review pass(es).`
      : " The repository taxonomy is still awaiting proposal, agent critique, or deterministic validation."
    : "";
  const statusCopy = agentFunded
    ? running ? "A connected coding agent has leased semantic work and is mapping the repository."
      : `${format.format(current)} of ${format.format(total)} eligible modules have current dossiers. The remaining queue is ready for the durable host executor; direct AnaxiMCP work is a bounded fallback.`
    : running ? "The semantic worker is reading stale modules and synthesizing architectural context."
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
    : running ? "Semantic mapping is running." : "Repository understanding is incomplete.";
  const incrementalCopy = agentFunded
    ? "The coding agent uses its own model and tokens. Hashes ensure later sessions receive only missing or stale work."
    : "Hashes keep later refreshes incremental; unchanged source is not sent to the model again unless its configured age policy expires.";
  notice.innerHTML = `<div class="semantic-notice-heading"><div><strong>${heading}</strong><p>${escapeHtml(statusCopy)} ${format.format(pending)} module job(s) and ${format.format(semantic.pending_scopes || 0)} synthesis scope(s) are pending; ${format.format(failed)} module(s) and ${format.format(failedScopes)} synthesis scope(s) failed; ${format.format(excluded)} module(s) are explicitly excluded.${escapeHtml(budgetCopy)}${escapeHtml(taxonomyCopy)}</p><p class="coverage-next">${escapeHtml(incrementalCopy)} Semantic maps are metadata only; proposal, independent agent review, and deterministic validation run automatically.</p></div>${action}</div>`;
}

export function scheduleSemanticPoll() {
  window.clearTimeout(state.semanticPollTimer);
  const worker = state.semanticStatus?.worker || {};
  if (!["queued", "running"].includes(worker.status)
      && !Number(state.semanticStatus?.jobs?.running || 0)) return;
  state.semanticPollTimer = window.setTimeout(async () => {
    try {
      const previous = worker.status;
      state.semanticStatus = await request(api("/api/semantic"));
      renderOverview();
      if (["queued", "running"].includes(state.semanticStatus?.worker?.status)
          || Number(state.semanticStatus?.jobs?.running || 0)) {
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

function renderBars(id, items) {
  const maximum = Math.max(...items.map((item) => Number(item.lines_of_code || item.files || 0)), 1);
  byId(id).innerHTML = items.slice(0, 12).map((item) => {
    const value = Number(item.lines_of_code || item.files || 0);
    return `<div class="bar-row"><span>${escapeHtml(item.language || item.name)}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, value / maximum * 100)}%"></div></div><span class="bar-value">${format.format(value)} LOC</span></div>`;
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
    description: "Files not assigned to a more specific subsystem.",
  }] : [];
  const children = [...(group.children || []), ...direct];
  const description = group.description || group.responsibility
    || (children.length ? `Roll-up of ${children.length} architecture subgroups.` : "Architecture group.");
  const share = Number(group.lines_of_code || 0) / repositoryLoc * 100;
  const scale = Number(group.lines_of_code || 0) / maximum * 100;
  const childColor = (child) => child.name.startsWith("other-")
    ? mix(color, architectureMixTarget(), 0.22) : architectureColor(child.name);
  const segments = children.length ? children.map((child) => {
    const width = Number(child.lines_of_code || 0) / Math.max(Number(group.lines_of_code || 0), 1) * 100;
    return `<span class="group-segment" style="width:${width}%;background:${childColor(child)}" title="${escapeAttr(child.label || childLabel(child.name, group.name))} · ${format.format(child.lines_of_code || 0)} LOC"></span>`;
  }).join("") : `<span class="group-segment" style="width:100%;background:${color}"></span>`;
  const childHtml = children.length ? `<div class="group-children">${children.map((child) => (
    `<span class="group-child" style="--child-color:${childColor(child)}" title="${escapeAttr(child.description || child.responsibility || "Architecture subgroup")}"><i class="group-child-dot"></i>${escapeHtml(child.label || childLabel(child.name, group.name))}<em>${format.format(child.lines_of_code || 0)} LOC</em></span>`
  )).join("")}</div>` : "";
  const badge = state.mapLayer === "semantic" ? "AI taxonomy"
    : children.length ? "area roll-up" : sourceLabel(group.source);
  return `<article class="group-family" style="--group-color:${color}"><div class="group-family-header"><strong>${escapeHtml(humanize(group.name))}<span class="source-badge">${escapeHtml(badge)}</span></strong><span>${format.format(group.files)} files · ${format.format(group.lines_of_code)} LOC</span></div><p>${escapeHtml(description)}</p><div class="group-scale"><div class="bar-track"><div class="group-bar-fill" style="width:${Math.max(1, scale)}%">${segments}</div></div><span class="group-scale-label">${share.toFixed(1)}% of repo LOC</span></div>${childHtml}</article>`;
}

function sourceLabel(source) {
  return ({ declared: "configured", inferred: "inferred fallback", mixed: "configured + fallback", derived: "area roll-up", semantic: "AI taxonomy" })[source] || source || "group";
}

function childLabel(name, parent) {
  const prefix = `${parent}-`;
  return humanize(name.startsWith(prefix) ? name.slice(prefix.length) : name);
}
