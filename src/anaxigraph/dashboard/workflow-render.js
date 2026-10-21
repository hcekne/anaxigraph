import { escapeAttr, escapeHtml, format } from "/assets/dashboard-core.js";
import { workflowState, statusLabels } from "/assets/workflow-model.js";

const number = value => format.format(Number(value || 0));
const diagrams = {
  architecture: { number: "04", columns: 3, handoff: "Select target + plan transition" },
  mapping: { number: "01", columns: 4, handoff: "Validate + repair" },
  patterns: { number: "02", columns: 3, handoff: "Independent critique" },
  "fresh-eyes": { number: "03", columns: 4, handoff: "Apply mission + constraints" },
};

export function workflowTabs(flows, selected) {
  return flows.map(flow => `<button type="button" role="tab" id="workflow-tab-${flow.id}"
    aria-selected="${flow.id === selected}" tabindex="${flow.id === selected ? 0 : -1}" aria-controls="workflow-panel" data-flow="${flow.id}">
    <span class="workflow-tab-number">${diagrams[flow.id].number}</span><span class="workflow-tab-copy">
    <strong>${escapeHtml(flow.name)}</strong><small>${statusLabels[workflowState(flow)]} · ${flow.steps.filter(item => item.status === "complete").length} / ${flow.steps.length} steps</small>
    </span><span class="workflow-tab-arrow" aria-hidden="true">→</span></button>`).join("");
}

export function workflowDiagram(flow, selectedStep) {
  const diagram = diagrams[flow.id];
  return `<div class="workflow-heading"><div>
    <h2><span>${diagram.number}</span> ${escapeHtml(flow.title)}</h2>${flow.update ? `<aside class="workflow-source-update" aria-label="Source changes"><strong>Source changed · your work is saved</strong><button type="button" data-progress-step="${flow.update.next}" aria-haspopup="dialog">See what changed →</button></aside>` : `<p>${escapeHtml(flow.description)}</p>`}</div>
    <div class="workflow-heading-actions"><span class="workflow-status ${workflowState(flow)}">${statusLabels[workflowState(flow)]}</span>
    <button id="workflow-focus" type="button" class="secondary-button">Focus map</button></div></div>
    <div class="workflow-canvas" data-columns="${diagram.columns}" data-handoff="${diagram.handoff}"><svg class="workflow-edges" aria-hidden="true"></svg>
    <ol class="workflow-nodes">${flow.steps.map((item, index) => nodeMarkup(item, index, selectedStep)).join("")}</ol></div>
    <p class="workflow-explore-hint">Select a card for progress, models and evidence. Configure opens its settings here.</p>`;
}

function nodeMarkup(item, index, selectedStep) {
  const isSoftware = item.owner !== "AI worker";
  const models = item.plan?.map(worker => worker.model) || item.jobs.models || [];
  const palette = isSoftware ? "software" : models.length === 1 ? modelPalette(models[0]) : "model";
  const progress = item.total > 0 ? Math.min(100, item.done / item.total * 100) : item.status === "complete" ? 100 : 0;
  return `<li><article class="workflow-card ${palette} ${item.status}${selectedStep === item.id ? " selected" : ""}"><button type="button" class="workflow-node ${palette} ${item.status}${item.parallel ? " parallel" : ""}"
    data-step="${item.id}" aria-pressed="${selectedStep === item.id}" aria-haspopup="dialog" aria-controls="workflow-step-dialog">
    <span class="workflow-node-top"><span class="workflow-number">${index + 1}</span>
    <strong>${escapeHtml(item.title)}</strong></span>
    <span class="workflow-description">${escapeHtml(item.updateNote || item.description)}</span>${activityMarkup(item)}
    ${item.parallel ? parallelMarkup(item.stages) : ""}
    <span class="workflow-count">${countMarkup(item)}</span>
    ${reviewProgressMarkup(item)}
    <span class="workflow-track" aria-hidden="true"><i style="width:${progress}%"></i></span>
    <span class="workflow-node-bottom"><span class="workflow-status ${item.status}">${item.activity?.label || statusLabels[item.status]}</span>
    ${item.reused ? `<small>${number(item.reused)} reused</small>` : ""}</span>
    ${cardError(item)}
    </button>${cardActions(item)}</article></li>`;
}

function countMarkup(item) {
  if (item.saved != null) return `${number(item.saved)}${item.savedTotal > 1 ? ` / ${number(item.savedTotal)}` : ""} <small>saved ${escapeHtml(item.unit)}</small>`;
  return `${number(item.done)}${item.total == null ? "" : ` / ${number(item.total)}`} <small>${item.freshness?.refresh ? "current " : ""}${escapeHtml(item.unit)}</small>`;
}

function cardError(item) {
  const pool = item.poolErrors?.[0], job = item.jobs.errors?.[0];
  if (!pool && !job) return "";
  const error = pool || job;
  const label = pool ? `${pool.model} unavailable` : job.status === "retry" ? "Retry pending" : "Job failed";
  return `<span class="workflow-card-error" title="${escapeAttr(error.error)}">${escapeHtml(label)} · View error</span>`;
}

function activityMarkup(item) {
  if (!item.activity) return "";
  const { running, capacity, label } = item.activity;
  const count = capacity && capacity >= running ? `${number(running)} / ${number(capacity)}` : number(running);
  const heading = running ? `${count} worker${capacity === 1 || (!capacity && running === 1) ? "" : "s"} active` : `${label}…`;
  return `<span class="workflow-activity" role="status"><i class="workflow-spinner" aria-hidden="true"></i><b>${heading}</b></span>`;
}

function nextRunMarkup(item) {
  if (!item.plan) return item.owner === "AI worker" ? "" : '<span class="workflow-next-run"><b>No model needed</b><small>Handled by AnaxiGraph</small></span>';
  return `<span class="workflow-next-run"><b>Next run · ${item.customized ? "your settings" : "suggested"}</b>${item.plan.map((worker, index) => {
    const prefix = item.mode === "sequence" ? `Pass ${index + 1} · ` : item.mode === "proposals" ? `Proposal ${String.fromCharCode(65 + index)} · ` : "";
    const count = ["parallel", "sequence"].includes(item.mode) ? `${worker.workers} parallel worker${worker.workers === 1 ? "" : "s"}` : "1 worker";
    return `<span class="workflow-planned-model ${modelPalette(worker.model)}"><strong>${escapeHtml(prefix)}${worker.provider === "claude" ? "Anthropic" : "OpenAI"}</strong><span>${escapeHtml(modelName(worker.model))}</span><small>${count}</small></span>`;
  }).join("")}${item.mode === "sequence" ? "<small>Ordered passes · one runs at a time</small>" : ""}</span>`;
}

function cardActions(item) {
  if (item.plan) return `<div class="workflow-card-actions"><button type="button" data-configure-step="${item.id}" aria-haspopup="dialog" aria-controls="workflow-step-dialog">Configure</button><button type="button" data-run-step="${item.id}">${item.status === "refresh_needed" ? "Update this step" : "Run this step"} →</button></div>`;
  if (item.id === "scan") return '<div class="workflow-card-actions"><button type="button" data-run-scan>Refresh source scan</button></div>';
  if (["pattern_plan", "brief", "grounding"].includes(item.id)) return `<div class="workflow-card-actions"><button type="button" data-run-step="${item.id}">Run step →</button></div>`;
  return item.view ? `<div class="workflow-card-actions"><button type="button" data-workflow-view="${item.view}">Explore results →</button></div>` : "";
}

function parallelMarkup(stages = []) {
  return `<span class="workflow-proposal-lanes">${stages.map((item, index) => {
    const model = item.provenance?.executor_model || item.provenance?.model;
    return `<span class="${model ? modelPalette(model) : "model"}">
      <b>${String.fromCharCode(65 + index)}</b><small>${item.state === "current" ? "Saved" : "Pending"}</small></span>`;
  }).join("")}</span>`;
}

function modelPalette(name) {
  if (/claude|opus|sonnet|haiku/i.test(name)) return "opus";
  return /sol/i.test(name) ? "sol" : "model";
}

function modelName(name) {
  return name.replace(/^gpt-/i, "GPT-").replace(/-(luna|sol|astra|terra)$/i, (_, model) => ` ${model[0].toUpperCase()}${model.slice(1)}`)
    .replace(/^claude-(\w+)-(\d+)-(\d+)$/i, (_, model, major, minor) => `Claude ${model[0].toUpperCase()}${model.slice(1)} ${major}.${minor}`);
}

export function workflowDetail(item) {
  const jobs = item.jobs;
  return `<div class="workflow-detail-heading"><div><p class="eyebrow">Selected step</p>
    <h3>${escapeHtml(item.title)}</h3></div><span class="workflow-status ${item.status}">${statusLabels[item.status]}</span></div>
    <p class="workflow-count">${countMarkup(item)}</p>
    ${reviewProgressMarkup(item, true)}
    ${activityMarkup(item)}
    ${activeWorkers(jobs.workers)}
    <p>${escapeHtml(item.detail || item.description)}</p>
    ${patternInputDetail(item.patternInputs)}
    ${savedProgressDetail(item)}
    ${nextRunMarkup(item)}
    ${item.plan ? "<p>Run this step completes missing earlier work, then stops here.</p>" : ""}
    ${item.jobs.models?.length ? `<p><strong>Recorded models:</strong> ${item.jobs.models.map(escapeHtml).join(", ")}</p>` : ""}
    ${item.reused ? `<p>${number(item.reused)} current results were reused from an earlier scan.</p>` : ""}
    ${jobTelemetry(jobs)}${stageDetails(item.stages)}
    ${(item.poolErrors || []).map(error => `<p class="workflow-error"><strong>${escapeHtml(error.provider)} · ${escapeHtml(error.model)} unavailable</strong><br>${escapeHtml(error.error)}</p>`).join("")}
    ${(jobs.errors || []).map(error => `<p class="workflow-error"><strong>${error.status === "retry" ? "Retry pending" : "Recorded failure"} · ${escapeHtml(error.scope_key)}</strong><br>${escapeHtml(error.error)}</p>`).join("")}
    ${item.view ? `<button type="button" class="secondary-button" data-workflow-view="${item.view}">Explore ${item.view === "overview" ? "the Charter" : item.view === "fresh-eyes" ? "review results" : item.view} →</button>` : ""}`;
}

function reviewProgressMarkup(item, detailed = false) {
  const progress = item.reviewProgress;
  if (!progress?.passes?.length) return "";
  const passes = detailed ? progress.passes : [progress.passes.at(-1)];
  return passes.map(pass => `<span class="workflow-review-progress"><strong>Pass ${number(pass.pass)} · ${number(pass.completed_batches)} / ${number(pass.total_batches)} batches saved</strong><span>${number(pass.active_workers)} workers active · ${number(pass.elapsed_seconds)}s elapsed</span><span>${pass.final ? "Final reconciliation" : "Pass reconciliation"} · ${escapeHtml(statusLabels[pass.reconciliation] || pass.reconciliation)}</span></span>`).join("");
}

function patternInputDetail(inputs) {
  if (!inputs?.evaluations?.length) return "";
  return `<details><summary>Pattern evidence used by this comparison</summary><ul>${inputs.evaluations.map(item => `<li>${escapeHtml(item.scope)} · ${item.current ? "current" : "changed since comparison"}<br><code>${escapeHtml(item.fingerprint)}</code></li>`).join("")}</ul>${inputs.omitted_evaluations ? `<p>${inputs.omitted_evaluations} additional evaluations remain in the saved comparison manifest.</p>` : ""}</details>`;
}

function savedProgressDetail(item) {
  const counts = item.freshness, previous = item.previous;
  let detail = "";
  if (item.reusePending) detail += `<p class="workflow-saved-progress">${number(item.saved)} file results remain saved from scan ${number(item.reusePending)}. The new scan has not checked their reuse yet. Updating the workflow first checks which results are still current.</p>`;
  if (counts && (counts.refresh || counts.new)) {
    detail += `<section class="workflow-saved-progress"><h4>What needs updating</h4><p>${number(counts.current)} current · ${number(counts.refresh)} saved results need refresh · ${number(counts.new)} have no saved result.</p><p>${item.id === "context" ? "Context can change when a file’s neighbours, interfaces or dependency links change, even if the file itself is untouched." : "Only missing descriptions and those whose source or analysis requirements changed need to run."}</p><ul>${(item.affected || []).map(row => `<li><code>${escapeHtml(row.path)}</code><span>${row[item.id] === "new" ? "First run" : "Refresh saved result"}</span></li>`).join("")}</ul>${counts.refresh + counts.new > (item.affected || []).length ? "<p>Showing the first affected files; the totals include all files.</p>" : ""}</section>`;
  }
  return detail + savedTaxonomyDetail(item);
}

function savedTaxonomyDetail(item) {
  const previous = item.previous;
  if (!previous) return "";
  let detail = "";
  if (previous) {
    detail += `<section class="workflow-saved-progress"><h4>Saved work from the earlier source</h4><p>1 proposal · ${number(previous.reviews)} / ${number(previous.required_reviews)} review passes saved${previous.failed_reviews ? ` · ${number(previous.failed_reviews)} failed` : ""}.</p>${item.saved != null ? `<p>For the current source: ${number(item.done)} / ${number(item.total)} ${escapeHtml(item.unit)} ready. Earlier results have not been counted as current.</p>` : ""}<p>Scan ${number(previous.snapshot_id)}${previous.commit_sha ? ` · commit ${escapeHtml(previous.commit_sha.slice(0, 7))}` : ""}. ${escapeHtml([previous.proposal_model, ...(previous.review_models || [])].filter(Boolean).join(" · "))}</p><p>Refresh the affected file evidence first. Small changes reuse the saved proposal; changed evidence is reviewed again. A new proposal is needed only when the map’s responsibilities or policy have changed substantially.</p>${previous.error ? `<details><summary>Earlier review failure</summary><p class="workflow-error">${escapeHtml(previous.error)}</p></details>` : ""}</section>`;
  }
  return detail;
}

function activeWorkers(workers = []) {
  return workers.filter(worker => worker.running > 0).map(worker => `<p class="workflow-active-worker">Running now: ${number(worker.running)} × ${escapeHtml(worker.executor_model || worker.executor_id || "worker")}</p>`).join("");
}

function jobTelemetry(jobs) {
  if (jobs.input_tokens == null) return "";
  return `<dl class="workflow-facts">
    <div><dt>Completed model jobs</dt><dd>${number(jobs.completed)}</dd></div>
    <div><dt>Running now</dt><dd>${number(jobs.running)}</dd></div>
    <div><dt>Input tokens</dt><dd>${number(jobs.input_tokens)}</dd></div>
    <div><dt>Output tokens</dt><dd>${number(jobs.output_tokens)}</dd></div>
    </dl><p class="muted">Job totals can include repeated work. File coverage above counts current saved descriptions.
    ${jobs.token_counts_missing ? `${number(jobs.token_counts_missing)} completed jobs have unknown token usage.` : ""}</p>`;
}

function stageDetails(stages = []) {
  if (!stages.length) return "";
  return `<div class="workflow-stage-records">${stages.map(item => `<article><strong>${escapeHtml(item.label || item.key)}</strong>
    <p>${escapeHtml(item.provenance?.executor_model || item.provenance?.model || "No model result saved yet")}</p>
    <p>${escapeHtml(item.reason || "Waiting to start")}</p>
    ${item.required_executor ? `<p>Required executor: ${escapeHtml(item.required_executor)}</p>` : ""}
    ${item.telemetry?.token_counts_reported ? `<small>${number(item.telemetry.input_tokens)} input / ${number(item.telemetry.output_tokens)} output tokens</small>` : ""}
    </article>`).join("")}</div>`;
}

export function drawWorkflowEdges(canvas) {
  if (!canvas || !canvas.offsetWidth) return;
  const list = canvas.querySelector("ol");
  const nodes = [...list.children];
  const preferred = Number(canvas.dataset.columns);
  const columns = canvas.clientWidth >= preferred * 174 + (preferred - 1) * 22 ? preferred : canvas.clientWidth >= 420 ? 2 : 1;
  list.style.gridTemplateColumns = `repeat(${columns}, minmax(0, 1fr))`;
  nodes.forEach((node, index) => {
    const row = Math.floor(index / columns);
    node.style.gridRow = row + 1;
    node.style.gridColumn = row % 2 ? columns - index % columns : index % columns + 1;
  });
  const origin = canvas.getBoundingClientRect();
  const paths = nodes.slice(1).map((node, index) => connectionPaths(nodes[index], node, origin));
  const svg = canvas.querySelector("svg");
  svg.setAttribute("viewBox", `0 0 ${canvas.clientWidth} ${canvas.clientHeight}`);
  svg.innerHTML = `<defs><marker id="workflow-arrow" markerWidth="9" markerHeight="9" refX="8" refY="4" orient="auto"><path d="M1 1 L7 4 L1 7"/></marker></defs>${paths.join("")}
    ${columns === preferred ? handoffLabel(nodes, preferred, origin, canvas.dataset.handoff) : ""}`;
}

function connectionPaths(fromNode, toNode, origin) {
  const from = fromNode.firstElementChild.getBoundingClientRect(), to = toNode.firstElementChild.getBoundingClientRect();
  if (fromNode.style.gridRow !== toNode.style.gridRow) {
    const x = from.left + from.width / 2 - origin.left;
    return `<path d="M${x},${from.bottom - origin.top + 4} V${to.top - origin.top - 5}"/>`;
  }
  const forward = to.left > from.left;
  const starts = connectionPorts(fromNode, from, forward, origin);
  const ends = connectionPorts(toNode, to, !forward, origin);
  const middle = ((forward ? from.right + to.left : from.left + to.right) / 2) - origin.left;
  return starts.flatMap(start => ends.map(end => `<path d="M${start.x},${start.y} H${middle} V${end.y} H${end.x}"/>`)).join("");
}

function connectionPorts(node, box, right, origin) {
  const lanes = [...node.querySelectorAll(".workflow-proposal-lanes > span")];
  const boxes = lanes.length ? lanes.map(lane => lane.getBoundingClientRect()) : [box];
  return boxes.map(rect => ({ x: (right ? rect.right + 4 : rect.left - 4) - origin.left, y: rect.top + rect.height / 2 - origin.top }));
}

function handoffLabel(nodes, columns, origin, label) {
  if (nodes.length <= columns) return "";
  const from = nodes[columns - 1].firstElementChild.getBoundingClientRect(), to = nodes[columns].firstElementChild.getBoundingClientRect();
  const x = from.left + from.width / 2 - origin.left - 14;
  const y = (from.bottom + to.top) / 2 - origin.top + 4;
  return `<text x="${x}" y="${y}" text-anchor="end">${escapeHtml(label)}</text>`;
}

export function overviewWorkflowLinks(flows) {
  return `<div><p class="eyebrow">Your repository, step by step</p><h2>See how the map comes together</h2>
    <p>Explore progress, inspect each handoff, and start optional reviews.</p></div>
    <div class="workflow-shortcuts">${flows.map(flow => `<button type="button" data-open-flow="${flow.id}">
    <strong>${escapeHtml(flow.name)} <span aria-hidden="true">→</span></strong>
    <span>${statusLabels[workflowState(flow)]} · ${flow.steps.filter(item => item.status === "complete").length} / ${flow.steps.length} steps</span></button>`).join("")}</div>`;
}
