const number = new Intl.NumberFormat();

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function humanize(value) {
  return String(value || "").replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function findingCards(items, { glossary = {}, actions = true } = {}) {
  if (!items.length) return '<p class="muted">No findings match this view and its filters.</p>';
  return items.map((item) => findingCard(item, glossary, actions)).join("");
}

function findingCard(item, glossary, actions) {
  const guide = glossary?.findings?.statuses?.[item.status];
  const status = guide?.label || humanize(item.status);
  const language = findingLanguage(item);
  const priority = language.priority?.label
    ? `<span class="finding-priority">${escapeHtml(language.priority.label)} priority</span> · `
    : "";
  const action = language.next_step
    ? `<div class="finding-action-copy"><strong>What to do next</strong><p>${escapeHtml(language.next_step)}</p></div>`
    : "";
  const tags = item.affected_artifacts?.length
    ? `<div class="tag-list">${item.affected_artifacts.slice(0, 8).map((path) => `<span class="tag">${escapeHtml(path)}</span>`).join("")}</div>`
    : "";
  return `<article class="finding-card"><span class="severity ${escapeHtml(item.severity)}"></span><div><div class="finding-meta">${priority}${escapeHtml(status)}</div><h3>${escapeHtml(language.what)}</h3><div class="finding-meaning"><strong>Why this matters</strong><p>${escapeHtml(language.why_it_matters)}</p></div>${action}${tags}${actionabilityDetails(item, language)}</div>${actions ? findingActionButtons(item) : ""}</article>`;
}

function findingLanguage(item) {
  return item.plain_language || {
    what: item.summary,
    why_it_matters: item.explanation,
    next_step: item.recommended_action,
    facts: item.actionability?.evidence?.plain_language || [],
    check: { id: item.finding_type, label: humanize(item.finding_type) },
    level: { id: item.severity, meaning: `${humanize(item.severity)} level.` },
    confidence: {
      value: Number(item.confidence || 0),
      meaning: "This number says how sure AnaxiGraph is about the measurement, not whether the design is bad.",
    },
    source: { id: item.source || "deterministic", meaning: "AnaxiGraph recorded this from repository evidence." },
    priority: {
      score: item.priority_score,
      label: item.priority_label,
      meaning: "The priority score only decides which finding appears first; it is not a grade for the code.",
      reasons: item.priority_reasons || [],
    },
    when_no_change_may_be_needed: item.actionability?.false_positive_conditions || [],
  };
}

function actionabilityDetails(item, language) {
  const value = item.actionability || {};
  const reasons = language.priority?.reasons || value.why_ranked || item.priority_reasons || [];
  const falsePositives = language.when_no_change_may_be_needed || value.false_positive_conditions || [];
  const affected = value.affected || {};
  const areas = affected.architecture_areas || [];
  const meanings = findingMeanings(language);
  return `<details class="finding-evidence"><summary>How AnaxiGraph reached this finding</summary><div class="finding-evidence-grid">${detailList("What AnaxiGraph measured", language.facts || [])}${detailList("What the labels and numbers mean", meanings)}${detailList("Why this appears where it does", reasons)}${detailList("When this may not need a change", falsePositives)}${detailList("Affected architecture areas", areas)}${detailList("How to check the result", value.verification ? [value.verification] : [])}</div></details>`;
}

function findingMeanings(language) {
  const check = language.check || {};
  const result = [];
  if (check.label) {
    result.push(`The check is “${check.label}.” Its API name is ${check.id || "not supplied"}.`);
  }
  [language.level?.meaning, language.source?.meaning, language.confidence?.meaning, language.priority?.meaning]
    .filter(Boolean)
    .forEach((value) => result.push(value));
  return result;
}

function detailList(title, values) {
  if (!values.length) return "";
  return `<section><strong>${escapeHtml(title)}</strong><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></section>`;
}

function findingActionButtons(item) {
  const buttons = [];
  if (["new", "regressed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="review">Mark reviewed</button>`);
  }
  if (!["planned", "resolved", "dismissed"].includes(item.status)) {
    buttons.push(`<button class="primary-action" data-finding="${item.id}" data-action="plan">Plan agent work</button>`);
  }
  if (item.status === "planned") {
    buttons.push(`<button class="primary-action" data-finding="${item.id}" data-action="handoff">Open agent handoff</button>`);
  }
  if (!["resolved", "dismissed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="dismiss">Not actionable</button>`);
  }
  if (["new", "acknowledged", "regressed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="accept">Accept risk</button>`);
  }
  if (["accepted", "dismissed"].includes(item.status)) {
    buttons.push(`<button data-finding="${item.id}" data-action="reopen">Reopen</button>`);
  }
  return `<div class="finding-actions">${buttons.join("")}</div>`;
}

export function findingResultNote(page, loaded) {
  if (!page) return "Loading findings…";
  const total = Number(page.total_matching || 0);
  const label = page.view === "attention"
    ? (total === 1 ? "finding to check" : "findings to check")
    : (total === 1 ? "finding" : "findings");
  const threshold = page.view === "attention"
    ? ` This view includes planned or returned work, plus findings that meet the project's ${page.filters.attention_minimum_severity} level or ${page.filters.attention_minimum_priority}-point queue limit.`
    : " This complete view keeps every finding; filters and pages only change what is shown.";
  return `Showing ${number.format(loaded)} of ${number.format(total)} matching ${label}, ordered by what is most useful to check first.${threshold}`;
}

export function findingGroupSummary(groups = []) {
  if (!groups.length) return "";
  const cards = groups.slice(0, 8).map((item) => (
    `<span class="finding-group"><strong>${number.format(item.count)}</strong> ${escapeHtml(humanize(item.finding_type))}<small>${escapeHtml(humanize(item.architecture_area))}</small></span>`
  )).join("");
  return `<div class="finding-groups"><p>Repeated findings are grouped here so the common shape is easier to see.</p><div>${cards}</div></div>`;
}

export function findingQueryParams(cursor = "") {
  const element = (id) => document.getElementById(id);
  return {
    view: element("finding-view-filter")?.value || "attention",
    cursor,
    status: element("finding-status-filter")?.value || "",
    severity: element("finding-severity-filter")?.value || "",
    finding_type: element("finding-type-filter")?.value || "",
    architecture_area: element("finding-area-filter")?.value || "",
    minimum_confidence: element("finding-confidence-filter")?.value || "0",
    module: element("finding-module-filter")?.value.trim() || "",
  };
}

export function renderFindingFilterOptions(page) {
  const available = page?.available_filters || {};
  updateSelect("finding-type-filter", available.finding_types || [], "Any check");
  updateSelect("finding-area-filter", available.architecture_areas || [], "Any area");
}

function updateSelect(id, values, emptyLabel) {
  const select = document.getElementById(id);
  const selected = select.value;
  const options = [...values];
  if (selected && !options.includes(selected)) options.unshift(selected);
  select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>${options.map((value) => (
    `<option value="${escapeHtml(value)}">${escapeHtml(humanize(value))}</option>`
  )).join("")}`;
  select.value = selected;
}

export function resetFindingFilters() {
  const values = {
    "finding-view-filter": "attention",
    "finding-status-filter": "",
    "finding-severity-filter": "",
    "finding-type-filter": "",
    "finding-area-filter": "",
    "finding-confidence-filter": "0",
    "finding-module-filter": "",
  };
  Object.entries(values).forEach(([id, value]) => {
    document.getElementById(id).value = value;
  });
}

export function bindFindingFilters(onChange) {
  const element = (id) => document.getElementById(id);
  [
    "finding-severity-filter",
    "finding-type-filter",
    "finding-area-filter",
    "finding-confidence-filter",
  ].forEach((id) => element(id).addEventListener("change", onChange));
  element("finding-status-filter").addEventListener("change", (event) => {
    if (["resolved", "dismissed", "accepted"].includes(event.target.value)) {
      element("finding-view-filter").value = "diagnostics";
    }
    onChange();
  });
  element("finding-view-filter").addEventListener("change", (event) => {
    const status = element("finding-status-filter");
    if (event.target.value === "attention" && ["resolved", "dismissed", "accepted"].includes(status.value)) {
      status.value = "";
    }
    onChange();
  });
  element("finding-filter-form").addEventListener("submit", (event) => {
    event.preventDefault();
    onChange();
  });
  element("finding-filter-reset").addEventListener("click", () => {
    resetFindingFilters();
    onChange();
  });
}
