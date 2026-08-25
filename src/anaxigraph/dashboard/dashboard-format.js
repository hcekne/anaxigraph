import { escapeHtml, humanize } from "/assets/dashboard-core.js";

export function detailList(values = [], empty = "No data") {
  const items = values || [];
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("") || `<li>${escapeHtml(empty)}</li>`}</ul>`;
}

export function patternOpportunityLabel(item) {
  if (!item || typeof item !== "object") return String(item || "Unnamed pattern");
  return item.name || "Unnamed pattern";
}

export function patternOpportunityExplanation(item) {
  if (!item || typeof item !== "object") return String(item || "");
  const language = item.plain_language || {};
  if (language.conclusion) {
    return [
      language.conclusion,
      language.why_it_may_matter,
      language.what_to_do,
    ].filter(Boolean).map(sentence).join(" ");
  }
  const name = patternOpportunityLabel(item);
  const effort = item.migration_cost
    ? `The expected effort and disruption are ${item.migration_cost}.`
    : "";
  return [
    `${name} may fit this code.`,
    item.rationale,
    effort,
    "Treat this as a design idea to check, not as a grade for the code.",
  ].filter(Boolean).map(sentence).join(" ");
}

export function patternOpportunityList(
  values = [], empty = "The AI map did not record a pattern idea for this code",
) {
  return detailList((values || []).map(patternOpportunityExplanation), empty);
}

export function consolidationMarkup(value) {
  if (!value || typeof value !== "object") {
    return value
      ? `<h3>Should this code be combined or separated?</h3><p>${escapeHtml(String(value))}</p>`
      : "";
  }
  if (value.recommendation === "insufficient_evidence" && !value.rationale) return "";
  const language = value.plain_language || {};
  const conclusion = language.conclusion || consolidationConclusion(value);
  const reason = language.why_it_may_matter || value.rationale
    || "The AI result did not give a clear reason for changing how this code is divided.";
  const action = language.what_to_do || consolidationAction(value);
  return `<h3>Should this code be merged or split?</h3><p><strong>${escapeHtml(sentence(conclusion))}</strong> ${escapeHtml(sentence(reason))} ${escapeHtml(sentence(action))}</p>`;
}

export function deadCodeList(values = []) {
  const descriptions = (values || []).map((item) => {
    if (!item || typeof item !== "object") return String(item || "");
    const language = item.plain_language || {};
    if (language.conclusion) {
      return [language.conclusion, language.what_to_do, language.deletion_rule]
        .filter(Boolean).map(sentence).join(" ");
    }
    const target = item.path_or_symbol || "This item";
    const reason = item.rationale
      ? `It was raised because ${lowerSentence(item.rationale)}`
      : "The analysis did not supply a concrete reason.";
    const check = item.verification
      ? `Before changing it, ${lowerSentence(item.verification)}`
      : "Trace its callers, configuration, runtime registration, and focused tests before changing it.";
    return [
      `Do not delete ${target} from this result alone.`,
      reason,
      check,
      "Static source links can miss uses through configuration, frameworks, plugins, or generated code.",
    ].map(sentence).join(" ");
  });
  return detailList(descriptions, "AnaxiGraph did not find code that appears unused");
}

function consolidationConclusion(value) {
  const candidates = (value.candidates || []).join(", ") || "nearby code";
  if (value.recommendation === "keep") return `Keep this code separate from ${candidates} for now.`;
  if (value.recommendation === "merge") {
    return `Consider combining this code with ${candidates}, but test the proposal first.`;
  }
  if (value.recommendation === "split") {
    return "Consider splitting this code, but test whether the proposed parts have clear responsibilities.";
  }
  return "Do not merge or split this code based on this result; there is not enough evidence.";
}

function consolidationAction(value) {
  if (!["merge", "split"].includes(value.recommendation)) {
    return "Leave the code divided as it is unless stronger evidence from code, Git history, and tests changes the result.";
  }
  return "Check responsibilities, public behavior, callers, and focused tests before moving any code.";
}

function sentence(value) {
  const text = String(value || "").trim();
  return text && !/[.?!]$/.test(text) ? `${text}.` : text;
}

function lowerSentence(value) {
  const text = sentence(value);
  return text ? `${text[0].toLowerCase()}${text.slice(1)}` : text;
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
  if (layer === "semantic") return "AI-created map";
  if (layer === "policy") return "Project settings";
  if (layer === "inferred") return "File-path guesses";
  return humanize(layer);
}

export function mapLayerDescription(layer, source = "configured and inferred evidence") {
  if (layer === "semantic") {
    return "Created from AI descriptions of what files do, checked by a separate AI pass, then checked against the indexed file list.";
  }
  if (layer === "policy") return "Shows only the code areas defined by path rules in this project's settings.";
  if (layer === "inferred") return "Guesses code areas from file paths and common runtime conventions; no AI is used.";
  return `Shows the best map currently available. Source: ${source}.`;
}
