// Display saved coverage separately from the jobs that produced it.
export const statusLabels = {
  complete: "Complete", running: "Running", queued: "Queued", failed: "Needs attention",
  interrupted: "Worker stopped", waiting: "Waiting", not_started: "Not run", skipped: "Not enabled",
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
    : jobs.failed ? "failed" : jobs.interrupted ? "interrupted"
      : jobs.pending || jobs.retry ? "queued" : done ? "waiting"
        : enabled ? "not_started" : "skipped";
  return { id, title, description, jobs, unit: "results", owner: "AI worker", ...options,
    done: Number(done || 0), total, status: options.status || status };
}

export function flowState(steps) {
  return ["running", "failed", "interrupted", "queued", "waiting"]
    .find(status => steps.some(item => item.status === status))
    || (steps.every(item => ["complete", "skipped"].includes(item.status)) ? "complete" : "not_started");
}

export function workflowState(flow) {
  return flow.state || flowState(flow.steps);
}

export function buildFlows(data, files = 0) {
  const flows = [mappingFlow(data, files), patternFlow(data), freshFlow(data)];
  flows.forEach(flow => flow.steps.forEach(item => {
    item.plan = data.settings?.steps[item.id];
    item.mode = data.settings?.modes[item.id];
    item.customized = data.settings?.customized.includes(item.id);
  }));
  return flows;
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
      step("intrinsic", "Describe each file", "Explain purpose, responsibilities and contracts.", {
        done: modules.intrinsic, total, unit: "files", reused: modules.intrinsic_reused,
        jobs: jobFacts(data, "intrinsic"), enabled: semantic.enabled, view: "modules",
        detail: "Each description starts with the file's own source. Reused descriptions count toward coverage without another model call.",
      }),
      step("context", "Add context", "Connect each file to its code neighbours.", {
        done: modules.current, total, unit: "files", reused: modules.reused,
        jobs: jobFacts(data, "context"), enabled: semantic.enabled, view: "modules",
        detail: "The worker receives the intrinsic description, dependency links and nearby descriptions. This stage explains how the file fits into the repository.",
      }),
      ...taxonomySteps(data, taxonomy),
      step("groups", "Summarize groups", "Combine member descriptions into shared responsibilities.", {
        done: groups.current, total: groups.total ?? null, unit: "groups", reused: groups.reused,
        jobs: jobFacts(data, "synthesis", "group"), enabled: semantic.enabled, view: "overview",
        detail: "Areas and subsystems receive summaries grounded in their members. Group totals become known once the map is planned.",
      }),
      step("charter", "Write the Charter", "Explain repository purpose, capabilities and architecture.", {
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
    step("taxonomy_review", "Review and revise", "Critique the map, then check every revised assignment.", {
      done: map?.stored_reviews || 0, total: taxonomy.required_review_passes ?? null, unit: "passes",
      zeroComplete: !!map, jobs: jobFacts(data, "taxonomy_review"), enabled: taxonomy.enabled,
      detail: map ? `${map.validation?.assigned_modules || 0} files assigned; ${map.validation?.areas || 0} areas and ${map.validation?.subsystems || 0} subsystems. Latest validation: ${map.validation?.repairs || 0} repairs. Repairs preserve coverage; they do not prove grouping accuracy.` : "Each pass receives the current map. The configured taxonomy model applies to the proposal and its reviews.", view: "graph",
    }),
  ];
}

function unplannedState(worker, workflow) {
  return worker?.workflow === workflow && ["running", "queued"].includes(worker.status) ? "running" : "not_started";
}

function patternFlow(data) {
  const semantic = data.semantic || {};
  const patterns = semantic.patterns || {};
  const scope = data.coverage?.scopes?.pattern || {};
  const planned = !!patterns.planned;
  const total = planned ? patterns.selected : null;
  const done = scope.current || 0;
  const assessed = Math.max(done, scope.intrinsic || 0);
  const enabled = patterns.enabled || planned;
  const ready = planned && done === total;
  return { id: "patterns", name: "Pattern analysis", title: "Find patterns that fit the code",
    state: planned ? null : unplannedState(semantic.worker, "patterns"),
    description: "A focused assessment of candidate patterns, followed by an independent critique.",
    note: "Complete Mapping first, then assess patterns against the saved map. Counts here are candidate–target pairs, not unique files. No source code is changed.",
    steps: [
      step("pattern_evidence", "Gather code evidence", "Use the map, source facts and pattern catalogue.", {
        owner: "AnaxiGraph code", done: semantic.architecture_charter?.status === "current" ? 1 : 0,
        total: 1, unit: "map", view: "overview", detail: "Mapping is a prerequisite. Pattern analysis adds its own detailed assessments while preserving current file descriptions.",
      }),
      step("pattern_plan", "Select candidates", "Match supported signals to bounded code targets.", {
        owner: "AnaxiGraph code", done: planned ? 1 : 0, total: 1, unit: "plan", enabled,
        detail: planned ? `${total} candidate–target pairs selected. An empty selection is a completed analysis, not missing work.` : "Deterministic selection avoids asking a model about every pattern for every file.", view: "patterns",
      }),
      step("pattern_assessment", "Assess the fit", "Weigh evidence, counter-evidence and alternatives.", {
        done: assessed, total, unit: "pairs", zeroComplete: planned, enabled,
        jobs: jobFacts(data, "pattern_assessment"), view: "patterns",
        detail: "Each assessment explains whether a pattern helps this target, which behaviour must survive and what remains uncertain.",
      }),
      step("pattern_review", "Review the assessment", "Challenge the proposed fit in a separate model call.", {
        done, total, unit: "pairs", zeroComplete: planned, enabled,
        jobs: jobFacts(data, "pattern_review"), view: "patterns",
        detail: "The reviewer receives the assessment and its evidence. A separate call does not necessarily mean a different model or provider.",
      }),
      step("pattern_save", "Save evaluations", "Keep conclusions and reasons, including poor fits.", {
        owner: "AnaxiGraph code", done, total, unit: "evaluations", zeroComplete: planned, enabled,
        detail: "Finalized evaluations retain rationale, alternatives and verification needs. Model confidence is self-reported.", view: "patterns",
      }),
      step("pattern_explore", "Explore the findings", "Compare candidates and inspect the relevant code.", {
        owner: "You + AnaxiGraph", done: ready ? 1 : 0, total: 1, unit: "review", enabled, view: "patterns",
        detail: "Open Patterns to filter the results and compare approaches. A recommendation never applies a refactor automatically.",
      }),
    ] };
}

function freshFlow(data) {
  const fresh = data.fresh_eyes || {};
  const stages = fresh.stages || [];
  const proposals = stages.filter(item => item.key.startsWith("proposal:"));
  const count = data.settings?.steps.proposals?.length || 2;
  const candidates = proposals.length ? proposals : Array.from({ length: count }, (_, index) => ({ key: `proposal:${String.fromCharCode(97 + index)}` }));
  const ready = fresh.ready;
  return { id: "fresh-eyes", name: "Fresh eyes", title: "Reconsider the architecture with fresh eyes",
    description: "Independent designs become a reference, then meet the realities of your repository.",
    note: "Proposals see the capability brief, not the current implementation or each other's answers. Later stages compare with current code. Provider diversity is shown only when recorded.",
    steps: [
      step("brief", "Frame the capabilities", "Start from the Charter's purpose and constraints.", {
        owner: "AnaxiGraph code", done: fresh.capability_brief ? 1 : 0, total: 1, unit: "brief",
        detail: "The capability brief defines what the software needs to do without giving the proposal writers its existing implementation.", view: "overview",
      }),
      freshStep(data, "proposals", "Independent proposals", "Separate sessions propose an architecture from the same brief.", candidates, {
        unit: "proposals", parallel: true, detail: "Each proposal is produced independently. More proposals add work; model or provider diversity depends on the executors that actually run them.",
      }),
      freshStep(data, "adjudication", "Build a reference design", "Compare proposals and preserve useful disagreements.", stages.filter(item => item.key === "adjudication")),
      freshStep(data, "comparison", "Compare with reality", "Now inspect current architecture and declared context.", stages.filter(item => item.key === "comparison")),
      freshStep(data, "mission_filter", "Rank useful changes", "Filter suggestions against the mission and review goal.", stages.filter(item => item.key === "review")),
      step("grounding", "Check the references", "Resolve cited paths and symbols against saved code.", {
        owner: "AnaxiGraph code", done: ready ? 1 : 0, total: 1, unit: "check",
        detail: "Resolved references show that cited code exists. They do not prove a recommendation correct or behaviour verified.", view: "fresh-eyes",
      }),
      step("suggestions", "Explore the suggestions", "Read evidence, trade-offs and the smallest proposed change.", {
        owner: "You + AnaxiGraph", done: ready ? fresh.recommendations?.length || 0 : 0,
        total: ready ? fresh.recommendations?.length || 0 : null, unit: "suggestions", zeroComplete: ready,
        detail: fresh.next_action || "Suggestions are saved for review; this workflow does not change source files.", view: "fresh-eyes",
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
    jobs: { models, workers: live.workers, running: done === stages.length ? 0 : live.running,
      interrupted: live.interrupted, failed: stages.filter(item => item.state?.startsWith("failed")).length,
      pending: stages.filter(item => item.state?.startsWith("pending")).length },
    detail: stages.map(item => item.reason).filter(Boolean).join(" ") || "Waiting for the preceding stage.",
    ...options,
  });
}
