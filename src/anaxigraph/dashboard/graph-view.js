import {
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  readThemeColors,
  state,
} from "/assets/dashboard-core.js";
import {
  groupColor,
  groupLabel,
  layoutGraph,
  nodeColor,
  nodeMetric,
  nodeRadius,
  visibleGraphNodes,
} from "/assets/graph-model.js";
import { entityContextKey, entityDetail } from "/assets/entity-client.js";
import { entityButton, entityInspector } from "/assets/entity-inspector.js";

let textRevision = "";

export function drawGraph() {
  const canvas = byId("graph-canvas");
  if (!canvas?.clientWidth || !canvas.clientHeight) return;
  const nodes = visibleGraphNodes();
  if (nodes.some(node => !state.positions.has(String(node.id)))) layoutGraph(false);
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.floor(canvas.clientWidth * ratio);
  canvas.height = Math.floor(canvas.clientHeight * ratio);
  const context = canvas.getContext("2d");
  if (!context) return;
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
  const { x, y, scale } = state.transform;
  const theme = state.themeColors || readThemeColors();
  context.save();
  context.translate(x, y);
  context.scale(scale, scale);
  drawRegions(context, scale);
  drawEdges(context, nodes, scale, theme);
  const maximum = Math.max(...nodes.map(nodeMetric), 1);
  nodes.forEach(node => drawNode(context, node, maximum, "", scale, theme));
  context.globalAlpha = 1;
  context.restore();
  canvas.dataset.renderState = state.graphLoading ? "loading" : nodes.length ? "ready" : "empty";
  if (!nodes.length) {
    context.fillStyle = theme.label;
    context.textAlign = "center";
    context.fillText("No entities match this graph scope.", canvas.clientWidth / 2, canvas.clientHeight / 2);
  }
  const revision = `${state.repositoryId}:${state.graphRequestToken}:${nodes.length}`;
  if (revision !== textRevision) { textRevision = revision; renderGraphText(nodes); }
}

function drawEdges(context, nodes, scale, theme) {
  const ids = new Set(nodes.map(node => String(node.id)));
  const relation = byId("graph-relation-select")?.value;
  (state.graph.edges || []).forEach(edge => {
    if (relation && edge.relationship_type !== relation) return;
    const source = state.positions.get(String(edge.source));
    const target = state.positions.get(String(edge.target));
    if (!source || !target || !ids.has(String(edge.source)) || !ids.has(String(edge.target))) return;
    context.strokeStyle = theme.edge;
    context.fillStyle = theme.edge;
    context.lineWidth = 1.1 / scale;
    context.setLineDash(edge.resolution === "unresolved" || edge.provenance?.kind === "inferred" ? [5 / scale, 4 / scale] : []);
    context.beginPath(); context.moveTo(source.x, source.y); context.lineTo(target.x, target.y); context.stroke();
    const angle = Math.atan2(target.y - source.y, target.x - source.x);
    const x = target.x - Math.cos(angle) * 15, y = target.y - Math.sin(angle) * 15;
    context.beginPath(); context.moveTo(x, y);
    context.lineTo(x - Math.cos(angle - 0.5) * 8 / scale, y - Math.sin(angle - 0.5) * 8 / scale);
    context.lineTo(x - Math.cos(angle + 0.5) * 8 / scale, y - Math.sin(angle + 0.5) * 8 / scale);
    context.closePath(); context.fill();
  });
  context.setLineDash([]);
}

function renderGraphText(nodes) {
  const list = byId("graph-entity-list"), relationships = byId("graph-relationship-list");
  if (!list || !relationships) return;
  list.innerHTML = nodes.map(node => entityButton(node, `${humanize(node.kind)} · ${node.label || node.name}`)).join("");
  const lookup = new Map(nodes.map(node => [String(node.id), node]));
  relationships.innerHTML = (state.graph.edges || []).slice(0, 200).map(edge => graphRelationshipMarkup(edge, lookup)).join("") || '<p class="muted">No connections in this bounded scope. Unresolved or unloaded connections may exist.</p>';
}

function graphRelationshipMarkup(edge, lookup) {
  const from = relationshipLabel(lookup.get(String(edge.source)), edge.source);
  const to = relationshipLabel(lookup.get(String(edge.target)), edge.target);
  return `<details class="graph-edge-row"><summary>${escapeHtml(from)} → ${escapeHtml(humanize(edge.relationship_type || "related"))} → ${escapeHtml(to)}</summary>
    <p>${entityButton(edge.source, from)} → ${entityButton(edge.target, to)}</p>
    <p>${escapeHtml(edge.resolution || "Resolution not recorded")} · confidence ${edge.confidence == null ? "unknown" : escapeHtml(edge.confidence)}</p>
    <pre>${escapeHtml(JSON.stringify(edge.evidence || edge.provenance || {}, null, 2))}</pre></details>`;
}

function relationshipLabel(node, fallback) { return node?.label || node?.name || fallback; }

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
  });
  state.subgroupRegions.forEach((region) => {
    context.globalAlpha = 0.14;
    context.strokeStyle = groupColor(region.group);
    context.lineWidth = 0.8 / scale;
    roundedRectangle(context, region.x, region.y, region.width, region.height, 7 / scale);
    context.stroke();
    if (!region.labelled) return;
    context.globalAlpha = 0.68;
    context.fillStyle = groupColor(region.group);
    context.font = `${9 / scale}px ui-sans-serif, system-ui, sans-serif`;
    context.fillText(
      groupLabel(region.group), region.x + 6 / scale, region.y + 12 / scale,
      Math.max(10, region.width - 12 / scale),
    );
  });
  state.groupRegions.forEach((region) => {
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
  const radius = Math.max(7, nodeRadius(node, maximum));
  context.globalAlpha = 1;
  context.fillStyle = nodeColor(node);
  drawEntityShape(context, node.kind, position, radius);
  context.fill();
  context.strokeStyle = theme.nodeStroke;
  context.lineWidth = 1.25 / scale;
  context.stroke();
  if (String(state.selectedNode?.id) === String(node.id)) {
    context.strokeStyle = theme.selected;
    context.lineWidth = 3 / scale;
    context.stroke();
  }
  if (state.graph.nodes.length <= 70 || String(state.selectedNode?.id) === String(node.id) || scale > 1.5) {
    context.fillStyle = theme.label;
    context.font = `${11 / scale}px ui-sans-serif, system-ui, sans-serif`;
    const name = node.label || node.name || node.path?.split("/").pop() || node.id;
    context.fillText(name, position.x + radius + 4 / scale, position.y + 4 / scale, 160 / scale);
  }
}

function drawEntityShape(context, kind, position, radius) {
  const { x, y } = position;
  context.beginPath();
  if (["capability", "module", "area"].includes(kind)) {
    roundedRectangle(context, x - radius, y - radius * 0.7, radius * 2, radius * 1.4, 4);
  } else if (["interface", "contract"].includes(kind)) {
    context.moveTo(x, y - radius); context.lineTo(x + radius, y);
    context.lineTo(x, y + radius); context.lineTo(x - radius, y); context.closePath();
  } else context.arc(x, y, radius, 0, Math.PI * 2);
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
  if (state.entityGraphKind !== "observed") {
    items = [...new Set(state.graph.nodes.map(node => node.kind))].map(kind => [humanize(kind), groupColor(kind)]);
  } else if (overlay === "architecture") {
    items = state.groupRoots.filter((group) => !state.hiddenGroups.has(group.name)).slice(0, 12)
      .map((group) => [groupLabel(group.name), groupColor(group.name)]);
  } else if (overlay === "agent") {
    items = [["Useful for this task", theme.cool], ["Needs extra care", theme.warm]];
  } else if (overlay === "coverage" && visibleGraphNodes().every((node) => node.line_coverage == null)) {
    items = [["No imported coverage", theme.missing]];
  } else if (overlay === "drift") {
    items = [["Area agrees / no project rule", theme.drift], ["Project rule and best guess disagree", theme.hot]];
  } else if (overlay === "dead-code") {
    items = [["No unused-code sign", theme.idle], ["May be unused; inspect before deleting", theme.warm]];
  } else {
    items = [["Lower measured amount", theme.low], ["Higher measured amount", overlay === "change" ? theme.warm : theme.hot]];
  }
  byId("graph-legend").innerHTML = items.map(([label, color]) => (
    `<span class="legend-item"><i class="legend-dot" style="background:${color}"></i>${escapeHtml(label)}</span>`
  )).join("");
}

export function renderOverlayHelp() {
  const overlay = byId("overlay-select").value;
  let message = state.glossary?.overlays?.[overlay]
    || "Choose a color view to inspect the repository.";
  if (overlay === "architecture" && byId("graph-layout-select").value !== "footprint") {
    message = "Color shows responsibility areas; directed connections determine the behavior-path layout. Read connection types and evidence in the keyboard view. Choose area footprint to compare composition.";
  }
  if (state.entityGraphKind !== "observed") message = "Read the saved functional design and its proposed connections. Open entity details for responsibilities, contracts and recorded assumptions.";
  if (overlay === "agent" && !state.highlightedPaths.size && state.entityGraphKind === "observed") {
    message += " Describe a coding task or open a finding selected for work to color the relevant files.";
  }
  byId("overlay-help").textContent = message;
}

export async function inspectNode(node) {
  const selection = ++state.entitySelectionToken;
  const context = entityContextKey();
  state.selectedNode = node;
  drawGraph();
  const panel = byId("inspector");
  panel.innerHTML = `<p class="eyebrow">${escapeHtml(node.kind || "Entity")}</p><h2>${escapeHtml(node.label || node.name || node.path)}</h2><p role="status">Reading saved understanding…</p>`;
  try {
    const value = await entityDetail(node.id);
    if (selection !== state.entitySelectionToken || context !== entityContextKey()) return;
    panel.innerHTML = entityInspector(value);
  } catch (error) {
    if (selection === state.entitySelectionToken && context === entityContextKey()) {
      panel.innerHTML += `<p class="muted">${escapeHtml(error.message)}</p>`;
    }
  }
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
