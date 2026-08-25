import { expect, test } from "@playwright/test";

const scores = {
  applicability: 82,
  suitability: 91,
  conformance: 24,
  opportunity: 88,
  confidence: 86,
  benefit: 84,
  urgency: 62,
  execution_safety: 73,
  migration_cost: 37,
};

function patternItem(includeEvidence) {
  const item = {
    target: {
      key: "module:src/anaxigraph/storage.py",
      level: "module",
      label: "storage.py",
      path: "src/anaxigraph/storage.py",
      qualified_name: "",
    },
    pattern: {
      key: "strategy",
      name: "Strategy",
      family: "object_interface",
      kind: "constructive",
      version: 1,
    },
    candidate: { priority: 81, selection_reasons: ["supporting_evidence"] },
    presence: "partial",
    recommendation: "improve_conformance",
    summary: "The providers already resemble Strategy, but choosing one provider follows an inconsistent rule.",
    rationale: "Several implementations provide the same caller-visible behavior through one shared interface.",
    scores,
    evidence_count: 2,
    counter_evidence_count: 1,
    review: {
      verdict: "approve",
      summary: "The second AI pass found that the chosen code and evidence support the result.",
      confidence: 89,
      issue_counts: {},
      competing_interpretation_count: 0,
    },
    plain_language: {
      version: "pattern-explanation-v2",
      conclusion: "storage.py partly follows Strategy; make the existing design more consistent before adding another abstraction.",
      what_anaxigraph_saw: [
        "storage.py shows some, but not all, of Strategy.",
        "Three providers implement the same execution contract.",
      ],
      why_it_may_matter: "Several implementations provide the same caller-visible behavior.",
      what_to_do: "Fix the smallest inconsistent part without building a second system beside it.",
      reasons_not_to_change_the_code: [
        "An extra abstraction could hide simple policy.",
      ],
      how_to_check: [
        "Preserve provider error behavior.",
        "Run focused tests, scan again, and compare the result.",
      ],
      score_meanings: [
        { label: "Problem and fit", scores: { problem_match: 82, pattern_fit: 91 }, meaning: "The problem match and pattern fit are strong." },
        { label: "What already exists", scores: { current_match: 24 }, meaning: "The current match is weak." },
        { label: "Value and timing", scores: { value_of_change: 88, expected_benefit: 84, urgency: 62 }, meaning: "Expected value is strong, while urgency is mixed." },
        { label: "Difficulty of changing it", scores: { execution_safety: 73, migration_cost: 37 }, meaning: "The change looks reasonably safe with weak migration cost." },
        { label: "Strength of evidence", scores: { evidence_strength: 86 }, meaning: "Evidence is strong; this is not a code-quality grade." },
      ],
      independent_review: "A separate AI pass checked the result and did not require a correction.",
    },
    provenance: {
      provider: "agent",
      model: "runtime-test-model",
      created_at: "2026-08-25T12:00:00+00:00",
    },
  };
  if (includeEvidence) {
    item.details = {
      evidence: ["Three providers implement the same execution contract."],
      counter_evidence: ["The current selector has one repository-specific branch."],
      alternatives: ["adapter"],
      prerequisites: ["Preserve provider error semantics."],
      risks: ["An extra abstraction could hide simple policy."],
      review_issues: [],
    };
  }
  return item;
}

function candidateItem(includeEvidence) {
  const item = {
    target: {
      key: "module:src/anaxigraph/provider.py",
      level: "module",
      label: "provider.py",
      path: "src/anaxigraph/provider.py",
      qualified_name: "",
    },
    selected_for_evaluation: false,
    reason: "sparse_plan_bound",
    priority: 76,
    selection_reasons: ["supporting_evidence", "capabilities_satisfied"],
    missing_evidence: [],
    capability_gaps: [],
    matched_signal_count: 3,
    counter_signal_count: 0,
    plain_language: {
      version: "pattern-candidate-explanation-v2",
      conclusion: "Strategy qualified for provider.py, but higher-ranked work filled the available AI tasks.",
      why_this_pair_was_considered: [
        "The code shows a problem that this pattern is designed to address.",
        "Other repository evidence also supports checking this pattern here.",
      ],
      why_it_was_selected_or_skipped: "The possible match passed the minimum score, but AnaxiGraph keeps only the strongest configured number of AI tasks.",
      what_anaxigraph_found: [
        "AnaxiGraph recorded that several providers share one caller-facing interface. This supports checking the pattern here.",
        "AnaxiGraph found 12 direct links from this file to other files. This may be a problem the pattern can address.",
      ],
      what_anaxigraph_could_not_check: [
        "AnaxiGraph had all information required for this code check.",
      ],
      what_happens_next: "No AI pattern task is created unless the repository evidence or task limit changes.",
      queue_rank: {
        value: 76,
        meaning: "AnaxiGraph gave this possible match a work-order score of 76 out of 100. It only chooses which limited AI tasks run first; it is not a code grade, pattern fit rating, or recommendation.",
      },
    },
  };
  if (includeEvidence) {
    item.details = {
      signals: [{
        role: "supporting",
        feature: "semantic.provider_boundary",
        operator: "present",
        outcome: "matched",
        confidence: 0.88,
        evidence: ["Provider implementations share one behavior boundary."],
        plain_language: {
          version: "pattern-candidate-detail-explanation-v2",
          what_was_checked: "AnaxiGraph checked whether several providers share one caller-facing interface.",
          what_was_found: "The recorded value passed this pattern-library check.",
          how_it_affected_selection: "This supports checking Strategy for this code.",
          evidence_strength: {
            value: 88,
            meaning: "Support for this observation is strong (88 out of 100). This is not a code-quality grade.",
          },
        },
      }],
      capabilities: [{
        fact: "semantic_dossier",
        minimum: "summary",
        best_level: "complete",
        ratio: 1,
        complete: true,
        plain_language: {
          version: "pattern-candidate-detail-explanation-v2",
          conclusion: "AnaxiGraph's code readers supplied enough information about what this code does.",
          required_detail: "This check needs a short explanation of the code's purpose.",
          available_detail: "All relevant code information met that requirement.",
          how_to_use_this: "This evidence was complete enough to use in candidate selection.",
        },
      }],
      semantic_questions: ["Does selection policy vary independently from execution?"],
    };
  }
  return item;
}

async function openDashboard(page) {
  await page.goto("/");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("plain-language pattern results can be explored in both directions", async ({ page }) => {
  const requests = [];
  await page.route("**/api/patterns**", async (route) => {
    const url = new URL(route.request().url());
    requests.push({ path: url.pathname, params: url.searchParams });
    const includeEvidence = url.searchParams.get("include_evidence") === "true";
    if (url.pathname.endsWith("/candidates")) {
      await route.fulfill({
        json: {
          contract_version: "pattern-candidate-query-v1",
          repository_id: 1,
          snapshot_id: 7,
          plan_ready: true,
          pattern: {
            key: "strategy",
            name: "Strategy",
            family: "object_interface",
            kind: "constructive",
            scope_levels: ["module"],
          },
          filters: { selection: url.searchParams.get("selection") || "skipped" },
          targets_considered: 5,
          selected_count: 2,
          skipped_count: 3,
          counts_by_reason: { sparse_plan_bound: 3 },
          total: 1,
          returned: 1,
          offset: 0,
          next_offset: null,
          omitted: 0,
          items: [candidateItem(includeEvidence)],
        },
      });
      return;
    }
    await route.fulfill({
      json: {
        contract_version: "pattern-query-v1",
        repository_id: 1,
        snapshot_id: 7,
        filters: {
          target: url.searchParams.get("target") || "",
          pattern: url.searchParams.get("pattern") || "",
          sort_by: url.searchParams.get("sort_by") || "opportunity",
        },
        total: 1,
        returned: 1,
        offset: 0,
        next_offset: null,
        omitted: 0,
        items: [patternItem(includeEvidence)],
      },
    });
  });

  await openDashboard(page);
  await page.getByRole("button", { name: "Patterns", exact: true }).click();

  await expect(page.locator("#view-patterns")).toBeVisible();
  await expect(page.locator(".pattern-result-card")).toContainText("Strategy");
  await expect(page.locator(".pattern-result-card")).toContainText("Second AI check");
  await expect(page.locator(".pattern-conclusion")).toContainText("partly follows Strategy");
  await expect(page.locator(".pattern-story-grid")).toContainText("What AnaxiGraph saw");
  await expect(page.locator(".pattern-story-grid")).toContainText("Reasons not to change the code");
  await expect(page.locator(".pattern-story-grid")).toContainText("How to check the result");
  await expect(page.locator(".pattern-score-story section")).toHaveCount(5);
  await expect(page.locator(".pattern-score-story")).toContainText("Evidence that the problem exists 82 out of 100");
  await expect(page.locator(".pattern-result-card .pattern-score")).toHaveCount(0);
  await expect(page.locator("#pattern-query-summary")).toContainText(
    "current pattern results that completed a separate AI check",
  );

  await page.locator("#pattern-target-filter").fill("src/anaxigraph/storage.py");
  await page.locator("#patterns-query-form").getByRole("button", {
    name: "Show completed pattern results",
  }).click();
  await expect.poll(() => requests.at(-1).params.get("target")).toBe(
    "src/anaxigraph/storage.py",
  );

  await page.getByRole("button", { name: "Find this pattern elsewhere" }).click();
  await expect(page.locator("#pattern-key-filter")).toHaveValue("strategy");
  await expect(page.locator("#pattern-target-filter")).toHaveValue("");
  await expect.poll(() => requests.at(-1).params.get("pattern")).toBe("strategy");

  await page.locator("#pattern-include-evidence").check();
  await page.locator("#patterns-query-form").getByRole("button", {
    name: "Show completed pattern results",
  }).click();
  await expect(page.locator(".pattern-details")).toContainText("Detailed evidence and changes made by the second AI check");
  await expect(page.locator(".pattern-details")).toContainText(
    "Three providers implement the same execution contract",
  );

  await page.getByRole("button", { name: "Explain skipped candidates" }).click();
  await expect(page.locator("#pattern-mode-filter")).toHaveValue("candidates");
  await expect(page.locator("#pattern-presence-filter")).toBeDisabled();
  await expect.poll(() => requests.at(-1).path).toBe("/api/patterns/candidates");
  await expect.poll(() => requests.at(-1).params.get("selection")).toBe("skipped");
  await expect(page.locator(".candidate-result-card")).toContainText("Available AI tasks were filled");
  await expect(page.locator(".candidate-result-card .pattern-conclusion")).toContainText(
    "higher-ranked work filled the available AI tasks",
  );
  await expect(page.locator(".candidate-result-card")).toContainText(
    "Why AnaxiGraph considered this pair",
  );
  await expect(page.locator(".candidate-result-card")).toContainText(
    "What AnaxiGraph could not check",
  );
  await expect(page.locator(".candidate-result-card .pattern-candidate-rank")).toContainText(
    "not a code grade, pattern fit rating, or recommendation",
  );
  await expect(page.locator(".candidate-result-card .pattern-details")).toContainText(
    "Does selection policy vary independently from execution",
  );
  await expect(page.locator(".candidate-result-card .pattern-details")).toContainText(
    "How AnaxiGraph checked this evidence",
  );
  await expect(page.locator(".candidate-result-card .pattern-details")).toContainText(
    "Support for this observation is strong (88 out of 100)",
  );
  await expect(page.locator(".candidate-result-card .pattern-details")).not.toContainText("/100");

  await page.getByRole("button", { name: "Look for a completed pattern result" }).click();
  await expect(page.locator("#pattern-mode-filter")).toHaveValue("evaluations");
  await expect.poll(() => requests.at(-1).path).toBe("/api/patterns");
  await expect.poll(() => requests.at(-1).params.get("target")).toBe(
    "module:src/anaxigraph/provider.py",
  );
});
