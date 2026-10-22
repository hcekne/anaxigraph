from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from semantic_support import _agent_dossier, _calls, _fake_provider, _semantic_config
from test_understandability import assessment, reader_task

from anaxigraph import semantic_freshness, semantic_runner
from anaxigraph.agent import architecture_guidance
from anaxigraph.architecture_reassessment import architecture_reassessment
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_contract import SemanticResult
from anaxigraph.understanding import SemanticEngine


@pytest.mark.parametrize(
    "contract,expected",
    [
        ("module-intrinsic-v1", "b6eaa6079e92de56c89d95ccbe5934c55d9995018c267d76b61d3b76e3018fc3"),
        ("module-context-v1", "60f0768f31fb4f5ae944e051ebc5873e632e956abe6e5cc89efee055a35ce108"),
        ("group-synthesis-v1", "3507a35e5212988ace4072060a7c9694b43c86a45cfd247463a5882527657fd8"),
        (
            "architecture-charter-v1",
            "4ffcdefb95e8dba3f3b77accc51805ec26caddea69f4c85a91417f7ed4680919",
        ),
        (
            "taxonomy-proposal-v1",
            "384376b7ff93b4b37bed443a186b3d32a93c7de95ffd5570b2c701b83751c97a",
        ),
        ("taxonomy-review-v1", "0243ca54b1834e9ecf47884bc49cdd9d27ee88bcf50496edb24b23629a632806"),
    ],
)
def test_agent_review_policy_preserves_existing_routine_input_hashes(
    contract, expected, monkeypatch
):
    # Golden values evaluated from the actual v0.8.3 implementation, independent of new writing limits.
    evidence = {"path": "pkg/core.py", "detailed_reviews": False}
    assert semantic_freshness.semantic_input_hash(contract, "v1", evidence) == expected
    monkeypatch.setattr(semantic_freshness, "AGENT_REVIEW_POLICY", "Revised agent review")
    assert semantic_freshness.semantic_input_hash(contract, "v1", evidence) == expected


@pytest.mark.parametrize(
    "contract",
    [
        "module-intrinsic-v1",
        "module-context-v1",
        "pattern-plan-v1",
        "pattern-assessment-v1",
        "pattern-independent-review-v1",
        "fresh-eyes-proposal-v1",
        "fresh-eyes-adjudication-v1",
        "fresh-eyes-comparison-v1",
        "fresh-eyes-review-v1",
    ],
)
def test_agent_review_policy_changes_only_relevant_review_identity(contract, monkeypatch):
    evidence = {"detailed_reviews": True}
    before = semantic_freshness.semantic_input_hash(contract, "v1", evidence)
    monkeypatch.setattr(semantic_freshness, "AGENT_REVIEW_POLICY", "Revised agent review")
    assert semantic_freshness.semantic_input_hash(contract, "v1", evidence) != before


def test_policy_change_requeues_unchanged_source_and_then_reuses_it(
    repository, database, tmp_path, monkeypatch
):
    provider, log = _fake_provider(tmp_path), tmp_path / "calls.jsonl"
    _semantic_config(repository, provider, log)
    config = load_config(repository)
    scan = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(scan.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    original_calls = len(_calls(log))
    changed = {**semantic_freshness.UNDERSTANDABILITY_POLICY, "version": "revised-rubric"}
    monkeypatch.setattr(semantic_freshness, "UNDERSTANDABILITY_POLICY", changed)
    plan = engine.plan(scan.repository_id, repository, config)
    assert plan.enqueued > 0
    assert engine.bootstrap(scan.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    assert len(_calls(log)) > original_calls
    assert engine.bootstrap(scan.repository_id, repository, config)["processed"] == 0


class ReaderProvider:
    name = "deterministic-test"

    def analyze(self, request):
        value = _agent_dossier(request)
        if request.get("path") == "pkg/core.py":
            if request["analysis_kind"] == "context":
                value["understandability"] = deepcopy(
                    request["intrinsic_dossier"]["understandability"]
                )
            else:
                clear = "quantity" in request.get("source", "")
                value["understandability"] = assessment(
                    reader_task(status="clear" if clear else "obstructed")
                )
        return SemanticResult(value=value, confidence=0.9, evidence=tuple(value["evidence"]))


def test_scan_guidance_and_reassessment_share_saved_reader_evidence(
    repository, database, tmp_path, monkeypatch
):
    _semantic_config(repository, _fake_provider(tmp_path), tmp_path / "calls.jsonl")
    monkeypatch.setattr(semantic_runner, "create_semantic_provider", lambda _: ReaderProvider())
    config = load_config(repository)
    config = replace(config, agent=replace(config.agent, payload_limit_bytes=100_000))
    first = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    assert engine.bootstrap(first.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    guide = architecture_guidance(
        database,
        repository_id=first.repository_id,
        goal="Change the calculation",
        intent="improve",
        focus="pkg/core.py",
        config=config,
    )
    assert guide["recommendation"]["reader_task"]["key"] == "change-calculation"
    core = repository / "pkg/core.py"
    core.write_text(core.read_text().replace("value", "quantity"))
    second = RepositoryScanner(database).scan(repository)
    assert engine.bootstrap(second.repository_id, repository, config)["semantic"][
        "semantically_ready"
    ]
    result = architecture_reassessment(
        database,
        repository_id=first.repository_id,
        config=config,
        from_snapshot_id=first.snapshot_id,
        target_snapshot_id=second.snapshot_id,
    )
    reader = [
        item for item in result["architectural_effects"] if item["category"] == "understandability"
    ]
    assert len(reader) == 1
    assert reader[0]["classification"] == "improved"
