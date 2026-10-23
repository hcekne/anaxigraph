export function freshReview(scopeId = "product", full = true) {
  const scopes = [{ id: "product", parent_id: "", level: "product", purpose: "Keep shared information usable", inputs: ["User information"], outputs: ["Useful answers"], constraints: ["Preserve access rules"] },
    { id: "capture", parent_id: "product", level: "capability", purpose: "Capture incoming information", inputs: ["New information"], outputs: ["Queryable records"], constraints: [] },
    { id: "capture-unit", parent_id: "capture", level: "subsystem", purpose: "Normalize incoming records", inputs: [], outputs: [], constraints: [] }];
  const alternatives = scope => ["a", "b", "c"].map(slot => ({ id: `${scope.id}:${slot}`, scope_id: scope.id,
    design: { summary: `${scope.purpose} using design ${slot}`, components: full || scope.id === "product" ? [{ key: `boundary-${slot}`, name: `${scope.id} boundary ${slot}`, responsibility: "Own one clear responsibility", contracts: ["Preserve required behavior"] }] : [], relationships: [], information_flows: ["Accept and normalize information"], boundary_rules: ["Keep state private"], operating_model: [], extension_strategy: [], assumptions: [], unknowns: [] },
    pros: [`Benefit ${slot}`], cons: [`Cost ${slot}`], isolation: { status: "unverified" } }));
  return { protocol_version: "fresh-eyes-recipe-v2", state: "current", ready: true,
    functional_brief: { revision: "brief-123", purpose: scopes[0].purpose, scopes }, selected_scope_id: scopeId,
    scope_reviews: scopes.map(scope => ({ scope_id: scope.id, scope, state: "current", alternatives: alternatives(scope), comparison: { summary: "Several useful designs remain", assessments: [], disagreements: ["Different state choices"], composition_conflicts: ["Check parent constraints before combining"] } })),
    counts: { total_scopes: 3, completed_scopes: 3, expected_alternatives: 9, retained_alternatives: 9 }, isolation: { status: "unverified" } };
}
