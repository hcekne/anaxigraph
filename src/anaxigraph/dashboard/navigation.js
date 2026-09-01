import { layoutGraph } from "/assets/graph-model.js";
import { drawGraph } from "/assets/graph-view.js";

const VIEW_JOURNEY = {
  overview: "understand",
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
  renderJourneyNav("understand", "overview");
}

export function switchView(name, preserveGraphCamera = false) {
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
  window.dispatchEvent(new CustomEvent("anaxigraph:viewchange", { detail: { name, journey } }));
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
