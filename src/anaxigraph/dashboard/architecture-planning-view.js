import { api, byId, escapeHtml, request, state, toast } from "/assets/dashboard-core.js";
import { architectureDiagram } from "/assets/architecture-plan-diagram.js";

let loadedKey = "", full = null, loading = false;
let directionRepository = null;

export function planningDirection() {
  return byId("architecture-direction")?.value.trim() || "";
}

export function renderArchitecturePlanning(data, flow) {
  let panel = byId("architecture-planning-panel");
  if (!panel) {
    panel = document.createElement("section");
    panel.id = "architecture-planning-panel";
    panel.className = "architecture-planning panel";
    byId("workflow-diagram").after(panel);
    panel.addEventListener("click", event => void action(event));
    panel.innerHTML = `<h3>Architecture direction <small>optional</small></h3><p>Leave this blank and the agent will choose a justified target. You can change its choice later.</p><label for="architecture-direction">What should the architecture help achieve?</label><textarea id="architecture-direction" rows="3" maxlength="4000" placeholder="Use the suggested direction and let the agent choose"></textarea><div class="planning-suggestions"><button class="secondary-button" type="button" data-plan-suggest="">Let the agent choose</button><button class="secondary-button" type="button" data-plan-suggest="Preserve behavior, strengthen existing boundaries and improve testability with small reversible changes.">Evolve existing boundaries</button><button class="secondary-button" type="button" data-plan-suggest="Reduce evidenced duplication and operational complexity while preserving existing contracts.">Simplify the architecture</button></div><p class="muted" id="planning-evidence"></p><div id="architecture-plan-results"></div><button class="secondary-button" type="button" data-record-save>Save shared architecture files</button><p class="muted">Writes the Git-ready anaxigraph/ record. Your normal Git workflow publishes it.</p>`;
    byId("architecture-direction").addEventListener("input", () => window.dispatchEvent(new CustomEvent("anaxigraph:planningdirection")));
  }
  panel.hidden = flow !== "architecture";
  if (directionRepository !== data.repository_id) {
    directionRepository = data.repository_id;
    loadedKey = "";
    full = null;
    byId("architecture-plan-results").innerHTML = "";
    byId("architecture-direction").value = data.architecture_plan?.user_direction || "";
  }
  if (panel.hidden) return;
  byId("planning-evidence").textContent = `Inputs: Mapping ${data.semantic?.architecture_charter?.status || "not ready"} · Patterns ${data.semantic?.patterns?.planned ? "available" : "not run"} · Fresh Eyes ${String(data.fresh_eyes?.state || "not run").replaceAll("_", " ")}. Available reviews contribute; missing reviews do not prevent planning.`;
  const plan = data.architecture_plan || {};
  const key = JSON.stringify([data.repository_id, plan.provenance?.created_at, plan.selected_option, plan.progress, plan.state]);
  if (loadedKey === key || loading) return;
  loading = true;
  const repositoryId = state.repositoryId;
  void request(api("/api/architecture-plan", { details: "true" })).then(value => {
    if (repositoryId !== state.repositoryId) return;
    full = value;
    loadedKey = key;
    byId("architecture-plan-results").innerHTML = planMarkup(value);
  }).catch(error => toast(error.message, true)).finally(() => {
    loading = false;
    if (repositoryId !== state.repositoryId) loadedKey = "";
  });
}

function planMarkup(plan) {
  if (!plan.value) return `<p>No target has been saved yet. Run full architecture planning to compare options and let an agent choose.</p>`;
  const target = plan.target, diagrams = plan.diagrams;
  return `<h3>${escapeHtml(plan.summary)}</h3><p><strong>${plan.state === "current" ? "Current plan" : "Based on an earlier scan — inspect changed source"}</strong> · ${escapeHtml(plan.selection_source)} selection</p><p>${escapeHtml(plan.selection_rationale)}</p><div class="architecture-options">${plan.value.options.map(option => `<article class="${option.key === plan.selected_option ? "selected" : ""}"><h4>${escapeHtml(option.title)}</h4><p>${escapeHtml(option.summary)}</p><p><strong>Costs:</strong> ${escapeHtml(option.costs.join("; ") || "None identified")}</p><p><strong>Risks:</strong> ${escapeHtml(option.risks.join("; ") || "None identified")}</p><button class="secondary-button" type="button" data-plan-option="${escapeHtml(option.key)}" ${option.key === plan.selected_option ? "disabled" : ""}>${option.key === plan.selected_option ? "Selected target" : "Choose this target"}</button></article>`).join("")}</div><div class="architecture-comparison">${architectureDiagram(diagrams.current, "current", diagrams.changes)}${architectureDiagram(diagrams.target, "target", diagrams.changes)}</div><details><summary>Mermaid diagram exports</summary><pre>${escapeHtml(diagrams.current_mermaid + "\n" + diagrams.target_mermaid)}</pre></details><h3>Migration milestones</h3><ol class="architecture-milestones">${target.milestones.map(item => `<li><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.outcome)}</p><p>Owners: ${escapeHtml(item.owners.join(", "))}</p><p>Verify: ${escapeHtml(item.verification.join("; "))}</p><p>Status: ${escapeHtml(plan.progress[item.key]?.status || "pending")}${plan.progress[item.key]?.reported_by ? ` (reported by ${escapeHtml(plan.progress[item.key].reported_by)})` : ""}</p><button class="secondary-button" type="button" data-plan-milestone="${escapeHtml(item.key)}">Copy agent task</button></li>`).join("") || "<li>Preserve the current design; no migration is proposed.</li>"}</ol>`;
}

async function action(event) {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    if (button.dataset.planSuggest != null) {
      byId("architecture-direction").value = button.dataset.planSuggest;
      byId("architecture-direction").dispatchEvent(new Event("input"));
    } else if (button.dataset.planOption) {
      full = await request("/api/architecture-plan", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ repository_id: state.repositoryId, option: button.dataset.planOption, details: true }) });
      loadedKey = "";
      byId("architecture-plan-results").innerHTML = planMarkup(full);
    } else if (button.dataset.planMilestone) {
      const item = full.target.milestones.find(item => item.key === button.dataset.planMilestone);
      await navigator.clipboard.writeText(`Use AnaxiGraph architecture target “${full.target.title}”. Implement milestone “${item.title}”: ${item.outcome}\nOwners: ${item.owners.join(", ")}\nPreserve: ${item.affected_contracts.join(", ")}\nVerify: ${item.verification.join("; ")}\nRollback: ${item.rollback}\nRefresh the map and reassess against pre-edit snapshot ${full.snapshot_id}. Report the actual verification evidence with ANAXIGRAPH_GUIDE(intent="plan", milestone="${item.key}", milestone_status="verified", verification_evidence=[...]).`);
      toast("Agent task copied.");
    } else if (button.dataset.recordSave != null) {
      const result = await request(api("/api/record/save"), { method: "POST" });
      toast(`Saved shared architecture files · ${result.changed_files} changed files.`);
    }
  } catch (error) { toast(error.message, true); }
}
