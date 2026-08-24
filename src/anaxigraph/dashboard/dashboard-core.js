export const state = {
  repositories: [],
  repositoryId: null,
  glossary: null,
  overview: null,
  modules: [],
  graph: { nodes: [], edges: [], snapshot: null },
  findings: [],
  findingPage: null,
  snapshots: [],
  trends: [],
  historyInfo: null,
  semanticStatus: null,
  moduleDetails: new Map(),
  selectedNode: null,
  highlightedPaths: new Set(),
  protectedPaths: new Set(),
  conflictPaths: new Set(),
  transform: { x: 0, y: 0, scale: 1 },
  positions: new Map(),
  groupRegions: [],
  groupParents: new Map(),
  groupRoots: [],
  hiddenGroups: new Set(),
  historyPlayToken: 0,
  historyPlaying: false,
  historyPollTimer: null,
  semanticPollTimer: null,
  lastAgentPrompt: "",
  moduleSort: { key: "lines_of_code", direction: "desc" },
  modulePage: 1,
  expandedModuleId: null,
  themeColors: null,
  mapLayer: "effective",
  reloadRepository: null,
};

export const supportedThemes = new Set([
  "constellation-light", "constellation-dark", "high-contrast", "anaxigraph",
]);

export const architecturePalettes = {
  "constellation-light": [
    "#167a96", "#315f9f", "#b87513", "#7652a4",
    "#a12b43", "#327b82", "#6d7a29", "#a04b78",
  ],
  "constellation-dark": [
    "#7ae5ff", "#8eb7ff", "#ffcf72", "#c0a3ff",
    "#ff9aa8", "#66d6d9", "#d4df80", "#f2a9cf",
  ],
  "high-contrast": [
    "#00ffff", "#66ccff", "#ffff00", "#ff66ff",
    "#ff4d4d", "#00ff99", "#ccff33", "#ff99cc",
  ],
  anaxigraph: [
    "#72e0b3", "#7db8ff", "#f4bd69", "#b99cf7",
    "#f07970", "#5fd0df", "#d2e274", "#f3a9d0",
  ],
};

export const byId = (id) => document.getElementById(id);
export const format = new Intl.NumberFormat();

export function currentTheme() {
  const value = document.documentElement.dataset.theme;
  return supportedThemes.has(value) ? value : "constellation-light";
}

export function readThemeColors() {
  const styles = window.getComputedStyle(document.documentElement);
  const value = (name) => styles.getPropertyValue(name).trim();
  return {
    cool: value("--graph-cool"),
    hot: value("--graph-hot"),
    warm: value("--graph-warm"),
    low: value("--graph-low"),
    missing: value("--graph-missing"),
    drift: value("--graph-drift"),
    idle: value("--graph-idle"),
    safe: value("--graph-safe"),
    edge: value("--graph-edge"),
    nodeStroke: value("--graph-node-stroke"),
    selected: value("--graph-selected"),
    label: value("--graph-label"),
  };
}

export function applyTheme(theme, persist = true) {
  const value = supportedThemes.has(theme) ? theme : "constellation-light";
  document.documentElement.dataset.theme = value;
  if (persist) {
    try {
      window.localStorage.setItem("anaxigraph.theme", value);
    } catch (_) {
      // The theme still applies when storage is unavailable.
    }
  }
  if (byId("theme-select")) byId("theme-select").value = value;
  const styles = window.getComputedStyle(document.documentElement);
  const meta = byId("theme-color");
  if (meta) meta.content = styles.getPropertyValue("--bg").trim();
  state.themeColors = readThemeColors();
}

export function setupTheme() {
  applyTheme(currentTheme(), false);
}

export async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch (_) {
      // Preserve the HTTP fallback when the response is not JSON.
    }
    throw new Error(message);
  }
  return response.json();
}

export function api(path, params = {}) {
  const query = new URLSearchParams();
  if (state.repositoryId != null) query.set("repository_id", state.repositoryId);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, value);
  });
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
}

export function selectedRepository() {
  return state.repositories.find((item) => Number(item.id) === Number(state.repositoryId));
}

export function architectureFor(item, layer = state.mapLayer) {
  if (layer === "effective") {
    return {
      area: item.architecture_area,
      subsystem: item.architecture_subsystem || item.architecture_group,
      source: item.architecture_source,
    };
  }
  const placement = item.architecture_layers?.[layer] || null;
  if (placement || layer !== "policy") return placement;
  return {
    area: "unconfigured",
    subsystem: "unconfigured",
    source: "not present in configured policy",
  };
}

export function toast(message, error = false) {
  const element = byId("toast");
  element.textContent = message;
  element.style.borderColor = error ? "var(--red)" : "";
  element.classList.add("visible");
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => element.classList.remove("visible"), 4200);
}

export function humanize(value) {
  return String(value || "")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}

export function hash(value) {
  let result = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    result ^= value.charCodeAt(index);
    result = Math.imul(result, 16777619);
  }
  return result >>> 0;
}

export function mix(left, right, amount) {
  const parse = (value) => [1, 3, 5].map((index) => parseInt(value.slice(index, index + 2), 16));
  const a = parse(left);
  const b = parse(right);
  return `rgb(${a.map((value, index) => Math.round(value + (b[index] - value) * amount)).join(",")})`;
}

export function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"]/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
  })[character]);
}

export function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

export function delay(milliseconds) {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}
