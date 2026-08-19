const state = {
  repositories: [],
  repositoryId: null,
  glossary: null,
  overview: null,
  graph: { nodes: [], edges: [], snapshot: null },
  findings: [],
  snapshots: [],
  trends: [],
  historyInfo: null,
  selectedNode: null,
  highlightedPaths: new Set(),
  protectedPaths: new Set(),
  conflictPaths: new Set(),
  transform: { x: 0, y: 0, scale: 1 },
  positions: new Map(),
  groupRegions: [],
  groupParents: new Map(),
  groupRoots: [],
  historyPlayToken: 0,
  historyPlaying: false,
  historyPollTimer: null,
  lastAgentPrompt: "",
};

const colors = [
  "#72e0b3", "#7db8ff", "#f4bd69", "#b99cf7",
  "#f07970", "#5fd0df", "#d2e274", "#f3a9d0",
];
const byId = (id) => document.getElementById(id);
const format = new Intl.NumberFormat();

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
    const remembered = Number(window.localStorage.getItem("codeintel.repository"));
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
  try {
    const [overview, graph, findings, snapshots, trends, historyInfo] = await Promise.all([
      request(api("/api/overview")),
      request(api("/api/graph")),
      request(api("/api/findings")),
      request(api("/api/snapshots")),
      request(api("/api/trends")),
      request(api("/api/history")),
    ]);
    state.overview = overview;
    state.graph = graph;
    state.findings = findings;
    state.snapshots = snapshots;
    state.trends = trends.snapshots || [];
    state.historyInfo = historyInfo;
    state.selectedNode = null;
    state.highlightedPaths.clear();
    state.protectedPaths.clear();
    state.conflictPaths.clear();
    buildGroupIndex(overview.group_hierarchy || []);

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
  const findingCount = Object.values(value.findings || {}).reduce((sum, item) => sum + item, 0);
  const metrics = [
    ["Files", value.files],
    ["Lines of code", value.lines_of_code],
    ["Symbols", value.symbols],
    ["Dependencies", value.relationships],
    ["Avg complexity", Number(value.average_complexity || 0).toFixed(1)],
    ["Active findings", findingCount],
    [
      "Line coverage",
      value.coverage?.line_coverage == null
        ? "Not imported"
        : `${(value.coverage.line_coverage * 100).toFixed(1)}%`,
    ],
  ];
  byId("metric-grid").innerHTML = metrics.map(([label, metric]) => (
    `<div class="metric"><span>${escapeHtml(label)}</span><strong>${typeof metric === "number" ? format.format(metric) : escapeHtml(metric ?? "—")}</strong></div>`
  )).join("");
  renderBars("language-bars", value.languages || []);
  renderGroupHierarchy(value.group_hierarchy || []);
  byId("finding-preview").innerHTML = findingCards(
    state.findings.filter((item) => !["resolved", "dismissed"].includes(item.status)).slice(0, 6),
    false,
  );

  const notice = byId("coverage-notice");
  const coverageMissing = value.coverage?.line_coverage == null;
  notice.hidden = !coverageMissing;
  if (coverageMissing) {
    notice.textContent = `${state.glossary?.coverage?.missing || "No coverage input was imported."} Generate a configured coverage.xml or lcov.info file, then refresh the scan.`;
  }
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
    const childHtml = children.length
      ? `<div class="group-children">${children.map((child) => (
        `<span class="group-child" title="${escapeAttr(child.description || "Architecture subgroup")}">${escapeHtml(child.label || childLabel(child.name, group.name))}<em>${format.format(child.lines_of_code || 0)} LOC</em></span>`
      )).join("")}</div>`
      : `<div class="bar-track"><div class="bar-fill" style="width:100%;background:${color}"></div></div>`;
    return `<article class="group-family" style="--group-color:${color}"><div class="group-family-header"><strong>${escapeHtml(humanize(group.name))}<span class="source-badge">${escapeHtml(sourceLabel(group.source))}</span></strong><span>${format.format(group.files)} files · ${format.format(group.lines_of_code)} LOC</span></div><p>${escapeHtml(description)}</p>${childHtml}</article>`;
  }).join("");
}

function sourceLabel(source) {
  return ({ declared: "configured", inferred: "inferred", mixed: "mixed", derived: "roll-up" })[source] || source || "group";
}

function childLabel(name, parent) {
  const prefix = `${parent}-`;
  return humanize(name.startsWith(prefix) ? name.slice(prefix.length) : name);
}

function findingCards(items, actions = true) {
  if (!items.length) return `<p class="muted">No findings in this view.</p>`;
  return items.map((item) => {
    const guide = state.glossary?.findings?.statuses?.[item.status];
    const status = guide?.label || humanize(item.status);
    const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% detection confidence`;
    const confidenceHelp = state.glossary?.findings?.confidence || "Confidence describes detector evidence, not severity.";
    const action = item.recommended_action
      ? `<div class="finding-action-copy"><strong>Suggested next step</strong><p>${escapeHtml(item.recommended_action)}</p></div>`
      : "";
    const tags = item.affected_artifacts?.length
      ? `<div class="tag-list">${item.affected_artifacts.slice(0, 8).map((path) => `<span class="tag">${escapeHtml(path)}</span>`).join("")}</div>`
      : "";
    return `<article class="finding-card"><span class="severity ${escapeHtml(item.severity)}"></span><div><div class="finding-meta">${escapeHtml(humanize(item.finding_type))} · ${escapeHtml(status)} · <span class="finding-provenance" title="${escapeAttr(confidenceHelp)}">${escapeHtml(confidence)}</span> · ${escapeHtml(item.source || "deterministic")}</div><h3>${escapeHtml(item.summary)}</h3><p>${escapeHtml(item.explanation)}</p>${action}${tags}</div>${actions ? findingActionButtons(item) : ""}</article>`;
  }).join("");
}

function findingActionButtons(item) {
  const buttons = [];
  if (["new", "regressed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="review">Mark reviewed</button>`);
  }
  if (!["planned", "resolved", "dismissed"].includes(item.status)) {
    buttons.push(`<button class="primary-action" data-finding="${item.id}" data-action="plan">Plan agent work</button>`);
  }
  if (item.status === "planned") {
    buttons.push(`<button class="primary-action" data-finding="${item.id}" data-action="handoff">Open agent handoff</button>`);
  }
  if (!["resolved", "dismissed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="dismiss">Not actionable</button>`);
  }
  if (item.status === "dismissed") {
    buttons.push(`<button data-finding="${item.id}" data-action="reopen">Reopen</button>`);
  }
  return `<div class="finding-actions">${buttons.join("")}</div>`;
}

function renderFindings() {
  const filter = byId("finding-status-filter").value;
  const items = filter === "all"
    ? state.findings
    : filter === "active"
      ? state.findings.filter((item) => !["resolved", "dismissed"].includes(item.status))
      : state.findings.filter((item) => item.status === filter);
  byId("findings-table").innerHTML = findingCards(items);
}

function renderWorkflowGuide() {
  const statuses = state.glossary?.findings?.statuses || {};
  const ordered = ["new", "acknowledged", "planned", "resolved", "dismissed"];
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

function architectureColor(group) {
  const parent = state.groupParents.get(group) || group;
  const base = groupColor(parent);
  if (parent === group) return base;
  return mix(base, "#ffffff", 0.08 + (hash(group) % 13) / 100);
}

function layoutGraph(resetView = true) {
  const nodes = state.graph.nodes || [];
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
  state.groupRoots.forEach((root) => {
    const map = new Map();
    seedGroup(map, root);
    roots.set(root.name, map);
  });
  grouped.forEach((members, group) => {
    const root = state.groupParents.get(group) || group;
    if (!roots.has(root)) roots.set(root, new Map());
    roots.get(root).set(group, members);
  });
  const rootNames = [...roots.keys()].sort((left, right) => {
    const leftOrder = rootOrder.get(left) ?? 10_000;
    const rightOrder = rootOrder.get(right) ?? 10_000;
    return leftOrder - rightOrder || left.localeCompare(right);
  });
  const aspect = Math.max(0.65, Math.min(1.8, width / height));
  const columns = Math.max(1, Math.ceil(Math.sqrt(rootNames.length * aspect)));
  const rows = Math.ceil(rootNames.length / columns);
  const cellW = width / columns;
  const cellH = height / Math.max(rows, 1);
  state.positions.clear();
  state.groupRegions = [];
  rootNames.forEach((root, index) => {
    const col = index % columns;
    const row = Math.floor(index / columns);
    const padding = Math.max(12, Math.min(cellW, cellH) * 0.045);
    const region = {
      root,
      x: col * cellW + padding,
      y: row * cellH + padding,
      width: Math.max(10, cellW - padding * 2),
      height: Math.max(10, cellH - padding * 2),
      color: groupColor(root),
    };
    state.groupRegions.push(region);
    const subgroups = [...roots.get(root).keys()].sort();
    const usableY = region.y + 24;
    const usableH = Math.max(10, region.height - 28);
    const subAspect = Math.max(0.7, region.width / usableH);
    const subColumns = Math.max(1, Math.ceil(Math.sqrt(subgroups.length * subAspect)));
    const subRows = Math.ceil(subgroups.length / subColumns);
    const subW = region.width / subColumns;
    const subH = usableH / Math.max(1, subRows);
    subgroups.forEach((group, groupIndex) => {
      const groupCol = groupIndex % subColumns;
      const groupRow = Math.floor(groupIndex / subColumns);
      const centerX = region.x + (groupCol + 0.5) * subW;
      const centerY = usableY + (groupRow + 0.5) * subH;
      roots.get(root).get(group).forEach((node) => {
        const value = hash(node.path);
        const angle = (value % 3600) / 3600 * Math.PI * 2;
        const distribution = Math.sqrt(((value >>> 10) % 1000) / 1000);
        const radius = Math.min(subW, subH) * (0.08 + distribution * 0.34);
        state.positions.set(String(node.id), {
          x: centerX + Math.cos(angle) * radius,
          y: centerY + Math.sin(angle) * radius,
          group,
        });
      });
    });
  });
  if (resetView) state.transform = { x: 0, y: 0, scale: 1 };
  renderLegend();
}

function nodeMetric(node) {
  return Math.max(0, Number(node[byId("size-select").value] || 0));
}

function nodeRadius(node, maximum) {
  return 3.2 + Math.sqrt(nodeMetric(node) / Math.max(maximum, 1)) * 10;
}

function groupColor(group) {
  return colors[Math.abs(hash(group)) % colors.length];
}

function heat(value, maximum, cool = "#72e0b3", hot = "#f07970") {
  const amount = Math.min(1, Math.max(0, value / Math.max(maximum, 1)));
  return mix(cool, hot, amount);
}

function nodeColor(node) {
  const overlay = byId("overlay-select").value;
  if (overlay === "architecture") return architectureColor(effectiveGroup(node));
  if (overlay === "coupling") return heat(Number(node.fan_in) + Number(node.fan_out), 25, "#436b61", "#f07970");
  if (overlay === "complexity") return heat(Number(node.complexity), 60, "#72e0b3", "#f07970");
  if (overlay === "coverage") return node.line_coverage == null ? "#3e504b" : heat(1 - Number(node.line_coverage), 1, "#72e0b3", "#f07970");
  if (overlay === "change") return heat(Number(node.change_count || 0), 30, "#4c6660", "#f4bd69");
  if (overlay === "drift") return node.declared_group && node.inferred_group && node.declared_group !== node.inferred_group ? "#f07970" : "#46645b";
  if (overlay === "dead-code") {
    const dead = state.findings.some((finding) => finding.finding_type === "possible_dead_code"
      && finding.affected_artifacts?.includes(node.path)
      && !["resolved", "dismissed"].includes(finding.status));
    return dead ? "#f4bd69" : "#40534d";
  }
  if (overlay === "agent") {
    if (state.conflictPaths.has(node.path)) return "#f07970";
    if (state.protectedPaths.has(node.path)) return "#f4bd69";
    if (state.highlightedPaths.has(node.path)) return "#72e0b3";
    return "#344943";
  }
  return "#72e0b3";
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
  const visibleIds = new Set(state.graph.nodes.map((node) => String(node.id)));
  const metricMaximum = Math.max(...state.graph.nodes.map(nodeMetric), 1);
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
      context.globalAlpha = 0.72;
      context.fillStyle = region.color;
      context.font = `${11 / scale}px ui-sans-serif, system-ui, sans-serif`;
      context.fillText(humanize(region.root), region.x + 10 / scale, region.y + 17 / scale);
    });
    context.globalAlpha = 1;
  }
  const edgeLimit = scale < 0.8 ? 1600 : 5000;
  state.graph.edges.slice(0, edgeLimit).forEach((edge) => {
    const source = state.positions.get(String(edge.source));
    const target = state.positions.get(String(edge.target));
    if (!source || !target || !visibleIds.has(String(edge.target))) return;
    context.strokeStyle = "rgba(145,170,161,.11)";
    context.lineWidth = Math.min(2.4, 0.35 + Math.log2(Number(edge.weight || 1) + 1) * 0.35) / scale;
    context.beginPath();
    context.moveTo(source.x, source.y);
    context.lineTo(target.x, target.y);
    context.stroke();
  });
  const search = byId("graph-search").value.trim().toLowerCase();
  state.graph.nodes.forEach((node) => {
    const position = state.positions.get(String(node.id));
    if (!position) return;
    const radius = nodeRadius(node, metricMaximum);
    const matches = !search || `${node.path} ${node.summary}`.toLowerCase().includes(search);
    context.globalAlpha = matches ? 1 : 0.12;
    context.fillStyle = nodeColor(node);
    context.beginPath();
    context.arc(position.x, position.y, radius, 0, Math.PI * 2);
    context.fill();
    if (state.selectedNode && String(state.selectedNode.id) === String(node.id)) {
      context.strokeStyle = "#ffffff";
      context.lineWidth = 2 / scale;
      context.stroke();
    }
    if (scale > 1.25 && radius > 4.5 && matches) {
      context.fillStyle = "rgba(234,245,240,.78)";
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
  let items;
  if (overlay === "architecture") {
    items = state.groupRoots.slice(0, 12).map((group) => [humanize(group.name), groupColor(group.name)]);
  } else if (overlay === "agent") {
    items = [["Task context", "#72e0b3"], ["Protected", "#f4bd69"], ["Branch collision", "#f07970"]];
  } else if (overlay === "coverage" && state.graph.nodes.every((node) => node.line_coverage == null)) {
    items = [["No imported coverage", "#3e504b"]];
  } else if (overlay === "drift") {
    items = [["Matches / no declaration", "#46645b"], ["Configured and inferred differ", "#f07970"]];
  } else if (overlay === "dead-code") {
    items = [["No signal", "#40534d"], ["Inspect static reachability", "#f4bd69"]];
  } else {
    items = [["Lower signal", "#436b61"], ["Higher signal", overlay === "change" ? "#f4bd69" : "#f07970"]];
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
  panel.innerHTML = `<p class="eyebrow">Module inspector</p><h2>${escapeHtml(node.path)}</h2><p class="muted">Loading details…</p>`;
  if (String(node.id).startsWith("external:")) {
    panel.innerHTML = `<p class="eyebrow">External dependency</p><h2>${escapeHtml(node.path)}</h2><p class="muted">This node is referenced by repository code but is not a file analyzed inside this repository.</p>`;
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
    panel.innerHTML = `<p class="eyebrow">${escapeHtml(effectiveGroup(file))}</p><h2>${escapeHtml(file.path)}</h2><p class="muted">${escapeHtml(file.summary)}</p><dl><dt>Language</dt><dd>${escapeHtml(file.language)}</dd><dt>LOC</dt><dd>${format.format(file.lines_of_code)}</dd><dt>Complexity</dt><dd>${file.complexity}</dd><dt title="Changes when any source byte changes">Raw hash</dt><dd>${escapeHtml(String(file.raw_hash || "").slice(0, 10))}</dd><dt title="Tracks normalized code structure and ignores some metadata-only edits">Structural hash</dt><dd>${escapeHtml(String(file.structural_hash || "").slice(0, 10))}</dd><dt>Last analysis</dt><dd>${escapeHtml(file.analysis_status)}</dd></dl><h3>Detected responsibilities</h3><div class="tag-list">${responsibilities || `<span class="muted">No structured semantic claim yet</span>`}</div><h3>Public interfaces</h3><div class="tag-list">${(file.public_interfaces || []).slice(0, 18).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || `<span class="muted">None detected</span>`}</div><h3>Uses</h3><div class="relation-list">${relationships || `<span class="muted">No outgoing relationship detected</span>`}</div><h3>Used by</h3><div class="relation-list">${dependants || `<span class="muted">No incoming relationship detected</span>`}</div><h3>Recent changes</h3><div class="relation-list">${detail.history.slice(0, 6).map((item) => `<span class="muted">${escapeHtml(item.commit_sha.slice(0, 8))} · ${escapeHtml(item.subject)}</span>`).join("") || `<span class="muted">No Git history loaded</span>`}</div>`;
  } catch (error) {
    panel.innerHTML += `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function renderHistory() {
  const snapshots = state.snapshots;
  const info = state.historyInfo || {};
  const job = info.job || {};
  const range = byId("history-range");
  range.max = Math.max(0, snapshots.length - 1);
  range.value = Math.max(0, snapshots.length - 1);
  range.disabled = snapshots.length < 2;
  byId("history-commits").innerHTML = snapshots.length
    ? `<span>${escapeHtml(String(snapshots[0].commit_sha).slice(0, 8))}</span><span>${escapeHtml(String(snapshots.at(-1).commit_sha).slice(0, 8))}</span>`
    : "";
  if (["queued", "running"].includes(job.status)) {
    const progress = job.total ? ` ${job.completed || 0}/${job.total}` : "";
    byId("history-help").textContent = `Importing${progress} graph frames from the repository's first-parent Git history. The dashboard remains available while this runs.`;
  } else if (info.total_commits > 0 && snapshots.length > 1) {
    const sampling = info.total_commits > info.analyzed_commits
      ? `${info.analyzed_commits} representative graph frames across all ${info.total_commits} first-parent commits`
      : `${info.analyzed_commits} commit graph frames`;
    byId("history-help").textContent = `${sampling}, spanning the initial commit through HEAD. Scrub the timeline or replay the architecture biography.`;
  } else if (info.total_commits > 0) {
    byId("history-help").textContent = `Git contains ${info.total_commits} first-parent commits. Import its architecture biography to replay from the initial commit.`;
  } else {
    byId("history-help").textContent = "This mounted directory has no Git commit history, so only its current working tree can be shown.";
  }
  byId("history-play-button").disabled = snapshots.length < 2;
  byId("graph-history-play-button").disabled = snapshots.length < 2;
  const importButton = byId("history-import-button");
  importButton.disabled = info.total_commits < 1 || ["queued", "running"].includes(job.status);
  importButton.textContent = ["queued", "running"].includes(job.status)
    ? "Importing history…"
    : "Rebuild Git timeline";
  showHistoryIndex(Number(range.value));
  updatePlaybackButtons();
  scheduleHistoryRefresh();
}

function scheduleHistoryRefresh() {
  window.clearTimeout(state.historyPollTimer);
  if (!["queued", "running"].includes(state.historyInfo?.job?.status)) return;
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
  result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Finding #${finding.id} · agent handoff</p><h2>${escapeHtml(finding.summary)}</h2><p class="panel-copy">${escapeHtml(value.workflow_note)}</p></div><span class="risk ${escapeHtml(value.risk)}">${escapeHtml(value.risk)} risk</span></div><div class="result-columns">${resultList("Recommended context", value.recommended_context)}${resultList("Relevant tests", value.relevant_tests)}${resultList("Protected paths", value.protected_paths)}${resultList("Verification", value.verification)}</div><h3>Copy this into Codex</h3><textarea id="agent-prompt" class="agent-prompt" readonly>${escapeHtml(state.lastAgentPrompt)}</textarea><div class="handoff-actions"><button id="copy-agent-prompt" class="button" type="button">Copy agent prompt</button><span class="muted">The structured version is available through CODEINTEL_FINDING_CONTEXT.</span></div>`;
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
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.view));
  });
  document.querySelectorAll("[data-switch]").forEach((button) => {
    button.addEventListener("click", () => switchView(button.dataset.switch));
  });
  byId("repository-select").addEventListener("change", async (event) => {
    state.repositoryId = Number(event.target.value);
    window.localStorage.setItem("codeintel.repository", state.repositoryId);
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
  byId("external-toggle").addEventListener("change", async () => {
    const snapshotId = state.graph.snapshot?.id || state.overview?.snapshot?.id;
    state.graph = await request(api("/api/graph", {
      snapshot_id: snapshotId,
      include_external: byId("external-toggle").checked,
    }));
    layoutGraph(false);
    drawGraph();
  });
  byId("finding-status-filter").addEventListener("change", renderFindings);
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
      toast(result.status === "started" ? "Git history import started." : "Git history import is already running.");
      state.historyInfo = await request(api("/api/history"));
      renderHistory();
    } catch (error) {
      toast(error.message, true);
      event.target.disabled = false;
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
    const metricMaximum = Math.max(...state.graph.nodes.map(nodeMetric), 1);
    const node = [...state.graph.nodes].reverse().find((item) => {
      const position = state.positions.get(String(item.id));
      return position && Math.hypot(position.x - x, position.y - y) <= nodeRadius(item, metricMaximum) + 3;
    });
    if (node) inspectNode(node);
  });
}

async function reloadFindings() {
  state.findings = await request(api("/api/findings"));
  renderFindings();
  renderOverview();
  drawGraph();
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
  element.style.borderColor = error ? "rgba(240,121,112,.5)" : "";
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

setupEvents();
load();
