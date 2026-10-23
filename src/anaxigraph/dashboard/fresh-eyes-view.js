import { api, byId, escapeAttr, escapeHtml, humanize, request, state, toast } from "/assets/dashboard-core.js";
import { architectureDiagram } from "/assets/architecture-plan-diagram.js";
import { switchView } from "/assets/navigation.js";

let current = null, generation = "", selectedScope = "", requestToken = 0, comparisonToken = 0;

export function setupFreshEyesView() {
  if (byId("view-fresh-eyes")) return;
  const section = document.createElement("section");
  section.id = "view-fresh-eyes"; section.className = "view";
  section.innerHTML = markup();
  byId("view-patterns").after(section);
  byId("fresh-eyes-open-workflow").addEventListener("click", () => switchView("workflows", false, "fresh-eyes"));
  byId("fresh-eyes-open-planning").addEventListener("click", () => switchView("workflows", false, "architecture"));
  section.addEventListener("click", event => { if (event.target.closest("[data-fresh-archive]")) void loadFreshEyes(true); });
  byId("fresh-eyes-refresh").addEventListener("click", () => void loadFreshEyes());
  byId("fresh-eyes-generation").addEventListener("change", event => { generation = event.target.value; void loadFreshEyes(); });
  byId("fresh-eyes-compare").addEventListener("change", () => void loadEarlierGeneration());
  byId("fresh-eyes-scope").addEventListener("change", event => { selectedScope = event.target.value; renderScope(); void loadFreshEyes(); });
  window.addEventListener("anaxigraph:contextready", () => {
    if (byId("view-fresh-eyes").classList.contains("active")) void loadFreshEyes();
  });
  window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
    if (detail.name === "fresh-eyes") void loadFreshEyes();
  });
}

export function resetFreshEyesView() {
  current = null; generation = ""; selectedScope = ""; requestToken += 1;
  comparisonToken += 1;
  if (byId("fresh-eyes-compare")) byId("fresh-eyes-compare").value = "";
  if (byId("fresh-eyes-compare-panel")) byId("fresh-eyes-compare-panel").innerHTML = "";
  if (byId("fresh-eyes-alternatives")) byId("fresh-eyes-alternatives").innerHTML = "";
  if (byId("view-fresh-eyes")?.classList.contains("active")) void loadFreshEyes();
}

function markup() {
  return `<article class="panel"><p class="eyebrow">Purpose → capabilities → functional subsystems</p>
    <h2>Explore three ways to deliver the same functionality</h2>
    <p>Fresh Eyes works from the functional brief without seeing source or the existing implementation. Alternatives remain available at each reviewed scope. Architecture Planning compares them with the actual system later.</p>
    <button id="fresh-eyes-open-workflow" class="secondary-button">Open Fresh Eyes workflow</button>
    <button id="fresh-eyes-open-planning" class="secondary-button">Compare with actual architecture in Planning</button></article>
    <article class="panel"><div class="panel-heading"><h2 id="fresh-eyes-title">Saved functional review</h2>
    <div class="fresh-eyes-controls"><label>Recorded generation<select id="fresh-eyes-generation"><option value="">Current review</option></select></label><label>Compare functional generation<select id="fresh-eyes-compare"><option value="">Off</option></select></label><button id="fresh-eyes-refresh" class="secondary-button">Refresh results</button></div></div>
    <p id="fresh-eyes-summary" role="status">Open this view to read saved alternatives.</p><p id="fresh-eyes-isolation" class="muted"></p><div id="fresh-eyes-snapshot"></div>
    <p id="fresh-eyes-purpose" class="entity-overview"></p>
    <label>Functional scope<select id="fresh-eyes-scope" class="functional-scope-select"></select></label>
    <div id="fresh-eyes-scope-detail"></div><details><summary>See the functional hierarchy</summary><div id="fresh-eyes-hierarchy"></div></details></article>
    <div id="fresh-eyes-alternatives" class="functional-alternatives"></div>
    <article id="fresh-eyes-comparison" class="panel"></article>
    <div id="fresh-eyes-compare-panel"></div>
    <article id="fresh-eyes-legacy" class="panel" hidden></article>`;
}

function contextKey() { return `${state.repositoryId}:${state.overview?.snapshot?.id}:${generation}`; }

async function loadFreshEyes(fullArchive = false) {
  if (!state.repositoryId || !state.overview) return;
  comparisonToken += 1;
  const token = ++requestToken, context = contextKey();
  byId("fresh-eyes-summary").textContent = "Reading saved functional scopes and alternatives…";
  try {
    const value = await request(api("/api/fresh-eyes", { generation, scope_id: selectedScope, details: fullArchive || !!selectedScope }));
    if (token !== requestToken || context !== contextKey()) return;
    current = value; render(value);
  } catch (error) {
    if (token === requestToken) { byId("fresh-eyes-summary").textContent = error.message; toast(error.message, true); }
  }
}

function render(value) {
  const brief = value.functional_brief || {};
  byId("fresh-eyes-title").textContent = `${humanize(value.state || "not started")} · functional alternatives`;
  byId("fresh-eyes-summary").textContent = reviewProgress(value, brief);
  byId("fresh-eyes-purpose").textContent = brief.purpose || "No functional brief has been saved yet.";
  renderProvenance(value, brief);
  renderGenerations(value.generations || []);
  renderHierarchy(functionalScopes());
  renderScope(); renderLegacy(value); void loadEarlierGeneration();
}

function reviewProgress(value, brief) {
  const counts = value.counts || {};
  const total = counts.total_scopes || brief.scopes?.length || 0;
  const next = value.next_action || (value.ready ? "Explore the retained alternatives or continue to Planning." : "Run the workflow to complete missing work.");
  return `${counts.completed_scopes || 0} / ${total} scopes complete · ${counts.retained_alternatives || 0} / ${counts.expected_alternatives || 0} alternatives saved. ${next}`;
}

function renderProvenance(value, brief) {
  byId("fresh-eyes-isolation").textContent = `Worker isolation: ${humanize(value.isolation?.status || "not recorded")}. Functional brief ${String(brief.revision || "not recorded").slice(0, 16)}.`;
  byId("fresh-eyes-snapshot").innerHTML = value.snapshot?.dirty ? `<p class="fresh-eyes-warning">Mapping provenance: dirty checkout · working-tree fingerprint ${escapeHtml(String(value.snapshot.working_tree_fingerprint || value.snapshot.content_fingerprint || "not recorded").slice(0, 12))}. The immutable functional brief revision identifies what Fresh Eyes received.</p>` : "";
}

function renderGenerations(records) {
  const generations = [...new Set(records.map(item => item.generation))];
  byId("fresh-eyes-generation").innerHTML = '<option value="">Current review</option>' + generations.map(number => `<option value="${number}">Generation ${number}</option>`).join("");
  byId("fresh-eyes-generation").value = generation;
  const compared = byId("fresh-eyes-compare").value;
  byId("fresh-eyes-compare").innerHTML = '<option value="">Off</option>' + generations.map(number => `<option value="${number}">Generation ${number}</option>`).join("");
  if (generations.map(String).includes(compared)) byId("fresh-eyes-compare").value = compared;
}

function renderHierarchy(scopes) {
  if (!scopes.some(item => item.id === selectedScope)) selectedScope = scopes[0]?.id || "";
  byId("fresh-eyes-scope").innerHTML = scopes.map(scope => `<option value="${escapeAttr(scope.id)}">${escapeHtml(`${humanize(scope.level)} · ${scope.purpose}`)}</option>`).join("");
  byId("fresh-eyes-scope").value = selectedScope;
  byId("fresh-eyes-hierarchy").innerHTML = architectureDiagram({ nodes: scopes.map(scope => ({ key: scope.id, label: scope.purpose, kind: scope.level, overview: scope.purpose })), edges: scopes.filter(scope => scope.parent_id).map(scope => ({ source: scope.parent_id, target: scope.id, label: "contains functionality" })) }, "functional-hierarchy", [], "Functional purpose and capabilities");
}

function functionalScopes() {
  const scopes = current?.functional_brief?.scopes || [];
  return scopes.length ? scopes : (current?.scope_reviews || []).map(item => item.scope || { id: item.scope_id, purpose: item.scope_id, level: "scope" });
}

function renderScope() {
  const scope = functionalScopes().find(item => item.id === selectedScope);
  const review = (current?.scope_reviews || []).find(item => item.scope_id === selectedScope) || {};
  byId("fresh-eyes-scope-detail").innerHTML = scope ? `<p>${escapeHtml(scope.purpose)}</p>${list("Inputs", scope.inputs)}${list("Outputs", scope.outputs)}${list("Required behavior and constraints", scope.constraints)}${scope.parent_id ? `<p class="muted">Parent functional scope: ${escapeHtml(scope.parent_id)}</p>` : ""}` : '<p class="muted">Reviewed scopes appear here when the functional brief is ready.</p>';
  const alternatives = review.alternatives || [];
  byId("fresh-eyes-alternatives").innerHTML = Array.from({ length: Math.max(3, alternatives.length) }, (_, index) => alternativeMarkup(alternatives[index], index)).join("");
  const comparison = review.comparison;
  byId("fresh-eyes-comparison").innerHTML = comparison
    ? `<h2>Trade-offs for this functionality</h2><p>${escapeHtml(comparison.summary || "")}</p>${diversityMarkup(comparison.diversity)}${assessmentMarkup(comparison.assessments, alternatives)}${list("Disagreements", comparison.disagreements)}${list("Composition conflicts", comparison.composition_conflicts)}<p class="muted">These are functional comparisons. No existing implementation is used as a reference design.</p>`
    : '<h2>Functional comparison pending</h2><p>Saved alternatives remain available while their comparison is unfinished.</p>';
}

function alternativeMarkup(item, index, lineage = "current") {
  const slot = String.fromCharCode(65 + index);
  if (!item) return `<article class="panel functional-alternative"><p class="eyebrow">Alternative ${slot}</p><h3>Not saved yet</h3><p>Successful alternatives are kept. Resume the workflow to complete missing work.</p></article>`;
  const design = item.design || item.proposal || {};
  const graph = alternativeGraph(design);
  return `<article class="panel functional-alternative" data-fresh-alternative="${escapeAttr(item.id || slot)}"><p class="eyebrow">Alternative ${escapeHtml(item.slot || slot)}</p>
    ${alternativeHeading(item, design, slot)}
    ${architectureDiagram(graph, `fresh-${lineage}-${selectedScope}-${item.id || slot}`, [], `Alternative ${slot} design`)}
    ${alternativeTradeoffs(item, design)}${operatingChoices(design)}
    <details><summary>Complete saved design and provenance</summary><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></details></article>`;
}

function alternativeHeading(item, design, slot) {
  const title = design.title || design.name || `Design ${slot}`;
  const model = item.provenance?.executor_model || item.provenance?.model || "Model not recorded";
  return `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(design.summary || "")}</p>
    <p class="muted">${escapeHtml(model)} · isolation ${escapeHtml(item.isolation?.status || "not recorded")}</p>`;
}

function alternativeTradeoffs(item, design) {
  return `${list("Pros", item.pros || design.pros || design.strengths)}${list("Cons", item.cons || design.cons || design.tradeoffs)}
    ${list("Assumptions", item.assumptions || design.assumptions)}${list("Unknowns", item.unknowns || design.unknowns)}`;
}

function operatingChoices(design) {
  const behavior = ["control_model", "state_ownership", "failure_isolation"].filter(key => design[key]).map(key => `<h4>${escapeHtml(humanize(key))}</h4><p>${escapeHtml(design[key])}</p>`).join("");
  return `<details><summary>Flows, boundaries and operating choices</summary>${behavior}${list("Information flows", design.information_flows)}${list("Boundary rules", design.boundary_rules)}${list("Operating model", design.operating_model)}${list("Extension strategy", design.extension_strategy)}</details>`;
}

async function loadEarlierGeneration() {
  const number = byId("fresh-eyes-compare").value, panel = byId("fresh-eyes-compare-panel");
  const token = ++comparisonToken, context = contextKey(), scope = selectedScope;
  if (!number) { panel.innerHTML = ""; return; }
  if (Number(number) === Number(generation || current?.review_generation)) {
    panel.innerHTML = '<article class="panel"><h2>Choose a different recorded generation</h2><p>Comparing a generation with itself does not establish agreement.</p></article>'; return;
  }
  panel.innerHTML = '<p role="status">Reading the earlier functional alternatives…</p>';
  try {
    const value = await request(api("/api/fresh-eyes", { generation: number, scope_id: scope, details: true }));
    if (token !== comparisonToken || context !== contextKey() || scope !== selectedScope) return;
    const review = (value.scope_reviews || []).find(item => item.scope_id === scope);
    panel.innerHTML = `<article class="panel"><h2>Generation ${escapeHtml(number)} · same functional scope</h2><p>Brief revision ${escapeHtml(value.functional_brief?.revision || "not recorded")}. Different requirements can make the designs incomparable.</p>
      ${review ? `<div class="functional-alternatives">${review.alternatives.map((item, index) => alternativeMarkup(item, index, number)).join("")}</div>` : '<p>This scope has no retained functional alternatives in this generation. Its original review remains available as a legacy record.</p>'}</article>`;
  } catch (error) { if (token === comparisonToken) panel.textContent = error.message; }
}

function alternativeGraph(design) {
  const components = design.nodes || design.components || [];
  return {
    nodes: components.map(proposedNode),
    edges: (design.edges || design.relationships || []).map(proposedEdge),
    unknowns: design.unknowns || [],
  };
}

function proposedNode(node, index) {
  return { ...node, key: node.id || node.key || node.name || `component-${index}`, label: node.label || node.name || node.title || `Component ${index + 1}`, overview: node.overview || node.responsibility || node.purpose || (node.responsibilities || []).join("; ") };
}

function proposedEdge(edge) {
  return { ...edge, source: edge.source || edge.from || edge.from_component, target: edge.target || edge.to || edge.to_component, label: edge.relationship || edge.label || edge.description || "interacts" };
}

function assessmentMarkup(values = [], alternatives) {
  return `<div class="functional-alternatives">${values.map(item => {
    const index = alternatives.findIndex(alternative => alternative.id === item.alternative_id);
    const name = index >= 0 ? `Alternative ${String.fromCharCode(65 + index)}` : item.alternative_id;
    return `<article><h3>${escapeHtml(name)}</h3>${["functional_fit", "change_isolation", "justified_complexity", "operating_constraints", "decomposition", "control_flow", "data_ownership", "failure_isolation"].map(key => `<h4>${escapeHtml(humanize(key))}</h4><p>${escapeHtml(item[key] || "Not assessed")}</p>`).join("")}${list("Strengths", item.strengths)}${list("Weaknesses", item.weaknesses)}</article>`;
  }).join("")}</div>`;
}

function list(title, items = []) {
  if (!Array.isArray(items) || !items.length) return "";
  return `<h4>${escapeHtml(title)}</h4><ul>${items.map(item => `<li>${escapeHtml(typeof item === "string" ? item : item.summary || item.assessment || item.description || JSON.stringify(item))}</li>`).join("")}</ul>`;
}

function renderLegacy(value) {
  const legacy = byId("fresh-eyes-legacy");
  legacy.hidden = value.protocol_version === "fresh-eyes-recipe-v2" || !!value.functional_brief;
  legacy.innerHTML = legacy.hidden ? "" : `<details><summary>Saved legacy review record</summary><p>This earlier review used the previous workflow. It remains readable for provenance; new Fresh Eyes runs retain independent functional alternatives.</p><button class="secondary-button" data-fresh-archive>Read complete saved archive</button><pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre></details>`;
}

function diversityMarkup(value) {
  if (!value) return '<p class="muted">Design diversity has not been assessed. Three saved alternatives do not by themselves establish three different architectures.</p>';
  return `<section class="fresh-design-diversity"><h3>Design diversity: ${escapeHtml(humanize(value.status || "uncertain"))}</h3><p class="muted">Novelty is unverified. Retained alternatives can converge; saved slots are not evidence of different designs.</p>${list("Material differences", value.differences)}${list("Limitations", value.limitations)}${list("Unexplored directions", value.unexplored_directions)}</section>`;
}
