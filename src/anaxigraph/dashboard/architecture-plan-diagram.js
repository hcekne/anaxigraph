import { escapeHtml } from "/assets/dashboard-core.js";

export function architectureDiagram(graph, title, changes) {
  const nodes = graph?.nodes || [], columns = 1, width = 340;
  const rows = Math.max(1, Math.ceil(nodes.length / columns));
  const positions = new Map(nodes.map((node, index) => [node.key, { x: 25 + index % columns * 335, y: 25 + Math.floor(index / columns) * 115 }]));
  const links = (graph?.edges || []).map(edge => {
    const from = positions.get(edge.source), to = positions.get(edge.target);
    if (!from || !to) return "";
    return `<path d="M${from.x + 145},${from.y + 75} L${to.x + 145},${to.y}" marker-end="url(#plan-arrow-${title})"><title>${escapeHtml(edge.label)}</title></path>`;
  }).join("");
  const boxes = nodes.map(node => {
    const { x, y } = positions.get(node.key);
    const change = changes.find(item => item.key === node.key)?.status || "retained";
    return `<g class="plan-node ${change}" transform="translate(${x} ${y})"><title>${escapeHtml(node.responsibility)}</title><rect width="290" height="75" rx="12"/><text x="14" y="27">${escapeHtml(node.label.slice(0, 31))}</text><text class="plan-node-state" x="14" y="53">${escapeHtml(change)}</text></g>`;
  }).join("");
  return `<figure class="architecture-diagram"><figcaption>${escapeHtml(title === "current" ? "Current architecture" : "Proposed target")}</figcaption><div class="plan-graph-scroll"><svg role="img" aria-label="${title === "current" ? "Current architecture" : "Proposed architecture"}" viewBox="0 0 ${width} ${rows * 115 + 15}"><defs><marker id="plan-arrow-${title}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8"/></marker></defs><g class="plan-links">${links}</g>${boxes}</svg></div>${(graph?.unknowns || []).map(item => `<p class="muted">Unknown: ${escapeHtml(item)}</p>`).join("")}</figure>`;
}
