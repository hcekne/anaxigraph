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
  const confidence = `${(Number(item.confidence || 0) * 100).toFixed(0)}% detection confidence`;
  const confidenceHelp = glossary?.findings?.confidence
    || "Confidence describes detector evidence, not severity.";
  const reasons = item.priority_reasons || [];
  const priority = item.priority_score == null
    ? ""
    : `<span class="finding-priority" title="${escapeHtml(reasons.join(" · "))}">${escapeHtml(item.priority_label || "Priority")} ${number.format(item.priority_score)}/100</span> · `;
  const action = item.recommended_action
    ? `<div class="finding-action-copy"><strong>Smallest suggested next step</strong><p>${escapeHtml(item.recommended_action)}</p></div>`
    : "";
  const tags = item.affected_artifacts?.length
    ? `<div class="tag-list">${item.affected_artifacts.slice(0, 8).map((path) => `<span class="tag">${escapeHtml(path)}</span>`).join("")}</div>`
    : "";
  return `<article class="finding-card"><span class="severity ${escapeHtml(item.severity)}"></span><div><div class="finding-meta">${priority}${escapeHtml(humanize(item.finding_type))} · ${escapeHtml(status)} · <span class="finding-provenance" title="${escapeHtml(confidenceHelp)}">${escapeHtml(confidence)}</span> · ${escapeHtml(item.source || "deterministic")}</div><h3>${escapeHtml(item.summary)}</h3><p>${escapeHtml(item.explanation)}</p>${action}${tags}${actionabilityDetails(item)}</div>${actions ? findingActionButtons(item) : ""}</article>`;
}

function actionabilityDetails(item) {
  const value = item.actionability || {};
  const reasons = value.why_ranked || item.priority_reasons || [];
  const falsePositives = value.false_positive_conditions || [];
  const affected = value.affected || {};
  const areas = affected.architecture_areas || [];
  if (!reasons.length && !falsePositives.length && !value.verification) return "";
  return `<details class="finding-evidence"><summary>Evidence, caveats, and verification</summary><div class="finding-evidence-grid">${detailList("Why this is ranked", reasons)}${detailList("Could be a false positive when", falsePositives)}${detailList("Architecture areas", areas)}${detailList("Verification", value.verification ? [value.verification] : [])}</div></details>`;
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
  const label = page.view === "attention" ? "attention signal" : "diagnostic";
  const threshold = page.view === "attention"
    ? ` The queue includes planned/regressed work plus findings at or above ${page.filters.attention_minimum_severity} severity or ${page.filters.attention_minimum_priority}/100 priority.`
    : " The diagnostics view is the complete ledger; filters and pages never discard records.";
  return `Showing ${number.format(loaded)} of ${number.format(total)} matching ${label}${total === 1 ? "" : "s"}, ordered by architectural priority.${threshold}`;
}

export function findingGroupSummary(groups = []) {
  if (!groups.length) return "";
  const cards = groups.slice(0, 8).map((item) => (
    `<span class="finding-group"><strong>${number.format(item.count)}</strong> ${escapeHtml(humanize(item.finding_type))}<small>${escapeHtml(humanize(item.architecture_area))}</small></span>`
  )).join("");
  return `<div class="finding-groups"><p>Repeated diagnostics are grouped here before the individual evidence cards.</p><div>${cards}</div></div>`;
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
  updateSelect("finding-type-filter", available.finding_types || [], "Any detector");
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
