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

export function patternOpportunityLabel(item) {
  if (!item || typeof item !== "object") return String(item || "Unnamed pattern");
  return item.name || "Unnamed pattern";
}

export function patternOpportunityExplanation(item) {
  if (!item || typeof item !== "object") return plainAiText(item);
  const language = item.plain_language || {};
  if (language.conclusion) {
    return [
      language.conclusion,
      language.why_it_may_matter,
      language.what_to_do,
    ].filter(Boolean).map(plainAiText).map(sentence).join(" ");
  }
  const name = patternOpportunityLabel(item);
  const effort = item.migration_cost
    ? `The expected effort and disruption are ${item.migration_cost}.`
    : "";
  return [
    `${name} may fit this code.`,
    plainAiText(item.rationale),
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
      ? `<h3>Should this code be combined or separated?</h3><p>${escapeHtml(plainAiText(value))}</p>`
      : "";
  }
  if (value.recommendation === "insufficient_evidence" && !value.rationale) return "";
  const language = value.plain_language || {};
  const conclusion = plainAiText(language.conclusion || consolidationConclusion(value));
  const reason = plainAiText(language.why_it_may_matter || value.rationale)
    || "The AI result did not give a clear reason for changing how this code is divided.";
  const action = plainAiText(language.what_to_do || consolidationAction(value));
  return `<h3>Should this code be merged or split?</h3><p><strong>${escapeHtml(sentence(conclusion))}</strong> ${escapeHtml(sentence(reason))} ${escapeHtml(sentence(action))}</p>`;
}

export function deadCodeList(values = []) {
  const descriptions = (values || []).map((item) => {
    if (!item || typeof item !== "object") return String(item || "");
    const language = item.plain_language || {};
    if (language.conclusion) {
      return [language.conclusion, language.what_to_do, language.deletion_rule]
        .filter(Boolean).map(plainAiText).map(sentence).join(" ");
    }
    const target = item.path_or_symbol || "This item";
    const reason = item.rationale
      ? `It was raised because ${lowerSentence(plainAiText(item.rationale))}`
      : "The analysis did not supply a concrete reason.";
    const check = item.verification
      ? `Before changing it, ${lowerSentence(plainAiText(item.verification))}`
      : "Trace its callers, settings, code that registers it when the application starts or runs, and focused tests before changing it.";
    return [
      `Do not delete ${target} from this result alone.`,
      reason,
      check,
      "Direct source-code links can miss uses through settings, framework setup, plugins, or generated code.",
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

function plainAiText(value) {
  let text = String(value || "").trim();
  const rewrites = [
    [/runtime registration/gi, "code registered when the application starts or runs"],
    [/static source links?/gi, "direct source-code links"],
    [/static edges?/gi, "direct source-code links"],
    [/runtime reachability/gi, "whether running code can reach it"],
    [/semantic (?:analysis|review)/gi, "AI review of what the code does"],
    [/module boundar(?:y|ies)/gi, "division between files"],
    [/public contracts?/gi, "names and behavior that callers rely on"],
    [/execution contracts?/gi, "required caller-visible behavior"],
    [/provider boundar(?:y|ies)/gi, "shared way callers use providers"],
    [/selection polic(?:y|ies)/gi, "rules for choosing an implementation"],
    [/behavior boundar(?:y|ies)/gi, "caller-visible behavior"],
    [/another abstraction/gi, "another shared layer of code"],
    [/\borchestration\b/gi, "coordination"],
    [/\bprotocols?\b/gi, "shared rules the parts use to communicate"],
    [/\bconfiguration\b/gi, "settings"],
    [/\breflection\b/gi, "code that looks up names while running"],
  ];
  for (const [pattern, replacement] of rewrites) {
    text = text.replace(pattern, (match) => (
      /^[A-Z]/.test(match) ? replacement[0].toUpperCase() + replacement.slice(1) : replacement
    ));
  }
  return text;
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
