import {
  api,
  architectureFor,
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  readThemeColors,
  request,
  state,
} from "/assets/dashboard-core.js";
import {
  consolidationMarkup,
  deadCodeList,
  detailList,
  formatDate,
  patternOpportunityList,
} from "/assets/dashboard-format.js";
import {
  effectiveGroup,
  groupColor,
  nodeColor,
  nodeMetric,
  nodeRadius,
  visibleGraphNodes,
} from "/assets/graph-model.js";
import { semanticProviderLabel } from "/assets/overview-view.js";

export function drawGraph() {
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
  drawRegions(context, scale);
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
  visibleNodes.forEach((node) => drawNode(
    context, node, metricMaximum, search, scale, theme,
  ));
  context.globalAlpha = 1;
  context.restore();
}

function drawRegions(context, scale) {
  if (!byId("architecture-regions-toggle").checked) return;
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
      context.fillText(line, region.x + 10 / scale, region.y + (17 + index * 14) / scale,
        Math.max(10, region.width - 20 / scale));
    });
    context.restore();
  });
  context.globalAlpha = 1;
}

function drawNode(context, node, maximum, search, scale, theme) {
  const position = state.positions.get(String(node.id));
  if (!position) return;
  const radius = nodeRadius(node, maximum);
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
    context.fillText(node.path.split("/").pop(), position.x + radius + 3 / scale,
      position.y + 3 / scale);
  }
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

export function renderLegend() {
  const overlay = byId("overlay-select").value;
  const theme = state.themeColors || readThemeColors();
  let items;
  if (overlay === "architecture") {
    items = state.groupRoots.filter((group) => !state.hiddenGroups.has(group.name)).slice(0, 12)
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

export function renderOverlayHelp() {
  const overlay = byId("overlay-select").value;
  let message = state.glossary?.overlays?.[overlay]
    || "Select an overlay to inspect the repository.";
  if (overlay === "agent" && !state.highlightedPaths.size) {
    message += " Plan a coding task or open a planned finding to populate this overlay.";
  }
  byId("overlay-help").textContent = message;
}

export async function inspectNode(node) {
  state.selectedNode = node;
  drawGraph();
  const panel = byId("inspector");
  const displayName = String(node.path).split("/").pop();
  panel.innerHTML = `<p class="eyebrow">Module inspector</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(node.path)}</code><p class="muted">Loading details…</p>`;
  if (String(node.id).startsWith("external:")) {
    panel.innerHTML = `<p class="eyebrow">External dependency</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(node.path)}</code><p class="muted">This node is referenced by repository code but is not analyzed inside this repository.</p>`;
    return;
  }
  try {
    const detail = await request(api("/api/file", {
      path: node.path,
      snapshot_id: state.graph.snapshot?.id,
    }));
    panel.innerHTML = inspectorMarkup(node, detail, displayName);
  } catch (error) {
    panel.innerHTML += `<p class="muted">${escapeHtml(error.message)}</p>`;
  }
}

function inspectorMarkup(node, detail, displayName) {
  const file = detail.file;
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
  const placement = architectureFor(inventory) || architectureFor(file) || {};
  const area = placement.area || state.groupParents.get(effectiveGroup(file)) || effectiveGroup(file);
  const subsystem = placement.subsystem || effectiveGroup(file);
  const coverage = node.line_coverage == null ? "Not imported"
    : `${(Number(node.line_coverage) * 100).toFixed(1)}%`;
  const evaluation = inventory.evaluation || {};
  const relationships = detail.relationships.slice(0, 14).map((item) => (
    `<button data-path="${escapeAttr(item.target_path || "")}">${escapeHtml(item.relationship_type)} → ${escapeHtml(item.target_path || item.target_external)}</button>`
  )).join("");
  const dependants = detail.dependants.slice(0, 14).map((item) => (
    `<button data-path="${escapeAttr(item.source_path || "")}">${escapeHtml(item.source_path || "")}</button>`
  )).join("");
  const responsibilities = (file.responsibilities || []).map(
    (item) => `<span class="tag">${escapeHtml(item)}</span>`,
  ).join("");
  return `<p class="eyebrow">${escapeHtml(humanize(area))} · ${escapeHtml(humanize(subsystem))}</p><h2>${escapeHtml(displayName)}</h2><code class="inspector-path">${escapeHtml(file.path)}</code><h3>Purpose</h3><p class="muted">${escapeHtml(purpose)}</p><p class="inspector-provenance">${escapeHtml(purposeSource)}</p>${factList(file, node, inventory, detail, coverage)}${semanticSection(semantic, semanticValue, detail)}<h3>Detected responsibilities</h3><div class="tag-list">${responsibilities || '<span class="muted">No structured responsibility detected</span>'}</div><h3>Deterministic pattern review</h3><div class="tag-list">${(evaluation.pattern_candidates || []).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || '<span class="muted">No detector-grounded pattern candidate yet</span>'}</div><h3>Public interfaces</h3><div class="tag-list">${(file.public_interfaces || []).slice(0, 18).map((item) => `<span class="tag">${escapeHtml(item)}</span>`).join("") || '<span class="muted">None detected</span>'}</div><h3>Uses</h3><div class="relation-list">${relationships || '<span class="muted">No outgoing relationship detected</span>'}</div><h3>Used by</h3><div class="relation-list">${dependants || '<span class="muted">No incoming relationship detected</span>'}</div><h3>Recent changes</h3><div class="relation-list">${detail.history.slice(0, 6).map((item) => `<span class="muted">${escapeHtml(item.commit_sha.slice(0, 8))} · ${escapeHtml(item.subject)}</span>`).join("") || '<span class="muted">No Git history loaded</span>'}</div>`;
}

function factList(file, node, inventory, detail, coverage) {
  const facts = [
    ["Language", file.language], ["Runtime", file.runtime || "—"],
    ["LOC", format.format(file.lines_of_code)], ["Complexity", file.complexity],
    ["Incoming links", format.format(node.fan_in || 0)],
    ["Outgoing links", format.format(node.fan_out || 0)], ["Line coverage", coverage],
    ["Indexed changes", format.format(node.change_count || 0)],
    ["First indexed", formatDate(inventory.first_changed_at)],
    ["Last worked", formatDate(inventory.last_commit_at)],
    ["Raw hash", String(file.raw_hash || "").slice(0, 10)],
    ["Structural hash", String(file.structural_hash || "").slice(0, 10)],
    ["Analysis state", file.analysis_status],
    ["Frame reason", humanize(file.metadata?.invalidation_reason || "not recorded")],
    ["Semantic state", humanize(detail.semantic_state?.status || "not started")],
  ];
  return `<dl>${facts.map(([label, value]) => `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`).join("")}</dl>`;
}

function semanticSection(semantic, value, detail) {
  if (!semantic) {
    return `<h3>AI understanding</h3><p class="muted">${escapeHtml(detail.semantic_state?.reason || "No current model-backed dossier.")}</p>`;
  }
  return `<h3>AI architecture role</h3><p class="muted">${escapeHtml(value.architecture_role || "No architecture role recorded")}</p>${value.change_summary ? `<h3>Meaning changed</h3><p class="muted">${escapeHtml(value.change_summary)}</p>` : ""}<h3>AI-understood responsibilities</h3>${detailList(value.responsibilities, "No semantic responsibilities recorded")}<h3>Similar or overlapping modules</h3>${detailList([...(value.similar_modules || []), ...(value.overlaps || [])], "No evidence-backed overlap recorded")}<h3>Pattern opportunities</h3>${patternOpportunityList(value.pattern_opportunities)}${consolidationMarkup(value.consolidation_assessment)}${value.placement_guidance ? `<h3>Where new work belongs</h3><p class="muted">${escapeHtml(value.placement_guidance)}</p>` : ""}<h3>Possible dead code</h3>${deadCodeList(value.dead_code_candidates)}<h3>Extension seams</h3>${detailList(value.extension_points, "No extension seam recorded")}<h3>Semantic risks</h3>${detailList(value.risks, "No semantic risk recorded")}`;
}

export function setupCanvasEvents() {
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
    const maximum = Math.max(...nodes.map(nodeMetric), 1);
    const node = [...nodes].reverse().find((item) => {
      const position = state.positions.get(String(item.id));
      return position && Math.hypot(position.x - x, position.y - y)
        <= nodeRadius(item, maximum) + 3;
    });
    if (node) inspectNode(node);
  });
}
