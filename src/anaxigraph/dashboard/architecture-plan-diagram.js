import { escapeAttr, escapeHtml, hash } from "/assets/dashboard-core.js";
import { graphPositions } from "/assets/semantic-graph-layout.js";

export function architectureDiagram(graph, title, changes = [], caption = "") {
  const all = graph?.nodes || [];
  const nodes = all.slice(0, 80).map(node => ({ ...node, id: node.id || node.key }));
  const edges = graph?.edges || [];
  const width = 640, height = Math.max(200, Math.ceil(nodes.length / 3) * 120);
  const positions = graphPositions(nodes, edges, width, height);
  const name = caption || (title === "current" ? "Current architecture" : "Proposed target");
  const marker = `graph-arrow-${hash(title + JSON.stringify(nodes.map(node => node.id)))}`;
  return `<figure class="architecture-diagram"><figcaption>${escapeHtml(name)}</figcaption>
    <div class="plan-graph-scroll"><svg role="img" aria-label="${escapeAttr(name)}" viewBox="0 0 ${width} ${height}">
    <defs><marker id="${marker}" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto"><path d="M0 0L8 4L0 8"/></marker></defs>
    <g class="plan-links">${edgeMarkup(edges, positions, marker)}</g>${nodes.map(node => nodeMarkup(node, positions.get(String(node.id)), changes, title === "current")).join("")}</svg></div>
    ${all.length > nodes.length ? `<p class="muted">Diagram shows ${nodes.length} of ${all.length} entities. The complete saved entity descriptions follow.</p>` : ""}
    <details class="proposed-entity-list"><summary>Entities, responsibilities and contracts</summary>${all.map(node => `<details><summary>${escapeHtml(node.label || node.name || node.id || node.key)}</summary><p>${escapeHtml(node.overview || node.responsibility || node.summary || "")}</p>${node.contracts?.length ? `<pre>${escapeHtml(JSON.stringify(node.contracts, null, 2))}</pre>` : ""}</details>`).join("")}</details>
    ${relationshipDetails(edges, all)}
    ${(graph?.unknowns || []).map(item => `<p class="muted">Unknown: ${escapeHtml(item)}</p>`).join("")}</figure>`;
}

function edgeMarkup(edges, positions, marker) {
  return edges.map(edge => {
    const source = positions.get(String(edge.source)), target = positions.get(String(edge.target));
    if (!source || !target) return "";
    return `<path d="M${source.x},${source.y} L${target.x},${target.y}" marker-end="url(#${marker})"><title>${escapeHtml(edge.relationship_type || edge.label || "related")}</title></path>`;
  }).join("");
}

function nodeMarkup(node, position, changes, observed) {
  if (!position) return "";
  const change = changes.find(item => item.key === (node.key || node.id))?.status || (observed ? "observed" : "proposed");
  return `<g class="plan-node ${escapeAttr(change)}" transform="translate(${position.x - 75} ${position.y - 38})">
    <title>${escapeHtml(node.overview || node.responsibility || node.label || "")}</title><rect width="150" height="76" rx="10"/>
    <foreignObject x="8" y="8" width="134" height="48"><div xmlns="http://www.w3.org/1999/xhtml" class="semantic-diagram-label">${escapeHtml(node.label || node.name || node.id)}</div></foreignObject>
    <text class="plan-node-state" x="8" y="64">${escapeHtml(node.kind || change)}</text></g>`;
}

function relationshipDetails(edges, nodes) {
  if (!edges.length) return "";
  const labels = new Map(nodes.map(node => [String(node.id || node.key), node.label || node.name || node.id || node.key]));
  return `<details class="proposed-relationships"><summary>Directed relationships</summary><ul>${edges.map(edge => `<li>${escapeHtml(labels.get(String(edge.source)) || edge.source)} → ${escapeHtml(edge.relationship_type || edge.label || "interacts with")} → ${escapeHtml(labels.get(String(edge.target)) || edge.target)}${edge.rationale ? `<p>${escapeHtml(edge.rationale)}</p>` : ""}</li>`).join("")}</ul></details>`;
}
