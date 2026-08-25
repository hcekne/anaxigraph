import {
  api,
  byId,
  escapeHtml,
  format,
  humanize,
  request,
  state,
  toast,
} from "/assets/dashboard-core.js";
import {
  findingCards,
  findingGroupSummary,
  findingQueryParams,
  findingResultNote,
  renderFindingFilterOptions,
} from "/assets/findings-view.js";
import { drawGraph, renderLegend, renderOverlayHelp } from "/assets/graph-view.js";
import { switchView } from "/assets/navigation.js";
import { renderOverview } from "/assets/overview-view.js";

export function renderFindings() {
  const page = state.findingPage;
  byId("finding-result-note").textContent = findingResultNote(page, state.findings.length);
  byId("finding-groups").innerHTML = findingGroupSummary(
    page?.view === "diagnostics" ? page.groups || [] : [],
  );
  const more = byId("finding-show-all");
  more.hidden = !page?.next_cursor;
  more.textContent = `Load next ${format.format(page?.page_size || 20)}`;
  renderFindingFilterOptions(page);
  byId("findings-table").innerHTML = findingCards(state.findings, {
    glossary: state.glossary,
  });
}

export function renderWorkflowGuide() {
  const statuses = state.glossary?.findings?.statuses || {};
  const ordered = ["new", "acknowledged", "planned", "accepted", "resolved", "dismissed"];
  byId("finding-workflow").innerHTML = ordered.map((name) => {
    const item = statuses[name] || { label: humanize(name), meaning: "" };
    return `<div class="workflow-step"><strong>${escapeHtml(item.label)}</strong><span>${escapeHtml(item.meaning)}</span></div>`;
  }).join("");
}

export function renderAgentResult(value, kind) {
  const result = byId("agent-result");
  const risk = value.risk || "low";
  if (kind === "scope") {
    state.highlightedPaths = new Set([
      ...(value.primary_files || []), ...(value.related_files || []),
    ].map((item) => item.path));
    state.protectedPaths = new Set((value.protected_files || []).map((item) => item.path));
    state.conflictPaths = new Set((value.active_branch_conflicts || []).map((item) => item.path));
    activateAgentOverlay();
    const findings = (value.known_findings || []).map(
      (item) => `#${item.id} ${item.plain_language?.what || item.summary} (${item.status})`,
    );
    const rules = (value.architecture_rules || []).map(
      (item) => `${item.rule_id}: ${item.description || humanize(item.rule_type)}`,
    );
    result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Recommended coding context</p><h2>${escapeHtml(value.goal)}</h2><p class="panel-copy">Primary files are the strongest matches. Related files are connected context, not a suggestion to edit all of them.</p></div><span class="risk ${escapeHtml(risk)}">${escapeHtml(risk)} risk</span></div>${(value.risk_reasons || []).map((item) => `<p class="muted">${escapeHtml(item)}</p>`).join("")}<div class="result-columns">${resultList("Likely implementation files", value.primary_files?.map((item) => item.path))}${resultList("Connected context", value.related_files?.map((item) => item.path))}${resultList("Relevant tests", value.tests)}${resultList("Existing findings", findings)}${resultList("Applicable rules", rules)}${resultList("Branch collisions", value.active_branch_conflicts?.map((item) => `${item.branch}: ${item.path}`))}</div>`;
    return;
  }
  result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Change impact</p><h2>${escapeHtml(value.target.path)}</h2><p class="panel-copy">Dependants use this target and may need verification if behavior or interfaces change.</p></div><span class="risk ${escapeHtml(risk)}">${escapeHtml(risk)} risk</span></div><div class="result-columns">${resultList("Direct dependants", value.direct_dependants?.map((item) => item.path))}${resultList("Indirect dependants", value.second_order_dependants?.map((item) => item.path))}${resultList("This file uses", value.outgoing_dependencies?.map((item) => item.path))}${resultList("Relevant tests", value.tests_relevant)}${resultList("Protected paths", value.critical_paths_affected)}${resultList("Possible migrations", value.database_migrations_possibly_affected)}</div>`;
}

function activateAgentOverlay() {
  byId("overlay-select").value = "agent";
  renderOverlayHelp();
  renderLegend();
  drawGraph();
}

function renderFindingHandoff(value) {
  const result = byId("agent-result");
  const finding = value.finding;
  const scope = value.scope || {};
  state.lastAgentPrompt = value.agent_prompt || "";
  state.highlightedPaths = new Set((value.recommended_context || []).map(String));
  state.protectedPaths = new Set((value.protected_paths || []).map(String));
  state.conflictPaths = new Set((scope.active_branch_conflicts || []).map((item) => item.path));
  activateAgentOverlay();
  const explanation = findingCards([finding], { glossary: state.glossary, actions: false });
  result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Finding #${finding.id} · agent handoff</p><h2>Work from the same explanation shown in the architecture map</h2><p class="panel-copy">${escapeHtml(value.workflow_note)}</p></div><span class="risk ${escapeHtml(value.risk)}">${escapeHtml(value.risk)} risk</span></div>${explanation}<div class="result-columns">${resultList("Recommended context", value.recommended_context)}${resultList("Relevant tests", value.relevant_tests)}${resultList("Protected paths", value.protected_paths)}${resultList("Verification", value.verification)}</div><h3>Copy this into Codex</h3><textarea id="agent-prompt" class="agent-prompt" readonly>${escapeHtml(state.lastAgentPrompt)}</textarea><div class="handoff-actions"><button id="copy-agent-prompt" class="button" type="button">Copy agent prompt</button><span class="muted">The structured version is available through ANAXIGRAPH_FINDING_CONTEXT.</span></div>`;
}

function resultList(title, values = []) {
  const safeValues = values || [];
  return `<div><h3>${escapeHtml(title)} · ${safeValues.length}</h3><ul>${safeValues.slice(0, 30).map((item) => `<li>${escapeHtml(item)}</li>`).join("") || "<li>None detected</li>"}</ul></div>`;
}

async function updateFindingStatus(findingId, status) {
  await request(api(`/api/findings/${findingId}/status`), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ status }),
  });
  await reloadFindings();
}

async function openFindingHandoff(findingId) {
  switchView("agents");
  byId("agent-result").innerHTML = `<p class="muted">Building affected-file, test, and dependency context for finding #${findingId}…</p>`;
  const value = await request(api(`/api/findings/${findingId}/context`));
  renderFindingHandoff(value);
}

export async function handleFindingAction(button) {
  const findingId = Number(button.dataset.finding);
  const action = button.dataset.action;
  button.disabled = true;
  try {
    if (action === "review") {
      await updateFindingStatus(findingId, "acknowledged");
      toast("Finding reviewed; it remains active and monitored.");
    } else if (action === "dismiss") {
      await updateFindingStatus(findingId, "dismissed");
      toast("Finding marked not actionable.");
    } else if (action === "accept") {
      await updateFindingStatus(findingId, "accepted");
      toast("Risk accepted; later scans will continue monitoring it.");
    } else if (action === "reopen") {
      await updateFindingStatus(findingId, "acknowledged");
      toast("Finding reopened for review.");
    } else if (action === "plan") {
      await updateFindingStatus(findingId, "planned");
      toast("Finding added to the agent queue.");
      await openFindingHandoff(findingId);
    } else if (action === "handoff") {
      await openFindingHandoff(findingId);
    }
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}

export async function reloadFindings({ append = false } = {}) {
  const more = byId("finding-show-all");
  const cursor = append ? state.findingPage?.next_cursor || "" : "";
  if (append && !cursor) return;
  more.disabled = true;
  try {
    const page = await request(api("/api/findings", findingQueryParams(cursor)));
    const items = append ? [...state.findings, ...(page.items || [])] : page.items || [];
    state.findings = items;
    state.findingPage = { ...page, items, shown: items.length,
      omitted: { ...page.omitted, before_cursor: 0 } };
    renderFindings();
    renderOverview();
    drawGraph();
  } catch (error) {
    toast(error.message, true);
  } finally {
    more.disabled = false;
  }
}
