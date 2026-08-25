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
  if (kind === "scope") {
    result.innerHTML = scopeResultMarkup(value);
    return;
  }
  result.innerHTML = impactResultMarkup(value);
}

function scopeResultMarkup(value) {
  state.highlightedPaths = new Set([
    ...(value.primary_files ?? []), ...(value.related_files ?? []),
  ].map((item) => item.path));
  state.protectedPaths = new Set((value.protected_files ?? []).map((item) => item.path));
  state.conflictPaths = new Set((value.active_branch_conflicts ?? []).map((item) => item.path));
  activateAgentOverlay();
  const findings = (value.known_findings ?? []).map(
    (item) => `#${item.id} ${item.plain_language?.what ?? item.summary} (${item.status})`,
  );
  const rules = (value.architecture_rules ?? []).map(
    (item) => `${item.rule_id}: ${item.description ?? humanize(item.rule_type)}`,
  );
  const lists = resultList("Likely implementation files", value.primary_files?.map(pathOf))
    + resultList("Related files worth reading", value.related_files?.map(pathOf))
    + resultList("Relevant tests", value.tests)
    + resultList("Existing findings", findings)
    + resultList("Project rules that apply", rules)
    + resultList("Files also changed on another branch", value.active_branch_conflicts?.map(branchPath));
  return agentResultHeader(
    value,
    "Files and facts for this coding task",
    value.goal,
    "Likely implementation files are the strongest matches. Related files may explain the behavior; this is not a suggestion to edit all of them.",
  ) + architectureDecisionMarkup(value.architecture_decision)
    + `<div class="result-columns">${lists}</div>`;
}

function impactResultMarkup(value) {
  const lists = resultList("Files that use it directly", value.direct_dependants?.map(pathOf))
    + resultList(
      "Files that may be affected through another file",
      value.second_order_dependants?.map(pathOf),
    )
    + resultList("Files this target uses", value.outgoing_dependencies?.map(pathOf))
    + resultList("Relevant tests", value.tests_relevant)
    + resultList("Files project rules mark for extra care", value.critical_paths_affected)
    + resultList("Possible database changes", value.database_migrations_possibly_affected);
  return agentResultHeader(
    value,
    "What this change may affect",
    value.target.path,
    "The listed files use this target and may need checking if its behavior or caller-visible names change.",
  ) + `<div class="result-columns">${lists}</div>`;
}

function agentResultHeader(value, eyebrow, title, fallback) {
  const risk = value.risk ?? "low";
  const language = value.plain_language ?? {};
  const riskMeaning = language.risk?.meaning;
  const meaningMarkup = riskMeaning ? `<p class="muted">${escapeHtml(riskMeaning)}</p>` : "";
  const reasons = (value.risk_reasons ?? [])
    .map((item) => `<p class="muted">${escapeHtml(item)}</p>`)
    .join("");
  return `<div class="panel-heading"><div><p class="eyebrow">${escapeHtml(eyebrow)}</p><h2>${escapeHtml(title)}</h2><p class="panel-copy">${escapeHtml(language.how_to_use_this ?? fallback)}</p></div><span class="risk ${escapeHtml(risk)}">${escapeHtml(riskLabel(risk))}</span></div>${meaningMarkup}${reasons}`;
}

function pathOf(item) {
  return item.path;
}

function branchPath(item) {
  return `${item.branch}: ${item.path}`;
}

function riskLabel(value) {
  return ({ high: "Extra care", medium: "Check nearby code", low: "No extra warning" })[value]
    || "Read the evidence";
}

function architectureDecisionMarkup(decision = {}) {
  const language = decision.plain_language || {};
  if (!language.conclusion) return "";
  const placement = decision.placement?.plain_language || {};
  const constraints = decision.change_constraints?.plain_language || {};
  const verification = decision.verification?.plain_language || {};
  return `<section class="agent-decision-copy"><h3>Where to make the change and how to check it</h3>
    ${decisionText("What this advice uses", language.conclusion)}
    ${decisionText("Where to start", placement.conclusion)}
    ${decisionText("What to preserve", constraints.conclusion)}
    ${decisionText("How to verify it", verification.conclusion)}
    ${decisionList("Next steps", verification.what_to_do || [])}
    ${decompositionMarkup(decision.decomposition)}</section>`;
}

function decompositionMarkup(decomposition = {}) {
  const items = decomposition.items || [];
  if (!items.length) return "";
  return items.map((item) => {
    const language = item.plain_language || {};
    const slices = (item.slices || []).map((slice) => {
      const names = slice.symbol_names
        || (slice.symbols || []).map((symbol) => symbol.name).filter(Boolean);
      const destination = slice.destination?.path
        ? ` → ${slice.destination.path}`
        : "";
      return `${slice.job}${destination}${names.length ? `: ${names.join(", ")}` : ""}`;
    });
    return `<div class="agent-decomposition"><h4>Should this large file be split?</h4>
      ${decisionText("Recommendation", language.conclusion)}
      ${decisionList("Safe extraction order", slices)}
      ${decisionList("Why keeping it together may be better", language.reasons_not_to_split || [])}
      ${decisionList("Checks after each step", language.how_to_check || [])}</div>`;
  }).join("");
}

function decisionText(title, value) {
  return value
    ? `<div><strong>${escapeHtml(title)}</strong><p>${escapeHtml(value)}</p></div>`
    : "";
}

function decisionList(title, values) {
  return values.length
    ? `<div><strong>${escapeHtml(title)}</strong><ul>${values.map((value) => `<li>${escapeHtml(value)}</li>`).join("")}</ul></div>`
    : "";
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
  result.innerHTML = `<div class="panel-heading"><div><p class="eyebrow">Finding #${finding.id} · coding-agent handoff</p><h2>Give the coding agent the same explanation you can read here</h2><p class="panel-copy">${escapeHtml(value.workflow_note)}</p></div><span class="risk ${escapeHtml(value.risk)}">${escapeHtml(riskLabel(value.risk))}</span></div>${explanation}<div class="result-columns">${resultList("Files worth reading", value.recommended_context)}${resultList("Relevant tests", value.relevant_tests)}${resultList("Files project rules mark for extra care", value.protected_paths)}${resultList("How to check the result", value.verification)}</div><h3>Copy this into Codex</h3><textarea id="agent-prompt" class="agent-prompt" readonly>${escapeHtml(state.lastAgentPrompt)}</textarea><div class="handoff-actions"><button id="copy-agent-prompt" class="button" type="button">Copy agent prompt</button><span class="muted">ANAXIGRAPH_FINDING_CONTEXT provides the same information as named JSON fields for coding tools.</span></div>`;
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
  byId("agent-result").innerHTML = `<p class="muted">Finding affected files, tests, and direct code links for finding #${findingId}…</p>`;
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
      toast("Finding selected for coding-agent work.");
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
