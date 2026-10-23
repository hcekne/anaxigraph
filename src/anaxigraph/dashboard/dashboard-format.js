import { escapeHtml, humanize } from "/assets/dashboard-core.js";

export function storyText(title, value) {
  if (!value) return "";
  return `<section><strong>${escapeHtml(title)}</strong><p>${escapeHtml(value)}</p></section>`;
}

export function storyList(title, values = []) {
  if (!values.length) return "";
  return `<section><strong>${escapeHtml(title)}</strong><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}

export function detailList(values = [], empty = "No data") {
  const items = values || [];
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>${escapeHtml(empty)}</li>`}</ul>`;
}

export function formatDate(value) {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 10);
  return parsed.toLocaleDateString(
    undefined, { year: "numeric", month: "short", day: "numeric" },
  );
}

export function mapLayerLabel(layer) {
  if (layer === "current") return "Current view";
  if (layer === "responsibility") return "Responsibility map";
  if (layer === "declared") return "Declared map";
  if (layer === "path") return "Path map";
  return humanize(layer);
}

export function mapLayerDescription(layer, source = "declared, responsibility, and path evidence") {
  if (layer === "responsibility") {
    return "Inferred from AI-reviewed file responsibilities and relationships, with confidence and evidence kept visible.";
  }
  if (layer === "declared") return "Shows only the optional architecture intent declared in this project's settings; unmatched files stay visibly unconfigured.";
  if (layer === "path") return "Uses deterministic directory and package rules; no AI is used, and the result is not presented as semantic meaning.";
  return `Shows declared intent where present, then inferred responsibilities, then path fallback. Source: ${source}.`;
}
