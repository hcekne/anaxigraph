const number = new Intl.NumberFormat();
const findingTypeLabels = {
  module_complexity: "File has many lines",
  long_function: "Function has many lines",
  symbol_complexity: "Function has many branches",
  high_fan_out: "File directly uses many other files",
  high_fan_in: "Many files directly use this file",
  dependency_cycle: "Files depend on one another in a loop",
  architecture_violation: "Code crossed a repository-area rule",
  architecture_drift: "File no longer fits its declared area",
  weak_test_coverage: "Tests miss part of a file",
  possible_dead_code: "File may no longer be used",
};

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
  const attention = language.priority?.guidance || "Use the explanation to decide when to check this.";
  const tags = item.affected_artifacts?.length
    ? `<div class="tag-list">${item.affected_artifacts.slice(0, 8).map((path) => `<span class="tag">${escapeHtml(path)}</span>`).join("")}</div>`
    : "";
  const story = [
    storyList("What AnaxiGraph saw", language.facts || []),
    storyText("Why this matters", language.why_it_matters),
    storyText("What to do", language.next_step),
    storyList("This may be fine when", language.when_no_change_may_be_needed || []),
    storyText("How to check the result", language.how_to_check),
  ].join("");
  return `<article class="finding-card"><span class="severity ${escapeHtml(item.severity)}"></span><div><div class="finding-meta">${escapeHtml(status)} · ${escapeHtml(attention)}</div><h3>${escapeHtml(language.what)}</h3><div class="finding-story">${story}</div>${tags}</div>${actions ? findingActionButtons(item) : ""}</article>`;
}

function findingLanguage(item) {
  return item.plain_language || {
    what: item.summary,
    why_it_matters: item.explanation,
    next_step: item.recommended_action,
    facts: item.actionability?.evidence?.plain_language || [],
    how_to_check: item.actionability?.verification || "Run focused tests and scan the repository again.",
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
      guidance: "Use the explanation to decide when to check this.",
      meaning: "The priority score only decides which finding appears first; it is not a grade for the code.",
      reasons: item.priority_reasons || [],
    },
    when_no_change_may_be_needed: item.actionability?.false_positive_conditions || [],
  };
}

function storyText(title, value) {
  if (!value) return "";
  return `<section><strong>${escapeHtml(title)}</strong><p>${escapeHtml(value)}</p></section>`;
}

function storyList(title, values) {
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
    ? " This view includes selected work, returned conditions, and the observations the project asked to see first."
    : " This complete view keeps every finding; filters and pages only change what is shown.";
  return `Showing ${number.format(loaded)} of ${number.format(total)} matching ${label}, ordered by what is most useful to check first.${threshold}`;
}

export function findingGroupSummary(groups = []) {
  if (!groups.length) return "";
  const cards = groups.slice(0, 8).map((item) => (
    `<span class="finding-group"><strong>${number.format(item.count)}</strong> ${escapeHtml(findingTypeLabel(item.finding_type))}<small>${escapeHtml(humanize(item.architecture_area))}</small></span>`
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
  updateSelect("finding-type-filter", available.finding_types || [], "Any check", findingTypeLabel);
  updateSelect("finding-area-filter", available.architecture_areas || [], "Any area");
}

function updateSelect(id, values, emptyLabel, label = humanize) {
  const select = document.getElementById(id);
  const selected = select.value;
  const options = [...values];
  if (selected && !options.includes(selected)) options.unshift(selected);
  select.innerHTML = `<option value="">${escapeHtml(emptyLabel)}</option>${options.map((value) => (
    `<option value="${escapeHtml(value)}">${escapeHtml(label(value))}</option>`
  )).join("")}`;
  select.value = selected;
}

function findingTypeLabel(value) {
  return findingTypeLabels[value] || humanize(value);
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
