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
  const populate = (id, values, label) => {
    const select = byId(id);
    const selected = select.value;
    select.innerHTML = `<option value="">All ${label}</option>${values.map((value) => (
      `<option value="${escapeAttr(value)}">${escapeHtml(humanize(value))}</option>`
    )).join("")}`;
    if (values.includes(selected)) select.value = selected;
  };
  populate("module-area-filter", options("architecture_area"), "areas");
  populate("module-subsystem-filter", options("architecture_subsystem"), "subsystems");
  populate("module-language-filter", options("language"), "languages");
}

function moduleValue(item, key) {
  if (key === "coupling") return Number(item.fan_in || 0) + Number(item.fan_out || 0);
  if (key === "attention_score") {
    const score = item.evaluation?.attention_score;
    return score == null ? null : Number(score);
  }
  if (key === "architecture_area") return architectureFor(item)?.area;
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
    ? `${format.format(items.length)} of ${format.format(state.modules.length)} modules`
    : `${format.format(items.length)} reviewable modules · ${format.format(hidden)} reference artifacts hidden`;
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
    || '<tr><td colspan="12"><p class="muted">No modules match these filters.</p></td></tr>';
}

function moduleRow(item) {
  const evaluation = item.evaluation || {};
  const placement = architectureFor(item) || {};
  const coverage = item.line_coverage == null
    ? '<span class="coverage-value missing">—</span>'
    : `<span class="coverage-value">${(Number(item.line_coverage) * 100).toFixed(0)}%</span>`;
  const architecture = placement.subsystem
    ? `<strong>${escapeHtml(humanize(placement.area))}</strong><span>${escapeHtml(humanize(placement.subsystem))}</span>`
    : `<strong>${escapeHtml(humanize(placement.area || "unclassified"))}</strong><span>${escapeHtml(placement.source || state.mapLayer)}</span>`;
  const attention = String(evaluation.attention_label || "low").toLowerCase();
  const semanticCandidates = item.semantic?.pattern_opportunities || [];
  const candidates = semanticCandidates.length ? semanticCandidates : evaluation.pattern_candidates || [];
  const pattern = candidates.length
    ? `<span class="pattern-candidate" title="${escapeAttr(candidates.map(patternOpportunityExplanation).join(" · "))}">${escapeHtml(patternOpportunityLabel(candidates[0]))}${candidates.length > 1 ? ` +${candidates.length - 1}` : ""}${semanticCandidates.length ? " · AI" : ""}</span>`
    : `<span class="pattern-none">${evaluation.monitored_by_default === false ? "Not evaluated" : "No grounded proposal"}</span>`;
  const attentionValue = evaluation.attention_score == null
    ? `<span class="attention-pill reference" title="${escapeAttr(evaluation.monitoring_reason || "Reference artifact")}">—</span>`
    : `<span class="attention-pill ${escapeAttr(attention)}" title="${escapeAttr((evaluation.attention_reasons || []).join(" · "))}">${format.format(evaluation.attention_score)}</span>`;
  const expanded = Number(state.expandedModuleId) === Number(item.artifact_id);
  const row = `<tr class="module-row" data-module-id="${item.artifact_id}" aria-expanded="${expanded}"><td><span class="module-name">${escapeHtml(item.name)}</span><code class="module-path">${escapeHtml(item.path)}</code></td><td class="architecture-cell">${architecture}</td><td class="module-summary">${escapeHtml(item.summary)}</td><td class="pattern-cell">${pattern}</td><td class="numeric">${format.format(item.lines_of_code)}</td><td class="numeric">${format.format(item.complexity)}</td><td class="numeric" title="${format.format(item.fan_in)} incoming · ${format.format(item.fan_out)} outgoing">${format.format(Number(item.fan_in || 0) + Number(item.fan_out || 0))}</td><td class="numeric">${coverage}</td><td class="numeric">${format.format(item.change_count || 0)}</td><td>${formatDate(item.first_changed_at)}</td><td>${formatDate(item.last_commit_at)}</td><td class="numeric">${attentionValue}</td></tr>`;
  return expanded ? row + moduleDetailRow(item) : row;
}

function moduleDetailRow(item) {
  const evaluation = item.evaluation || {};
  const candidates = item.semantic?.pattern_opportunities?.length
    ? item.semantic.pattern_opportunities
    : evaluation.pattern_candidates || [];
  const semanticState = item.semantic || {};
  const detail = state.moduleDetails.get(item.path);
  const intrinsic = detail?.semantic_dossiers?.intrinsic?.value || {};
  const contextual = detail?.semantic_dossiers?.context?.value || {};
  const semanticPurpose = contextual.summary || intrinsic.summary || item.summary;
  const semanticRole = contextual.architecture_role || intrinsic.architecture_role;
  const semanticInsights = [
    ...(contextual.similar_modules || intrinsic.similar_modules || []),
    ...(contextual.overlaps || intrinsic.overlaps || []),
    ...(contextual.extension_points || intrinsic.extension_points || []),
  ];
  const semanticPatterns = contextual.pattern_opportunities || intrinsic.pattern_opportunities || [];
  const semanticDeadCode = contextual.dead_code_candidates || intrinsic.dead_code_candidates || [];
  const consolidation = contextual.consolidation_assessment || intrinsic.consolidation_assessment;
  const semanticRisks = contextual.risks || intrinsic.risks || [];
  const history = [
    item.first_change_commit
      ? `First indexed change ${String(item.first_change_commit).slice(0, 8)} · ${formatDate(item.first_changed_at)}`
      : "No indexed first-change commit",
    item.last_change_commit
      ? `Last change ${String(item.last_change_commit).slice(0, 8)} · ${formatDate(item.last_commit_at)}`
      : "No indexed last-change commit",
    item.last_change_subject || "No commit subject indexed",
  ];
  const semanticPanel = !detail
    ? `<div><h3>AI understanding · ${escapeHtml(humanize(semanticState.status || "not started"))}</h3><p>Loading the current semantic dossier…</p></div>`
    : `<div><h3>AI understanding · ${escapeHtml(humanize(semanticState.status || "not started"))}</h3><p>${escapeHtml(semanticPurpose || "No model-backed dossier is current for this module.")}</p>${semanticRole ? `<h3>Architecture role</h3><p>${escapeHtml(semanticRole)}</p>` : ""}${contextual.change_summary ? `<h3>Meaning changed</h3><p>${escapeHtml(contextual.change_summary)}</p>` : ""}<h3>Related responsibilities and extension seams</h3>${detailList(semanticInsights, "No evidence-backed overlap or extension seam recorded")}<h3>Pattern opportunities</h3>${patternOpportunityList(semanticPatterns)}${consolidationMarkup(consolidation)}${contextual.placement_guidance ? `<h3>Where new work belongs</h3><p>${escapeHtml(contextual.placement_guidance)}</p>` : ""}<h3>Code that may no longer be used</h3>${deadCodeList(semanticDeadCode)}<h3>Risks and uncertainty</h3>${detailList(semanticRisks, semanticState.reason || "No semantic risk recorded")}</div>`;
  return `<tr class="module-detail-row"><td colspan="12"><div class="module-detail"><div><h3>Purpose · ${escapeHtml(item.summary_source)}</h3><p>${escapeHtml(item.summary)}</p><p><code class="module-path">raw ${escapeHtml(String(item.raw_hash).slice(0, 12))} · structure ${escapeHtml(String(item.structural_hash).slice(0, 12))}</code></p><div class="module-detail-actions"><button class="secondary-button" data-module-graph="${escapeAttr(item.path)}" type="button">Open in graph</button></div></div><div><h3>Responsibilities</h3>${detailList(item.responsibilities || [], "No structured responsibilities detected")}<h3>Git biography</h3>${detailList(history)}</div>${semanticPanel}<div><h3>Review scope · ${evaluation.monitored_by_default === false ? "Reference" : "Monitored"}</h3><p>${escapeHtml(evaluation.monitoring_reason || "Included in attention triage.")}</p><h3>Attention · ${escapeHtml(evaluation.attention_label || "Low")}</h3>${detailList(evaluation.attention_reasons)}<h3>Pattern review</h3>${patternOpportunityList(candidates, "No detector-grounded pattern candidate yet")}<p>${escapeHtml(evaluation.note || "")}</p></div></div></td></tr>`;
}
