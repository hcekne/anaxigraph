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
import { findingCards } from "/assets/findings-view.js";
import {
  architectureColor,
  architectureMixTarget,
  groupColor,
} from "/assets/graph-model.js";

export function selectedHierarchy() {
  const hierarchies = state.overview?.group_hierarchies || {};
  return hierarchies[state.mapLayer] || [];
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
    state.findings.slice(0, 10),
    { glossary: state.glossary, actions: false, loading: state.findingPage == null },
  );
  renderSemanticNotice(semantic);
  renderRepositoryIntelligence(value.architecture_charter);
  renderGraphQualityNotice(graphQuality);
  renderCoverageNotice(value.coverage || {});
}

function renderGraphQualityNotice(graphQuality) {
  const notice = byId("graph-quality-notice");
  const fallback = Number(graphQuality.fallback_files || 0);
  const parseErrors = Number(graphQuality.parse_error_files || 0);
  const partial = graphQuality.status === "partial" || fallback > 0 || parseErrors > 0;
  notice.hidden = !partial;
  if (!partial) return;
  const language = graphQuality.plain_language;
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

function renderRepositoryIntelligence(value) {
  const panel = byId("repository-intelligence");
  panel.hidden = !value;
  if (!value) {
    panel.innerHTML = "";
    return;
  }
  const statements = (items = []) => items.map(
    (item) => item.presented_statement || item.statement || item.name,
  );
  const unknowns = (value.unknowns || []).map((item) => item.question);
  const conflicts = (value.conflicts || []).map((item) => item.claim);
  const declared = (value.declared_context || []).map(
    (item) => `${item.statement} — ${item.author}: ${item.rationale}`,
  );
  const source = value.state === "provisional"
    ? "Built from static scan facts only. AI review has not confirmed the product meaning yet."
    : value.state === "stale"
      ? "Saved AI understanding is visible, but changed code evidence still needs review."
    : `Created by ${semanticProviderLabel(value.provenance)}. Every claim should point back to indexed evidence; uncertainty stays visible.`;
  const purpose = value.purpose?.presented_statement || value.purpose?.statement;
  panel.innerHTML = `<header class="charter-header"><div class="charter-heading"><div><p class="eyebrow">Living Architecture Charter</p><h2>What this repository does</h2></div><span class="charter-state">${escapeHtml(humanize(value.state))}</span></div><p class="charter-purpose">${escapeHtml(purpose || "The Charter did not record a purpose.")}</p><p class="charter-provenance">${escapeHtml(source)}</p></header><div class="repository-intelligence-grid">${charterSection("Observable capabilities", statements(value.capabilities), "No capability has enough evidence yet")}${charterSection("Responsibility areas", statements(value.responsibilities), "No responsibility has enough evidence yet")}${charterSection("Important flows", statements(value.execution_flows), "No execution flow has enough evidence yet")}${charterSection("Safe extension points", statements(value.extension_points), "No extension point has enough evidence yet")}${charterSection("Coherence concerns", statements(value.coherence_concerns), "No current coherence concern was recorded", "attention")}${charterSection("Unknowns and conflicts", [...unknowns, ...conflicts], "No unresolved unknown or conflict was recorded", "question")}${charterSection("Declared context", declared, "No human or principal correction has been added")}</div>`;
}

function charterSection(title, values, empty, tone = "") {
  const items = values.length ? values : [empty];
  const count = values.length ? String(values.length) : "0";
  return `<section class="charter-section${tone ? ` charter-section-${tone}` : ""}"><header><h3>${escapeHtml(title)}</h3><span aria-label="${count} recorded items">${count}</span></header><ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></section>`;
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
  const language = semantic.plain_language;
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

function semanticStatusList(title, values = []) {
  if (!values.length) return "";
  return `<div><h3>${escapeHtml(title)}</h3><ul>${values.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul></div>`;
}

export function scheduleSemanticPoll() {
  window.clearTimeout(state.semanticPollTimer);
  const worker = state.semanticStatus?.worker || {};
  if (!semanticWorkIsActive(state.semanticStatus || {})) return;
  state.semanticPollTimer = window.setTimeout(async () => {
    const repositoryLoadToken = state.repositoryLoadToken;
    try {
      const previous = worker.status;
      const semanticStatus = await request(api("/api/semantic"));
      if (repositoryLoadToken !== state.repositoryLoadToken) return;
      state.semanticStatus = semanticStatus;
      renderOverview();
      if (semanticWorkIsActive(state.semanticStatus || {})) {
        scheduleSemanticPoll();
      } else {
        if (previous === "running") toast("Repository understanding refresh finished.");
        await state.reloadRepository?.();
      }
    } catch (error) {
      if (repositoryLoadToken === state.repositoryLoadToken) toast(error.message, true);
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
  const copy = groupCopy(group);
  const direct = group.direct_files > 0 && group.children?.length ? [{
    name: `other-${group.name}`,
    label: `Other ${humanize(group.name)}`,
    files: group.direct_files,
    lines_of_code: group.direct_lines_of_code,
    description: "Files not assigned to a smaller group inside this area.",
  }] : [];
  const children = [...(group.children || []), ...direct];
  const description = groupDescription(copy.language, group, children.length);
  const nameMeaning = groupNameMeaning(copy.language, copy.label);
  const share = Number(group.lines_of_code || 0) / repositoryLoc * 100;
  const scale = Number(group.lines_of_code || 0) / maximum * 100;
  const childColor = (child) => child.name.startsWith("other-")
    ? mix(color, architectureMixTarget(), 0.22) : architectureColor(child.name);
  const segments = children.length ? children.map((child) => {
    const width = Number(child.lines_of_code || 0) / Math.max(Number(group.lines_of_code || 0), 1) * 100;
    return `<span class="group-segment" style="width:${width}%;background:${childColor(child)}" title="${escapeAttr(groupChildLabel(child, group.name))} · ${format.format(child.lines_of_code || 0)} code lines"></span>`;
  }).join("") : `<span class="group-segment" style="width:100%;background:${color}"></span>`;
  const childHtml = children.length ? `<div class="group-children">${children.map((child) => (
    `<span class="group-child" style="--child-color:${childColor(child)}" title="${escapeAttr(groupChildDescription(child))}"><i class="group-child-dot"></i>${escapeHtml(groupChildLabel(child, group.name))}<em>${format.format(child.lines_of_code || 0)} code lines</em></span>`
  )).join("")}</div>` : "";
  const badge = state.mapLayer === "responsibility" ? "inferred responsibility"
    : children.length ? "includes smaller groups" : sourceLabel(group.source);
  return `<article class="group-family" style="--group-color:${color}"><div class="group-family-header"><strong>${escapeHtml(copy.label)}<span class="source-badge">${escapeHtml(badge)}</span></strong><span>${format.format(group.files)} files · ${format.format(group.lines_of_code)} code lines</span></div>${nameMeaning}<p>${escapeHtml(description)}</p><div class="group-scale"><div class="bar-track"><div class="group-bar-fill" style="width:${Math.max(1, scale)}%">${segments}</div></div><span class="group-scale-label">${share.toFixed(1)}% of repository code lines</span></div>${childHtml}</article>`;
}

function groupCopy(group) {
  const language = group.plain_language || {};
  return {
    label: language.display_name || group.label || humanize(group.name),
    language,
  };
}

function groupDescription(language, group, childCount) {
  if (language.what_this_group_does) return language.what_this_group_does;
  if (group.description || group.responsibility) return group.description || group.responsibility;
  return childCount
    ? `This area contains ${childCount} smaller groups of related work.`
    : "A group of files with related work.";
}

function groupNameMeaning(language, label) {
  if (!language.name_and_meaning || language.name_and_meaning === label) return "";
  return `<p class="muted">${escapeHtml(language.name_and_meaning)}</p>`;
}

function groupChildDescription(child) {
  return child.plain_language?.what_this_group_does
    || child.description
    || child.responsibility
    || "Smaller group of related files";
}

function groupChildLabel(child, parent) {
  return child.plain_language?.display_name
    || child.label
    || childLabel(child.name, parent);
}

function sourceLabel(source) {
  return ({ declared: "declared intent", path: "path map", mixed: "mixed evidence", missing: "not declared", derived: "includes smaller groups", responsibility: "inferred responsibility" })[source] || source || "code area";
}

function childLabel(name, parent) {
  const prefix = `${parent}-`;
  return humanize(name.startsWith(prefix) ? name.slice(prefix.length) : name);
}
