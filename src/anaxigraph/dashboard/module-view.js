import {
  architectureFor,
  byId,
  escapeAttr,
  escapeHtml,
  format,
  humanize,
  state,
} from "/assets/dashboard-core.js";
import {
  consolidationMarkup,
  deadCodeList,
  detailList,
  formatDate,
  patternOpportunityExplanation,
  patternOpportunityLabel,
  patternOpportunityList,
} from "/assets/dashboard-format.js";

export function renderModuleFilters() {
  const options = (key) => [...new Set(state.modules.map((item) => {
    if (key === "architecture_area") return architectureFor(item)?.area;
    if (key === "architecture_subsystem") return architectureFor(item)?.subsystem;
    return item[key];
  }).filter(Boolean))].sort((left, right) => String(left).localeCompare(String(right)));
  const populate = (id, values, label, display = humanize) => {
    const select = byId(id);
    const selected = select.value;
    select.innerHTML = `<option value="">All ${label}</option>${values.map((value) => (
      `<option value="${escapeAttr(value)}">${escapeHtml(display(value))}</option>`
    )).join("")}`;
    if (values.includes(selected)) select.value = selected;
  };
  populate("module-area-filter", options("architecture_area"), "areas", (value) => architectureLabel("area", value));
  populate("module-subsystem-filter", options("architecture_subsystem"), "subsystems", (value) => architectureLabel("subsystem", value));
  populate("module-language-filter", options("language"), "languages");
}

function architectureLabel(kind, value) {
  const label = state.modules
    .map((item) => architectureFor(item))
    .find((placement) => placement?.[kind] === value)?.[`${kind}_label`];
  return label || humanize(value);
}

function moduleValue(item, key) {
  if (key === "coupling") return Number(item.fan_in || 0) + Number(item.fan_out || 0);
  if (key === "attention_score") {
    const score = item.evaluation?.attention_score;
    return score == null ? null : Number(score);
  }
  if (key === "architecture_area") {
    const placement = architectureFor(item) || {};
    return placement.area_label || placement.area;
  }
  return item[key];
}

function filteredModules() {
  const query = byId("module-search").value.trim().toLowerCase();
  const area = byId("module-area-filter").value;
  const subsystem = byId("module-subsystem-filter").value;
  const language = byId("module-language-filter").value;
  const includeReference = byId("module-include-reference").checked;
  const filtered = state.modules.filter((item) => {
    const evaluation = item.evaluation || {};
    const architecture = architectureFor(item) || {};
    const haystack = [
      item.path,
      item.summary,
      architecture.area,
      architecture.subsystem,
      architecture.area_label,
      architecture.subsystem_label,
      ...(item.responsibilities || []),
      ...(evaluation.pattern_candidates || []),
    ].join(" ").toLowerCase();
    return (includeReference || evaluation.monitored_by_default !== false)
      && (!query || haystack.includes(query))
      && (!area || architecture.area === area)
      && (!subsystem || architecture.subsystem === subsystem)
      && (!language || item.language === language);
  });
  const { key, direction } = state.moduleSort;
  filtered.sort((left, right) => {
    const a = moduleValue(left, key);
    const b = moduleValue(right, key);
    if (a == null && b == null) return left.path.localeCompare(right.path);
    if (a == null) return 1;
    if (b == null) return -1;
    const comparison = typeof a === "number" && typeof b === "number"
      ? a - b
      : String(a).localeCompare(String(b));
    return (direction === "asc" ? comparison : -comparison)
      || left.path.localeCompare(right.path);
  });
  return filtered;
}

export function renderModules() {
  const items = filteredModules();
  const pageSize = Number(byId("module-page-size").value || 100);
  const pages = Math.max(1, Math.ceil(items.length / pageSize));
  state.modulePage = Math.min(Math.max(1, state.modulePage), pages);
  const start = (state.modulePage - 1) * pageSize;
  const visible = items.slice(start, start + pageSize);
  const reviewable = state.modules.filter(
    (item) => item.evaluation?.monitored_by_default !== false,
  ).length;
  const hidden = state.modules.length - reviewable;
  byId("module-result-count").textContent = byId("module-include-reference").checked
    ? `${format.format(items.length)} of ${format.format(state.modules.length)} files`
    : `${format.format(items.length)} source or test files · ${format.format(hidden)} reference files hidden`;
  byId("module-page-label").textContent = `Page ${state.modulePage} of ${pages}`;
  byId("module-previous").disabled = state.modulePage <= 1;
  byId("module-next").disabled = state.modulePage >= pages;
  document.querySelectorAll("[data-module-sort]").forEach((button) => {
    const active = button.dataset.moduleSort === state.moduleSort.key;
    button.classList.toggle("active", active);
    if (active) button.dataset.direction = state.moduleSort.direction === "asc" ? "↑" : "↓";
    else delete button.dataset.direction;
  });
  byId("module-table-body").innerHTML = visible.map(moduleRow).join("")
    || '<tr><td colspan="12"><p class="muted">No files match these filters.</p></td></tr>';
}

function moduleRow(item) {
  const evaluation = item.evaluation || {};
  const placement = architectureFor(item) || {};
  const semanticCandidates = item.semantic?.pattern_opportunities || [];
  const candidates = semanticCandidates.length ? semanticCandidates : evaluation.pattern_candidates || [];
  const expanded = Number(state.expandedModuleId) === Number(item.artifact_id);
  const branchMeaning = `File-wide branch score ${format.format(item.complexity)}. This combines branches across all functions; it is not a code-quality grade.`;
  const row = `<tr class="module-row" data-module-id="${item.artifact_id}" aria-expanded="${expanded}"><td><span class="module-name">${escapeHtml(item.name)}</span><code class="module-path">${escapeHtml(item.path)}</code></td><td class="architecture-cell">${architectureMarkup(placement)}</td><td class="module-summary">${escapeHtml(item.summary)}</td><td class="pattern-cell">${patternMarkup(candidates, semanticCandidates, evaluation)}</td><td class="numeric">${format.format(item.lines_of_code)}</td><td class="numeric" title="${escapeAttr(branchMeaning)}">${format.format(item.complexity)}</td><td class="numeric" title="${format.format(item.fan_in)} direct links from other files · ${format.format(item.fan_out)} direct links to other files">${format.format(Number(item.fan_in || 0) + Number(item.fan_out || 0))}</td><td class="numeric">${coverageMarkup(item.line_coverage)}</td><td class="numeric">${format.format(item.change_count || 0)}</td><td>${formatDate(item.first_changed_at)}</td><td>${formatDate(item.last_commit_at)}</td><td class="numeric">${attentionMarkup(evaluation)}</td></tr>`;
  return expanded ? row + moduleDetailRow(item) : row;
}

function coverageMarkup(lineCoverage) {
  return lineCoverage == null
    ? '<span class="coverage-value missing">—</span>'
    : `<span class="coverage-value">${(Number(lineCoverage) * 100).toFixed(0)}%</span>`;
}

function architectureMarkup(placement) {
  const area = placement.area_label || humanize(placement.area || "unclassified");
  const subsystem = placement.subsystem_label || humanize(placement.subsystem || "");
  if (placement.subsystem) {
    return `<strong>${escapeHtml(area)}</strong><span>${escapeHtml(subsystem)}</span>`;
  }
  return `<strong>${escapeHtml(area)}</strong><span>${escapeHtml(placement.source || state.mapLayer)}</span>`;
}

function patternMarkup(candidates, semanticCandidates, evaluation) {
  if (!candidates.length) {
    const emptyLabel = evaluation.monitored_by_default === false
      ? "Not evaluated"
      : "No grounded proposal";
    return `<span class="pattern-none">${emptyLabel}</span>`;
  }
  const more = candidates.length > 1 ? ` +${candidates.length - 1}` : "";
  const source = semanticCandidates.length ? " · AI" : "";
  const title = candidates.map(patternOpportunityExplanation).join(" · ");
  return `<span class="pattern-candidate" title="${escapeAttr(title)}">${escapeHtml(patternOpportunityLabel(candidates[0]))}${more}${source}</span>`;
}

function attentionMarkup(evaluation) {
  if (evaluation.attention_score == null) {
    const meaning = evaluation.attention_score_meaning
      || evaluation.monitoring_reason
      || "Reference file";
    return `<span class="attention-pill reference" title="${escapeAttr(meaning)}">Reference</span>`;
  }
  const attention = String(evaluation.attention_label || "low").toLowerCase();
  const reasons = [
    evaluation.attention_score_meaning,
    ...(evaluation.attention_reasons || []),
  ].filter(Boolean).join(" · ");
  const guidance = evaluation.attention_guidance || evaluation.attention_label || "Background";
  return `<span class="attention-pill ${escapeAttr(attention)}" title="${escapeAttr(reasons)}">${escapeHtml(guidance)}</span>`;
}

function moduleDetailRow(item) {
  const evaluation = item.evaluation || {};
  const candidates = item.semantic?.pattern_opportunities?.length
    ? item.semantic.pattern_opportunities
    : evaluation.pattern_candidates || [];
  const detail = state.moduleDetails.get(item.path);
  const history = [
    item.first_change_commit
      ? `First indexed change ${String(item.first_change_commit).slice(0, 8)} · ${formatDate(item.first_changed_at)}`
      : "No indexed first-change commit",
    item.last_change_commit
      ? `Last change ${String(item.last_change_commit).slice(0, 8)} · ${formatDate(item.last_commit_at)}`
      : "No indexed last-change commit",
    item.last_change_subject || "No commit subject indexed",
  ];
  const semanticPanel = semanticPanelMarkup(item, detail);
  const fingerprints = `Exact file fingerprint ${String(item.raw_hash).slice(0, 12)} · code-structure fingerprint ${String(item.structural_hash).slice(0, 12)}. These identify versions; they are not scores.`;
  return `<tr class="module-detail-row"><td colspan="12"><div class="module-detail"><div><h3>Purpose</h3><p>${escapeHtml(item.summary)}</p><p class="muted">How this purpose was written: ${escapeHtml(item.summary_source)}</p><p><code class="module-path">${escapeHtml(fingerprints)}</code></p><div class="module-detail-actions"><button class="secondary-button" data-module-graph="${escapeAttr(item.path)}" type="button">Open in graph</button></div></div><div><h3>Jobs detected in this file</h3>${detailList(item.responsibilities || [], "No specific job was detected")}<h3>Change history</h3>${detailList(history)}</div>${semanticPanel}<div><h3>${evaluation.monitored_by_default === false ? "Reference file" : "Included when choosing what to inspect first"}</h3><p>${escapeHtml(evaluation.monitoring_reason || "AnaxiGraph includes this source file when choosing what to inspect first.")}</p><h3>When to inspect · ${escapeHtml(evaluation.attention_guidance || "Background")}</h3><p>${escapeHtml(evaluation.attention_score_meaning || "This ordering is not a code-quality grade.")}</p>${detailList(evaluation.attention_reasons)}<h3>Pattern ideas from code checks</h3>${patternOpportunityList(candidates, "No pattern idea has direct code evidence yet")}<p>${escapeHtml(evaluation.note || "")}</p></div></div></td></tr>`;
}

function semanticPanelMarkup(item, detail) {
  if (!detail) return "<div><h3>AI map</h3><p>Loading the saved AI description…</p></div>";
  const intrinsic = detail.semantic_dossiers?.intrinsic?.value ?? {};
  const contextual = detail.semantic_dossiers?.context?.value ?? {};
  const value = contextual.summary ? contextual : intrinsic;
  const language = item.semantic?.plain_language ?? detail.semantic_plain_language ?? {};
  const related = [...(value.similar_modules ?? []), ...(value.overlaps ?? [])];
  const summary = preferredText(language.what_this_file_does, value.summary, item.summary);
  const role = preferredText(language.role_in_repository, value.architecture_role);
  const changed = preferredText(language.what_changed_in_description, value.change_summary);
  const placement = preferredText(language.where_related_work_belongs, value.placement_guidance);
  const extensionPoints = preferredList(language.places_for_adding_behavior, value.extension_points);
  const risks = preferredList(language.risks_and_uncertainty, value.risks);
  const mapState = preferredText(
    language.conclusion,
    "The AI map has not described this file yet.",
  );
  return `<div><h3>AI map</h3><p>${escapeHtml(mapState)}</p><h3>What this file does</h3><p>${escapeHtml(summary)}</p>${optionalSection("Role in this repository", role)}${optionalSection("What changed in this AI description", changed)}<h3>Files with related or overlapping work</h3>${optionalParagraph(language.related_file_evidence)}${detailList(related, "The AI map did not identify related or overlapping files")}<h3>Places designed for adding behavior</h3>${detailList(extensionPoints, "The AI map did not identify a specific place for adding behavior")}<h3>Patterns that may fit</h3>${patternOpportunityList(value.pattern_opportunities)}${consolidationMarkup(value.consolidation_assessment)}${optionalSection("Where related work belongs", placement)}<h3>Code that may no longer be used</h3>${deadCodeList(value.dead_code_candidates)}<h3>Risks and uncertainty</h3>${detailList(risks, "The AI map did not record a specific risk")}</div>`;
}

function preferredText(...values) {
  return values.find((value) => typeof value === "string" && value.length) ?? "";
}

function preferredList(primary, fallback) {
  return Array.isArray(primary) ? primary : fallback ?? [];
}

function optionalSection(title, value) {
  return value ? `<h3>${escapeHtml(title)}</h3><p>${escapeHtml(value)}</p>` : "";
}

function optionalParagraph(value) {
  return value ? `<p class="muted">${escapeHtml(value)}</p>` : "";
}
