from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_primary_onboarding_leads_with_the_four_step_agent_funded_path():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    onboarding = (ROOT / "docs/onboarding.md").read_text(encoding="utf-8")
    required = (
        "uvx anaxigraph up . --open --semantic agent --connect codex",
        "http://127.0.0.1:8765",
        "own",
        "build or resume the AI-created code map",
    )

    assert readme.index("## 🚀 Start in four steps") < readme.index("## 🐳 Durable Docker sidecar")
    assert onboarding.index("### 1. Start it") < onboarding.index("### 4. Ask the agent")
    for document in (readme, onboarding):
        assert all(value in document for value in required)
        assert "no model key" in document.lower()


def test_advanced_modes_are_routed_out_of_the_primary_path():
    onboarding = (ROOT / "docs/onboarding.md").read_text(encoding="utf-8")
    advanced = (ROOT / "docs/advanced-operations.md").read_text(encoding="utf-8")

    for detail in (
        'export OPENAI_API_KEY="..."',
        "ssh -L 8765:127.0.0.1:8765",
        "backend/coverage.xml",
        "repositories.example.yml",
        "anaxigraph history /path/to/repository --cancel",
    ):
        assert detail not in onboarding
        assert detail in advanced
    assert "[Advanced operation](advanced-operations.md)" in onboarding


def test_primary_docs_share_one_ordered_before_and_after_coding_loop():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    onboarding = (ROOT / "docs/onboarding.md").read_text(encoding="utf-8")
    ordered_steps = (
        "ANAXIGRAPH_SCOPE",
        "post_change_baseline",
        "ANAXIGRAPH_IMPACT",
        "ANAXIGRAPH_SCAN",
        "verification_baseline",
        "post_change_comparison",
    )

    for document in (readme, onboarding):
        positions = [
            document.index(step, document.index("Use one coding loop")) for step in ordered_steps
        ]
        assert positions == sorted(positions)
        assert "A difference is not automatically an improvement" in document or (
            "does not call a difference an improvement" in document
        )
