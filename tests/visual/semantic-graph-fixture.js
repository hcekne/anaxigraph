export function semanticFixture() {
  const make = (id, kind, label, overview) => ({ id, kind, label, path: kind === "module" ? "src/orders.py" : "", overview,
    metrics: { lines_of_code: kind === "module" ? 42 : null, function_count: kind === "module" ? 1 : null, fan_in: 1, fan_out: 1 },
    placement: { area: "orders", subsystem: "processing" }, readiness: "current", provenance: { method: "extracted" } });
  const nodes = [
    make("module:src/orders.py", "module", "Order module", "Accepts orders through a stable contract."),
    make("function:src/orders.py#submit", "function", "submit", "Accepts one order and coordinates persistence."),
    make("interface:src/orders.py#gateway", "interface", "Order gateway", "Provides the stable order submission interface."),
    make("contract:orders#retry", "contract", "Order retry contract", "Retries preserve one accepted order."),
    make("module:tests/test_orders.py", "module", "Order retry tests", "Checks caller-visible retry behavior."),
  ];
  const edges = nodes.slice(1).map((node, index) => ({ id: `edge-${index}`, source: nodes[index].id, target: node.id,
    relationship_type: ["defines", "implements", "requires_contract", "tested_by"][index],
    confidence: 1, resolution: "resolved_internal", evidence: [{ observation: "fixture relationship" }], provenance: { method: "extracted" } }));
  const context = { repository_id: 1, snapshot_id: 1, graph_kind: "observed", revision: "fixture-revision" };
  const graph = { context, nodes, edges, total_nodes: 5, returned_nodes: 5, total_edges: 4, returned_edges: 4, next_offset: null };
  return { nodes, edges, graph, detail(id) {
    const index = nodes.findIndex(node => node.id === id), node = nodes[index];
    return { context, node: { ...node, detail: `Saved paragraph for ${node.label}. Caller obligations remain available without source reads.` },
      functions: index === 0 ? [nodes[1]] : [], interfaces: index <= 1 ? [nodes[2]] : [], contracts: index <= 2 ? [nodes[3]] : [],
      connections: { incoming: edges.filter(edge => edge.target === id), outgoing: edges.filter(edge => edge.source === id), tests: index === 3 ? [nodes[4]] : [] }, counts: {} };
  } };
}

export async function installSemanticFixture(page, fixture = semanticFixture()) {
  await page.route("**/api/graph/entities?*", route => {
    const kind = new URL(route.request().url()).searchParams.get("kind");
    const nodes = fixture.nodes.filter(node => node.kind === kind);
    return route.fulfill({ json: { ...fixture.graph, nodes, edges: [], total_nodes: nodes.length, returned_nodes: nodes.length, facets: { areas: ["orders"], subsystems: ["processing"], languages: ["python"] } } });
  });
  await page.route("**/api/graph/entity?*", route => route.fulfill({ json: fixture.detail(new URL(route.request().url()).searchParams.get("entity_id")) }));
  await page.route("**/api/graph/neighborhood?*", route => route.fulfill({ json: fixture.graph }));
  return fixture;
}
