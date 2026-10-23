import { state } from "/assets/dashboard-core.js";

export function layoutSemanticGraph(nodes, canvas, resetView) {
  const width = canvas.clientWidth, height = canvas.clientHeight;
  if (!width || !height) return;
  state.positions = graphPositions(nodes, state.graph.edges || [], width, height);
  state.groupRegions = [];
  state.subgroupRegions = [];
  canvas.dataset.regionCount = "0";
  canvas.dataset.visibleNodeCount = String(nodes.length);
  canvas.dataset.labelOverflow = "0";
  canvas.dataset.layout = "semantic";
  if (resetView) state.transform = { x: 0, y: 0, scale: 1 };
}

export function graphPositions(nodes, edges, width, height) {
  const ids = new Set(nodes.map(node => String(node.id)));
  const ranks = relationshipRanks(ids, edges);
  const lanes = new Map();
  [...nodes].sort((a, b) => String(a.id).localeCompare(String(b.id))).forEach(node => {
    const rank = ranks.get(String(node.id)) || 0;
    if (!lanes.has(rank)) lanes.set(rank, []);
    lanes.get(rank).push(node);
  });
  const levels = [...lanes.keys()].sort((a, b) => a - b);
  const columns = Math.max(levels.length, 1);
  const horizontal = Math.max(80, (width - 80) / columns);
  const positions = new Map();
  levels.forEach((rank, column) => {
    const members = lanes.get(rank);
    const subdivisions = Math.max(1, Math.floor(horizontal / 180));
    const rows = Math.ceil(members.length / subdivisions);
    members.forEach((node, index) => {
      const row = index % rows;
      const subdivision = Math.floor(index / rows);
      positions.set(String(node.id), {
        x: 40 + horizontal * column + horizontal * (subdivision + 0.5) / subdivisions,
        y: 36 + (height - 72) * (row + 0.5) / Math.max(rows, 1),
        group: node.architecture_area || node.kind,
      });
    });
  });
  return positions;
}

function relationshipRanks(ids, edges) {
  const incoming = new Map([...ids].map(id => [id, 0]));
  const outgoing = new Map([...ids].map(id => [id, []]));
  edges.forEach(edge => {
    const from = String(edge.source), to = String(edge.target);
    if (from === to || !ids.has(from) || !ids.has(to)) return;
    incoming.set(to, incoming.get(to) + 1);
    outgoing.get(from).push(to);
  });
  const queue = [...ids].filter(id => incoming.get(id) === 0).sort();
  const ranks = new Map(queue.map(id => [id, 0]));
  for (let cursor = 0; cursor < queue.length; cursor += 1) {
    const id = queue[cursor];
    outgoing.get(id).forEach(to => {
      ranks.set(to, Math.min(4, Math.max(ranks.get(to) || 0, ranks.get(id) + 1)));
      incoming.set(to, incoming.get(to) - 1);
      if (!incoming.get(to)) queue.push(to);
    });
  }
  // Cycles remain visible in the graph and text relationships instead of disappearing.
  return ranks;
}
