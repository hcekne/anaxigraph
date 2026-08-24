import { state } from "/assets/dashboard-core.js";
import { layoutGraph } from "/assets/graph-model.js";
import { drawGraph } from "/assets/graph-view.js";

export function switchView(name, preserveGraphCamera = false) {
  document.querySelectorAll(".tab").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === name);
  });
  document.querySelectorAll(".view").forEach((item) => {
    item.classList.toggle("active", item.id === `view-${name}`);
  });
  if (name === "graph") {
    window.setTimeout(() => {
      layoutGraph(!preserveGraphCamera);
      drawGraph();
    }, 0);
  }
}

export function resetGraphCamera() {
  state.transform = { x: 0, y: 0, scale: 1 };
  layoutGraph(false);
  drawGraph();
}
