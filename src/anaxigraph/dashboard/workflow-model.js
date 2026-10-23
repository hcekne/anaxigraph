// Display saved coverage separately from the jobs that produced it.
import { applySavedProgress } from "/assets/workflow-freshness.js";
import { stepRun, stepActivityLabel, workflowRuns } from "/assets/workflow-activity.js";
import { architectureWorkflow } from "/assets/architecture-workflow.js";

export const statusLabels = {
  complete: "Complete", running: "Running", queued: "Queued", failed: "Needs attention",
  interrupted: "Worker stopped", waiting: "Waiting", not_started: "Not run", skipped: "Not enabled",
  refresh_needed: "Needs update",
};

export function jobFacts(data, kind, scope) {
  const matches = item => item.job_kind === kind && (!scope || item.scope_type === scope);
  const rows = data.semantic?.telemetry?.semantic?.current_snapshot?.actions || [];
  const value = rows.find(matches) || {};
  const live = data.coverage?.live_jobs?.find(matches) || {};
  const saved = (data.coverage?.document_models || [])
    .filter(item => item.document_kind === kind && (!scope || item.scope_type === scope))
    .flatMap(item => (item.models || "").split(",")).filter(Boolean);
  return { ...value, running: live.running || 0, interrupted: live.interrupted || 0,
    workers: (data.coverage?.workers || []).filter(matches),
    models: [...new Set([...(value.models || []), ...saved])],
    errors: (data.coverage?.failures || []).filter(matches) };
}

export function step(id, title, description, options = {}) {
  const { done = 0, total = null, jobs = {}, enabled = true, zeroComplete = false } = options;
  const complete = total != null && done >= total && (total > 0 || zeroComplete);
  const status = jobs.running ? "running" : complete ? "complete"
    : jobs.failed || jobs.errors?.length ? "failed" : jobs.interrupted ? "interrupted"
      : jobs.pending || jobs.retry ? "queued" : done ? "waiting"
        : enabled ? "not_started" : "skipped";
  return { id, title, description, jobs, unit: "results", owner: "AI worker", ...options,
    done: Number(done || 0), total, status: options.status || status };
}

export function flowState(steps) {
  return ["running", "failed", "interrupted", "refresh_needed", "queued", "waiting"]
    .find(status => steps.some(item => item.status === status))
    || (steps.every(item => ["complete", "skipped"].includes(item.status)) ? "complete" : "not_started");
}

export function workflowState(flow) {
  return flow.state || flowState(flow.steps);
}

export function buildFlows(data, files = 0, startingStep = null) {
  const flows = [mappingFlow(data, files), patternFlow(data), freshFlow(data), architectureWorkflow(data, step, jobFacts)];
  flows.forEach(flow => applySavedProgress(flow, data));
  flows.forEach(flow => flow.steps.forEach(item => {
    item.plan = data.settings?.steps[item.id];
    item.mode = data.settings?.modes[item.id];
    item.customized = data.settings?.customized?.includes(item.id);
    item.poolErrors = workflowRuns(data).flatMap(run => run.pool_errors || []).filter(error => error.step === item.id);
    if (item.poolErrors.length && item.status !== "complete") item.status = "failed";
    applyActivity(item, data, flow.id, startingStep);
  }));
  return flows;
}

function applyActivity(item, data, flow, startingStep) {
  const worker = stepRun(data, item.id);
  const running = Math.max(item.jobs.running || 0, (item.jobs.workers || []).reduce((sum, row) => sum + row.running, 0));
  const requested = !!worker;
  const starting = startingStep === item.id;
  if (!running && !starting && item.status === "complete") return;
  if (!running && !requested && !starting && item.status !== "running") return;
  const plan = worker?.settings?.[item.id] || item.plan;
  const capacity = workerCapacity(plan, item.mode, data.execution?.max_parallel_jobs);
  const label = running ? "Running" : starting ? "Starting step" : stepActivityLabel(worker, item.jobs.retry, item.id);
  item.activity = { running, capacity, label };
  item.jobs.running = running;
  item.status = "running";
}

function workerCapacity(plan, mode, ceiling) {
  if (!plan?.length) return null;
  const total = mode === "single" ? 1 : mode === "sequence" ? Math.max(...plan.map(row => row.workers)) : plan.reduce((sum, row) => sum + row.workers, 0);
  return Math.min(total, ceiling || total);
}

function mappingFlow(data, files) {
  const semantic = data.semantic || {};
  const scopes = data.coverage?.scopes || {};
  const modules = scopes.module || {};
  const total = modules.total == null ? null : modules.total - modules.excluded;
  const taxonomy = semantic.taxonomy || {};
  const groups = scopes.group || {};
  const charter = semantic.architecture_charter;
  const ready = mapReady(modules, total, groups, semantic);
  return { id: "mapping", title: "Build the repository map", name: "Mapping",
    state: !semantic.enabled && !ready ? "not_started" : null,
    description: "From source files to a shared explanation of how this repository works.",
    note: "Checks after every map proposal and revision preserve file coverage and apply grouping rules. Arrows show evidence dependencies; independent file jobs can run together.",
    steps: [
      scanStep(data, files),
      step("annotation", "Annotate the entities", "Save a sentence, a short paragraph and function summaries.", {
        done: data.coverage?.graph?.annotation_current ?? modules.current, total: data.coverage?.graph?.annotation_total ?? total,
        unit: "modules", reused: modules.reused, jobs: jobFacts(data, "annotation"), enabled: semantic.enabled, view: "modules",
        detail: "One compact saved annotation enriches the graph. Compatible results are reused; descriptions and contracts are not copied into a second essay.",
      }),
      step("contracts", "Link interfaces and contracts", "Connect behavior, obligations, consumers and tests.", {
        owner: "AnaxiGraph code", done: data.coverage?.graph?.contracts_ready ? 1 : 0, total: 1, unit: "graph",
        enabled: semantic.enabled, view: "graph", detail: "First-class function, interface and contract nodes keep callers linked to required behavior. Structural readiness and missing semantic obligations remain separate.",
      }),
      ...taxonomySteps(data, taxonomy),
      step("groups", "Describe capabilities", "Explain shared purposes and responsibility boundaries.", {
        done: groups.current, total: groups.total ?? null, unit: "groups", reused: groups.reused,
        jobs: jobFacts(data, "synthesis", "group"), enabled: semantic.enabled, view: "overview",
        detail: "Areas and subsystems receive summaries grounded in their members. Group totals become known once the map is planned.",
      }),
      step("charter", "Prepare the functional brief", "State purpose, capabilities and required behavior.", {
        done: charter?.status === "current" ? 1 : 0, total: 1, unit: "Charter",
        jobs: jobFacts(data, "synthesis", "repository"), enabled: semantic.enabled, view: "overview",
        detail: "The repository summary combines the groups into a Living Architecture Charter, with uncertainties and evidence retained.",
      }),
      step("explore", "Explore the map", "Use the same saved evidence in the dashboard, CLI and MCP.", {
        owner: "AnaxiGraph code", done: ready ? 1 : 0, total: 1, unit: "map", enabled: semantic.enabled, view: "graph",
        detail: "Later scans reuse current documents and refresh work whose inputs changed. Optional reviews are shown in their own flows.",
      }),
    ] };
}

function mapReady(modules, total, groups, semantic) {
  const taxonomy = semantic.taxonomy || {};
  return modules.current === total && semantic.architecture_charter?.status === "current"
    && (!taxonomy.enabled || taxonomy.ready) && groups.current === groups.total;
}

function scanStep(data, files) {
  const scan = data.coverage?.scan || {};
  files = scan.discovered_count ?? files;
  const active = data.scan?.active;
  return step("scan", "Scan the source", "Read symbols, imports and source fingerprints.", {
    owner: "AnaxiGraph code", done: active ? data.scan.completed || 0 : files,
    total: active ? data.scan.total : files, unit: "files", status: active ? "running" : data.snapshot_id ? "complete" : "not_started",
    reused: scan.reused_count, detail: `${scan.analyzed_count || 0} files analyzed and ${scan.reused_count || 0} reused in the saved scan. ${scan.error_count || 0} scan errors.`, view: "modules",
  });
}

function taxonomySteps(data, taxonomy) {
  const map = taxonomy.current;
  return [
    step("taxonomy_proposal", "Propose the map", "Group responsibilities into areas and subsystems.", {
      done: map ? 1 : 0, total: 1, unit: "proposal", jobs: jobFacts(data, "taxonomy_proposal"), enabled: taxonomy.enabled,
      detail: "The proposal uses file descriptions and code relationships. Software validates and repairs assignments before the review begins.", view: "graph",
    }),
    step("taxonomy_review", "Review and revise", "Review batches in parallel, then reconcile the map.", {
      done: map?.stored_reviews || 0, total: taxonomy.required_review_passes ?? null, unit: "passes",
      zeroComplete: !!map, jobs: jobFacts(data, "taxonomy_review"), enabled: taxonomy.enabled,
      reviewProgress: data.coverage?.taxonomy_review,
      detail: map ? `${map.validation?.assigned_modules || 0} files assigned; ${map.validation?.areas || 0} areas and ${map.validation?.subsystems || 0} subsystems. Latest validation: ${map.validation?.repairs || 0} repairs. Repairs preserve coverage; they do not prove grouping accuracy.` : "Each pass receives the current map. The configured taxonomy model applies to the proposal and its reviews.", view: "graph",
    }),
  ];
}

function unplannedState(data, workflow) {
  return workflowRuns(data).some(worker => worker.workflow === workflow && ["running", "queued"].includes(worker.status)) ? "running" : "not_started";
}

function patternFlow(data) {
  const { semantic, catalogue, planned, total, done, assessed, enabled, ready } = patternProgress(data);
  return { id: "patterns", name: "Pattern analysis", title: "Consider the complete pattern catalogue",
    state: planned ? null : unplannedState(data, "patterns"),
    completionLabel: catalogue.unresolved ? `Reviewed · ${catalogue.unresolved} unresolved` : null,
    unresolved: catalogue.unresolved || 0,
    description: "Every catalogue pattern receives contextual ratings, benefits, costs and an independent critique.",
    note: "Missing Mapping prerequisites run first. Each versioned catalogue entry is considered for the whole repository; relevant local placements retain evidence and trade-offs. No source code is changed.",
    steps: [
      step("pattern_evidence", "Gather code evidence", "Use the map, source facts and pattern catalogue.", {
        owner: "AnaxiGraph code", done: semantic.architecture_charter?.status === "current" ? 1 : 0,
        total: 1, unit: "map", view: "overview", detail: "Mapping is a prerequisite. Pattern analysis adds its own detailed assessments while preserving current file descriptions.",
      }),
      step("pattern_plan", "Record catalogue coverage", "Include every entry in the versioned pattern catalogue.", {
        owner: "AnaxiGraph code", done: planned ? 1 : 0, total: 1, unit: "plan", enabled,
        detail: planned ? `${total} catalogue patterns planned. Missing, unresolved and poor-fit outcomes remain distinct.` : "Every catalogue pattern is considered; deterministic signals guide attention without excluding potential opportunities.", view: "patterns",
      }),
      step("pattern_assessment", "Assess the fit", "Weigh evidence, counter-evidence and alternatives.", {
        done: assessed, total, unit: "patterns", zeroComplete: planned, enabled,
        jobs: jobFacts(data, "pattern_assessment"), view: "patterns",
        detail: "Each assessment rates the pattern for this repository and records contextual pros, cons, alternatives and useful placements. A useful pattern need not solve an existing defect.",
      }),
      step("pattern_review", "Review the assessment", "Challenge the proposed fit in a separate model call.", {
        done, total, unit: "patterns", zeroComplete: planned, enabled,
        jobs: jobFacts(data, "pattern_review"), view: "patterns",
        detail: "The reviewer challenges ratings, omissions and trade-offs against the evidence. Unresolved assessments remain visible. A separate call does not necessarily mean a different model or provider.",
      }),
      step("pattern_save", "Save evaluations", "Keep conclusions and reasons, including poor fits.", {
        owner: "AnaxiGraph code", done, total, unit: "evaluations", zeroComplete: planned, enabled,
        detail: "Finalized evaluations retain rationale, alternatives and verification needs. Model confidence is self-reported.", view: "patterns",
      }),
      step("pattern_explore", "Explore the findings", "Compare all patterns, ratings, pros, cons and useful placements.", {
        owner: "You + AnaxiGraph", done: ready ? 1 : 0, total: 1, unit: "review", enabled, view: "patterns",
        detail: "Open Patterns to filter the results and compare approaches. A recommendation never applies a refactor automatically.",
      }),
    ] };
}

function patternProgress(data) {
  const semantic = data.semantic || {};
  const patterns = semantic.patterns || {};
  const scope = data.coverage?.scopes?.pattern || {};
  const catalogue = patterns.catalogue || {};
  const planned = !!patterns.planned;
  return { semantic, catalogue, planned, ...patternCounters(patterns, scope, catalogue, planned) };
}

function patternCounters(patterns, scope, catalogue, planned) {
  const total = planned ? catalogue.expected ?? patterns.selected : null;
  const done = catalogue.reviewed ?? scope.current ?? 0;
  return { total, done, assessed: catalogue.rated ?? Math.max(done, scope.intrinsic || 0),
    enabled: patterns.enabled || planned, ready: catalogue.complete ?? (planned && done === total) };
}

function freshFlow(data) {
  const fresh = data.fresh_eyes || {}, counts = fresh.counts || {};
  const stages = fresh.stages || [];
  const proposals = stages.filter(item => item.key?.includes("proposal"));
  const comparisons = stages.filter(item => item.key?.includes("comparison"));
  const reviews = stages.filter(item => item.key?.includes("review"));
  const ready = fresh.ready === true;
  return { id: "fresh-eyes", name: "Fresh eyes", title: "Design from purpose with fresh eyes",
    description: "Three retained alternatives per functional scope, without seeing the current implementation.",
    note: "Only the functional brief enters this workflow. Actual-code comparison belongs in Architecture Planning. Independent scopes and alternatives can run together and resume from saved results.",
    steps: [
      step("brief", "Read the functional hierarchy", "Use purpose, capabilities, inputs, outputs and constraints.", {
        owner: "AnaxiGraph code", done: fresh.functional_brief || data.semantic?.architecture_charter?.status === "current" ? 1 : 0, total: 1, unit: "brief", view: "fresh-eyes",
        detail: "Source paths, current implementation topology and Pattern judgments are excluded. Each scope identifies its immutable brief revision.",
      }),
      freshStep(data, "adjudication", "Prepare the functional hierarchy", "Extract product, capability and subsystem scopes without implementation topology.", stages.filter(item => item.key === "functional:brief")),
      freshStep(data, "proposals", "Explore three alternatives", "Keep materially different designs at every reviewed scope.", proposals, {
        done: counts.retained_alternatives ?? proposals.filter(item => item.state === "current").length,
        total: counts.expected_alternatives || proposals.length || null, unit: "alternatives", parallel: true,
      }),
      freshStep(data, "comparison", "Compare functional trade-offs", "Rate alternatives against required behavior, never current code.", comparisons),
      freshStep(data, "mission_filter", "Review functionality", "Preserve assumptions, disagreements and composition conflicts.", reviews),
      step("isolation", "Record the blind boundary", "Keep executor isolation and provenance explicit.", {
        owner: "AnaxiGraph code", done: fresh.isolation?.status ? 1 : 0,
        total: 1, unit: "isolation record", view: "fresh-eyes",
        status: ready ? "complete" : undefined,
        detail: `Worker isolation: ${fresh.isolation?.status || "not recorded"}. An unverified context is never presented as verified blindness.`,
      }),
      step("suggestions", "Explore the alternatives", "Inspect each scope and all retained design graphs.", {
        owner: "You + AnaxiGraph", done: counts.completed_scopes || 0, total: counts.total_scopes ?? null,
        unit: "scopes", zeroComplete: ready, view: "fresh-eyes",
        detail: "Selecting a target in Planning does not erase the other Fresh Eyes alternatives.",
      }),
    ] };
}

function freshStep(data, id, title, description, stages, options = {}) {
  const done = stages.filter(item => item.state === "current").length;
  const models = [...new Set(stages.map(item => item.provenance?.executor_model || item.provenance?.model).filter(Boolean))];
  const kind = { proposals: "fresh_proposal", mission_filter: "fresh_review" }[id] || `fresh_${id}`;
  const live = jobFacts(data, kind);
  return step(id, title, description, {
    done, total: stages.length || 1, unit: "result", view: "fresh-eyes", stages,
    jobs: { models, workers: live.workers, errors: live.errors, running: done === stages.length ? 0 : live.running,
      interrupted: live.interrupted, failed: stages.filter(item => item.state?.startsWith("failed")).length,
      pending: stages.filter(item => item.state?.startsWith("pending")).length },
    detail: stages.map(item => item.reason).filter(Boolean).join(" ") || "Waiting for the preceding stage.",
    ...options,
  });
}
