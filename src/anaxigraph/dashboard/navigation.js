import { layoutGraph } from "/assets/graph-model.js";
import { drawGraph } from "/assets/graph-view.js";

const VIEW_JOURNEY = {
  overview: "understand",
  workflows: "workflows",
  modules: "understand",
  graph: "understand",
  agents: "guide",
  architecture: "improve",
  patterns: "improve",
  "fresh-eyes": "improve",
  history: "changes",
  settings: "settings",
};

const JOURNEY_VIEWS = {
  understand: [["overview", "Charter & overview"], ["modules", "Files"], ["graph", "Graph"]],
  improve: [["architecture", "Findings"], ["patterns", "Patterns"], ["fresh-eyes", "Fresh eyes"]],
};

const PRIMARY_JOURNEYS = [
  ["workflows", "workflows", "Workflows"],
  ["understand", "overview", "Understand"],
  ["guide", "agents", "Guide"],
  ["improve", "architecture", "Improve"],
  ["changes", "history", "Changes"],
  ["settings", "settings", "Settings"],
];

export function renderNavigation() {
  document.getElementById("primary-navigation").innerHTML = PRIMARY_JOURNEYS.map(
    ([journey, view, label], index) => (
      `<button class="tab${index === 0 ? " active" : ""}" data-journey="${journey}" data-view="${view}">${label}</button>`
    ),
  ).join("");
  restoreView();
  window.addEventListener("hashchange", restoreView);
}

function restoreView() {
  const name = window.location.hash.slice(1).split("/")[0];
  switchView(Object.hasOwn(VIEW_JOURNEY, name) ? name : "workflows");
}

export function switchView(name, preserveGraphCamera = false, flow = null) {
  if (!Object.hasOwn(VIEW_JOURNEY, name)) return;
  const previous = window.location.hash.slice(1).split("/");
  const selectedFlow = flow || (previous[0] === "workflows" && previous[1]) || "mapping";
  const route = name === "workflows" ? `workflows/${selectedFlow}` : name;
  window.history.replaceState({}, "", `${window.location.pathname}${window.location.search}#${route}`);
  const journey = VIEW_JOURNEY[name] || name;
  document.querySelectorAll(".tab").forEach((item) => {
    item.classList.toggle("active", item.dataset.journey === journey);
  });
  document.querySelectorAll(".view").forEach((item) => {
    item.classList.toggle("active", item.id === `view-${name}`);
  });
  if (name === "graph") {
    window.requestAnimationFrame(() => window.requestAnimationFrame(() => {
      layoutGraph(!preserveGraphCamera);
      drawGraph();
    }));
  }
  renderJourneyNav(journey, name);
  window.dispatchEvent(new CustomEvent("anaxigraph:viewchange", { detail: { name, journey, flow: selectedFlow } }));
}

function renderJourneyNav(journey, activeView) {
  const nav = document.getElementById("journey-subnav");
  if (!nav) return;
  const items = JOURNEY_VIEWS[journey] || [];
  nav.hidden = items.length < 2;
  nav.innerHTML = items.map(([view, label]) => (
    `<button class="${view === activeView ? "active" : ""}" data-subview="${view}">${label}</button>`
  )).join("");
}
