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
      intent: "Put several ways to solve the same problem behind one caller-visible operation.",
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
      what_the_pattern_name_means: "In this result, Strategy means putting several ways to solve the same problem behind one caller-visible operation.",
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
  await page.goto("/#overview");
  await expect(page.locator("#project-name")).not.toHaveText("Loading…");
  await expect(page.locator("main")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".group-family").first()).toBeVisible();
}

test("complete catalogue ratings, full explanations and compatibility diagnostics remain accessible", async ({ page }) => {
  const requests = [];
  await page.route("**/api/patterns**", async route => {
    const url = new URL(route.request().url()), params = url.searchParams;
    requests.push({ path: url.pathname, params });
    if (url.pathname.endsWith("/catalogue")) return route.fulfill({ json: {
      catalogue: { expected: 133, considered: 133, rated: 132, reviewed: 131, unresolved: 2, missing: 1, complete: false, fingerprint: "all-patterns-v2" },
      total: 1, returned: 1, next_offset: null, items: [{ ...patternItem(false), state: "reviewed", pros: ["Preserves a stable caller contract"], cons: ["Can obscure simple selection policy"], placements: [{ target_key: "module:src/anaxigraph/storage.py", reason: "Provider selection can change independently", evidence: ["Three implementations"] }] }],
    } });
    if (url.pathname.endsWith("/candidates")) return route.fulfill({ json: {
      pattern: patternItem(false).pattern, total: 1, returned: 1, next_offset: null,
      items: [candidateItem(params.get("include_evidence") === "true")],
    } });
    return route.fulfill({ json: { total: 1, returned: 1, next_offset: null, items: [patternItem(params.get("include_evidence") === "true")] } });
  });
  await openDashboard(page);
  await page.getByRole("button", { name: "Improve", exact: true }).click();
  await page.getByRole("button", { name: "Patterns", exact: true }).click();
  await expect(page.locator("#pattern-catalogue-counts")).toContainText("Expected 133");
  await expect(page.locator("#pattern-results")).toContainText("Preserves a stable caller contract");
  await expect(page.locator("#pattern-results")).toContainText("Can obscure simple selection policy");
  await page.locator("#pattern-key-filter").fill("strategy");
  await page.locator("#pattern-family-filter").fill("object_interface");
  await page.locator("#pattern-state-filter").selectOption("reviewed");
  await page.locator("#pattern-sort-filter").selectOption("migration_cost");
  await page.getByRole("button", { name: "Show catalogue assessments" }).click();
  await expect.poll(() => requests.at(-1).params.get("family")).toBe("object_interface");
  expect(requests.at(-1).params.get("sort_by")).toBe("migration_cost");
  expect(requests.at(-1).params.get("state")).toBe("reviewed");
  await page.getByRole("button", { name: "Read full saved assessment" }).click();
  await expect(page.locator(".pattern-conclusion")).toContainText("partly follows Strategy");
  await expect(page.locator(".pattern-story-grid")).toContainText("Reasons not to change the code");
  await expect(page.locator(".pattern-score-story section")).toHaveCount(5);
  await expect(page.locator(".pattern-score-story")).toContainText("Evidence that the problem exists 82 out of 100");
  await page.locator(".pattern-details summary").click();
  await expect(page.locator(".pattern-details")).toContainText("Three providers implement the same execution contract");
  expect(requests.at(-1).params.get("include_evidence")).toBe("true");
  await page.getByRole("button", { name: "Explain skipped candidates" }).click();
  await expect(page.locator(".candidate-result-card")).toContainText("Available AI tasks were filled");
  await expect(page.locator(".candidate-result-card .pattern-candidate-rank")).toContainText("not a code grade, pattern fit rating, or recommendation");
  await page.locator(".candidate-result-card .pattern-details summary").click();
  await expect(page.locator(".candidate-result-card .pattern-details")).toContainText("Support for this observation is strong (88 out of 100)");
  await page.getByRole("button", { name: "Look for a completed pattern result" }).click();
  await expect.poll(() => requests.at(-1).path).toBe("/api/patterns/catalogue");
  await expect(page.locator("#pattern-key-filter")).toHaveValue("strategy");
});
