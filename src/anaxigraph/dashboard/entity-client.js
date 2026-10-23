import { api, byId, request, state } from "/assets/dashboard-core.js";

const detailCache = new Map();

export function entityContext(extra = {}) {
  return {
    snapshot_id: state.entityGraphKind === "observed" ? state.entitySnapshotId || state.overview?.snapshot?.id : undefined,
    graph_kind: state.entityGraphKind || "observed",
    graph_subject: state.entitySubjectId || "observed",
    map_layer: state.mapLayer,
    ...extra,
  };
}

export function entityContextKey() {
  return JSON.stringify([state.repositoryId, entityContext(), state.repositoryLoadToken]);
}

export function normalizeEntity(node) {
  const properties = node.properties || {};
  return { ...properties, ...node.metrics, ...node, ...entityNames(node, properties),
    ...entityPlacement(node, properties), canonical: node };
}

function entityNames(node, properties) {
  const overview = node.overview || node.summary || "Understanding not yet recorded.";
  return { path: node.path ?? properties.path ?? "", name: node.label || node.name || node.id,
    summary: overview, overview, kind: node.kind || "module",
    artifact_id: node.artifact_id ?? properties.artifact_id ?? null };
}

function entityPlacement(node, properties) {
  return { architecture_area: node.placement?.area || node.architecture_area || properties.area || properties.architecture_area,
    architecture_subsystem: node.placement?.subsystem || node.architecture_subsystem || properties.subsystem };
}

export function normalizeGraph(value) {
  const nodes = (value.nodes || []).map(normalizeEntity);
  return { ...value, nodes, edges: value.edges || [],
    snapshot: value.context?.snapshot || { id: value.context?.snapshot_id },
    counts: graphCounts(value, nodes), next_cursor: value.next_offset };
}

function graphCounts(value, nodes) {
  const edges = value.edges?.length ?? 0;
  return { page_internal_nodes: value.returned_nodes ?? nodes.length,
    matching_nodes: matchingTotal(value, "total_nodes", nodes.length),
    page_edges: value.returned_edges ?? edges,
    matching_edges: matchingTotal(value, "total_edges", edges),
    known_nodes: value.known_nodes ?? value.total_nodes ?? nodes.length,
    known_edges: value.known_edges ?? value.total_edges ?? edges };
}

function matchingTotal(value, key, fallback) {
  if (value.counts_are_complete === false) return null;
  return Object.hasOwn(value, key) ? value[key] : fallback;
}

export async function entityPage(params = {}) {
  const url = api("/api/graph/entities", entityContext(params));
  return request(params.kind === "" ? `${url}${url.includes("?") ? "&" : "?"}kind=` : url);
}

export async function entityNeighborhood(entityId, params = {}) {
  const value = await request(api("/api/graph/neighborhood", entityContext({
    entity_id: entityId, direction: "both", depth: 1, limit: 100, ...params,
  })));
  return normalizeGraph(value);
}

export async function entityDetail(entityId, options = {}) {
  const semanticRevision = JSON.stringify([state.graph?.context?.semantic_revision, state.moduleEnvelope?.context?.semantic_revision]);
  const key = `${entityContextKey()}:${semanticRevision}:${entityId}:${JSON.stringify(options)}`;
  if (detailCache.has(key)) return detailCache.get(key);
  const value = await request(api("/api/graph/entity", entityContext({ entity_id: entityId, ...options })));
  if (detailCache.size >= 100) detailCache.delete(detailCache.keys().next().value);
  detailCache.set(key, value);
  return value;
}

export function clearEntityState() {
  detailCache.clear();
  state.entitySelectionToken = (state.entitySelectionToken || 0) + 1;
  state.entitySnapshotId = null;
  state.entityGraphKind = "observed";
  state.entitySubjectId = "observed";
  state.entitySubjectRevision = null;
  state.moduleEnvelope = null;
  state.entityTrail = [];
  state.graphFocusId = null;
  state.graphLoading = false;
}

export function moduleQuery() {
  return {
    kind: "module", sort: state.moduleSort.key === "summary" ? "overview" : state.moduleSort.key,
    direction: state.moduleSort.direction,
    offset: (state.modulePage - 1) * Number(byId("module-page-size").value),
    limit: Number(byId("module-page-size").value),
    q: byId("module-search").value.trim(),
    area: byId("module-area-filter").value,
    subsystem: byId("module-subsystem-filter").value,
    language: byId("module-language-filter").value,
    include_reference: byId("module-include-reference").checked,
  };
}
