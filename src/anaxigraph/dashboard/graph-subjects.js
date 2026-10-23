import { api, byId, escapeAttr, escapeHtml, humanize, request, state, toast } from "/assets/dashboard-core.js";
import { loadGraphRegion } from "/assets/graph-regions.js";
import { buildGroupIndex } from "/assets/graph-model.js";
import { selectedHierarchy } from "/assets/overview-view.js";

const OBSERVED = { id: "observed", graph_kind: "observed", label: "Observed implementation", default_kind: "capability", entity_kinds: ["capability", "module", "function", "interface", "contract", "unresolved"] };
let subjects = [OBSERVED], token = 0;

export function setupGraphSubjects() {
  byId("graph-subject-select").addEventListener("change", () => {
    selectSubject(subjects.find(item => item.id === byId("graph-subject-select").value) || OBSERVED);
    void loadGraphRegion("").catch(error => toast(error.message, true));
  });
  window.addEventListener("anaxigraph:viewchange", ({ detail }) => {
    subjectControls(detail.name === "graph");
    if (detail.name === "graph") void loadSubjects();
  });
  window.addEventListener("anaxigraph:contextready", () => {
    if (byId("view-graph").classList.contains("active")) void loadSubjects();
  });
}

function context() { return `${state.repositoryId}:${state.overview?.snapshot?.id}:${state.repositoryLoadToken}`; }

async function loadSubjects() {
  if (!state.overview) return;
  const identity = context(), current = ++token;
  try {
    const value = await request(api("/api/graph/subjects", { snapshot_id: state.overview.snapshot?.id }));
    if (current !== token || identity !== context()) return;
    subjects = value.subjects || [OBSERVED];
    if (!subjects.some(item => item.id === "observed")) subjects.unshift(OBSERVED);
    const select = byId("graph-subject-select");
    select.innerHTML = subjects.map(item => `<option value="${escapeAttr(item.id)}">${escapeHtml(item.label)}</option>`).join("");
    select.value = state.entitySubjectId || "observed";
    if (!select.value || (state.entityGraphKind === "observed" && !byId("graph-kind-select").querySelector('option[value="module"]'))) { selectSubject(OBSERVED); void loadGraphRegion(""); }
    subjectControls(byId("view-graph").classList.contains("active"));
  } catch (error) { if (current === token) byId("graph-subject-note").textContent = `Saved graph subjects could not be loaded: ${error.message}`; }
}

function selectSubject(subject) {
  state.entityGraphKind = subject.graph_kind;
  state.entitySubjectId = subject.id;
  state.entitySubjectRevision = subject.revision || null;
  state.entitySnapshotId = null;
  state.entitySelectionToken += 1;
  state.graphRequestToken += 1;
  state.graphLoaded = true;
  state.graphFocusId = null;
  state.selectedNode = null;
  state.entityTrail = [];
  const kinds = subject.entity_kinds || (subject.graph_kind === "observed" ? OBSERVED.entity_kinds : ["capability", "component", "contract"]);
  byId("graph-kind-select").innerHTML = '<option value="">All entity types</option>' + kinds.map(kind => `<option value="${escapeAttr(kind)}">${escapeHtml(humanize(kind))}</option>`).join("");
  byId("graph-kind-select").value = subject.default_kind || "";
  byId("graph-subject-select").value = subject.id;
  byId("graph-search").value = "";
  byId("graph-relation-select").value = "";
  const evidence = subject.graph_kind === "observed" ? [["extracted", "Read from code"], ["inferred", "Inferred"], ["unresolved", "Unresolved"]] : [[subject.graph_kind === "functional_brief" ? "functional" : "proposed", subject.graph_kind === "functional_brief" ? "Functional requirement" : "Proposed design"]];
  byId("graph-evidence-select").innerHTML = '<option value="">All evidence</option>' + evidence.map(([key, label]) => `<option value="${key}">${label}</option>`).join("");
  byId("inspector").textContent = "Select an entity from this graph subject.";
  buildGroupIndex(subject.graph_kind === "observed" ? selectedHierarchy() : []);
  subjectControls(true);
}

export function useObservedSubject() {
  if (state.entityGraphKind === "observed") return false;
  selectSubject(OBSERVED);
  state.graphLoaded = false;
  state.moduleEnvelope = null;
  state.moduleDetails.clear();
  byId("module-subject-note").textContent = "The module inventory shows observed source. Saved alternatives remain available in the Graph subject selector.";
  subjectControls(false);
  return true;
}

function subjectControls(active) {
  const proposed = state.entityGraphKind !== "observed";
  buildGroupIndex(active && proposed ? [] : selectedHierarchy());
  byId("map-layer-select").disabled = active && proposed;
  for (const id of ["overlay-select", "size-select", "external-toggle", "architecture-regions-toggle", "graph-area-picker"]) byId(id).closest("label, details").hidden = proposed;
  byId("graph-layout-select").disabled = proposed;
  if (proposed) byId("graph-layout-select").value = "semantic";
  byId("graph-history-play-button").disabled = proposed || state.snapshots.length < 2;
  byId("graph-subject-note").textContent = proposed
    ? `Saved ${humanize(state.entityGraphKind).toLowerCase()} · revision ${String(state.entitySubjectRevision || "recorded with subject").slice(0, 20)}. Explore its functionality, proposed relationships and assumptions. Grouping and source metrics apply to observed implementation.`
    : "Observed source graph. Detail and grouping are independent of the graph subject.";
}
