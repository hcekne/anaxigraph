import { escapeHtml, format, humanize } from "/assets/dashboard-core.js";

export function detailList(values = [], empty = "No data") {
  const items = values || [];
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>${escapeHtml(empty)}</li>`}</ul>`;
}

export function patternOpportunityLabel(item) {
  if (!item || typeof item !== "object") return String(item || "Unnamed pattern");
  return `${item.name || "Unnamed pattern"} · ${format.format(Number(item.score || 0))}/100`;
}

export function patternOpportunityExplanation(item) {
  if (!item || typeof item !== "object") return String(item || "");
  const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% confidence`;
  return [
    patternOpportunityLabel(item),
    item.rationale,
    confidence,
    `${item.migration_cost || "unknown"} migration cost`,
  ].filter(Boolean).join(" · ");
}

export function patternOpportunityList(
  values = [], empty = "No contextual pattern opportunity recorded",
) {
  return detailList((values || []).map(patternOpportunityExplanation), empty);
}

export function consolidationMarkup(value) {
  if (!value || typeof value !== "object") {
    return value
      ? `<h3>Merge or split assessment</h3><p>${escapeHtml(String(value))}</p>`
      : "";
  }
  if (value.recommendation === "insufficient_evidence" && !value.rationale) return "";
  const candidates = value.candidates?.length ? ` Candidates: ${value.candidates.join(", ")}.` : "";
  return `<h3>Merge or split assessment</h3><p><strong>${escapeHtml(humanize(value.recommendation || "review"))} · ${format.format(Number(value.score || 0))}/100.</strong> ${escapeHtml(value.rationale || "No rationale supplied.")}${escapeHtml(candidates)}</p>`;
}

export function deadCodeList(values = []) {
  const descriptions = (values || []).map((item) => {
    if (!item || typeof item !== "object") return String(item || "");
    const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% confidence`;
    return [item.path_or_symbol, confidence, item.rationale, item.verification]
      .filter(Boolean).join(" · ");
  });
  return detailList(descriptions, "No evidence-backed dead-code candidate recorded");
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
  if (layer === "semantic") return "Semantic map (AI)";
  if (layer === "policy") return "Configured policy";
  if (layer === "inferred") return "Path inference";
  return humanize(layer);
}

export function mapLayerDescription(layer, source = "configured and inferred evidence") {
  if (layer === "semantic") {
    return "Proposed from module meaning, critiqued by an agent, and deterministically validated.";
  }
  if (layer === "policy") return "Repository-configured path groups only.";
  if (layer === "inferred") return "Deterministic path inference only.";
  return `Best available map · ${source}.`;
}
