"""Real application scenarios across indexing, persistence and analysis contracts."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from anaxigraph.application import Application


@pytest.fixture
def app(tmp_path: Path) -> Application:
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "service.py").write_text(
        "from persistence import save\n"
        "# PRIVATE_SOURCE_SENTINEL\n"
        "def validate(invoice):\n    return bool(invoice)\n"
        "class InvoiceService:\n"
        "    def create(self, invoice):\n"
        "        if validate(invoice):\n            return save(invoice)\n"
    )
    (root / "persistence.py").write_text("def save(invoice):\n    return {'id': 1, **invoice}\n")
    application = Application(root, tmp_path / "knowledge.sqlite")
    application.scan()
    return application


def annotation_result(request: dict) -> dict:
    behavior = {
        "service.py": "Create valid invoices for the authenticated tenant.",
        "persistence.py": "Persist invoice state and return its assigned identity.",
    }
    annotations = []
    for module in request["packet"]["modules"]:
        annotations.append(
            {
                "node_id": module["id"],
                "overview": f"Provides invoice behavior for {module['path']}.",
                "detail": "Keeps its invoice responsibility available through a narrow public interface.",
                "capabilities": [behavior[module["path"]]],
                "functions": [
                    {"node_id": node["id"], "overview": "Performs its invoice operation."}
                    for node in request["packet"]["functions"]
                    if node["path"] == module["path"]
                ],
                "contracts": [
                    {
                        "statement": "Preserve tenant isolation.",
                        "basis": "inferred",
                        "evidence": [{"path": module["path"], "line": 1}],
                    }
                ],
                "uncertainty": ["Runtime persistence failure behavior has not been checked."],
            }
        )
    return {"producer": "fixture-agent/fixture-model", "annotations": annotations}


def annotate(app: Application, scope: list[str] | None = None) -> tuple[dict, dict]:
    request = app.analysis_request("annotate", scope or ["service.py", "persistence.py"])
    result = annotation_result(request)
    app.submit_analysis(request["request_id"], result)
    return request, result


def pattern_result(request: dict) -> dict:
    return {
        "producer": "fixture-agent/fixture-model",
        "evaluations": [
            {
                "module_id": module["id"],
                "pattern_id": card["id"],
                "opportunity": None,
                "pros": ["A separate owner might contain independently changing behavior."],
                "cons": ["Evidence is insufficient to justify another abstraction."],
                "alternative": "Keep the operation local until a concrete variation is required.",
                "evidence": [],
            }
            for module in request["packet"]["modules"]
            for card in request["packet"]["catalogue"]
        ],
    }


def fresh_result(request: dict) -> dict:
    requirements = [item["id"] for item in request["packet"]["requirements"]]
    return {
        "producer": "fixture-agent/fixture-model",
        "alternatives": [
            {
                "name": name,
                "design": explanation,
                "requirements": requirements.copy(),
                "pros": ["Keeps behavior ownership understandable."],
                "cons": ["Requires validating the proposed failure boundary."],
                "diagram": f"flowchart TB\n    Client --> {component}\n    {component} --> State",
            }
            for name, explanation, component in (
                ("Small local service", "Validate and persist in one focused process.", "Service"),
                (
                    "Queued processing",
                    "Accept commands and persist through an asynchronous consumer.",
                    "Queue",
                ),
                (
                    "Functional operations",
                    "Use a pure invoice transform and a narrow persistence boundary.",
                    "Transform",
                ),
            )
        ],
    }


def test_scan_and_annotation_request_survive_application_restart(app: Application) -> None:
    assert app.status()["annotations"] == {"current": 0, "stale": 0, "missing": 2}
    request = app.analysis_request("annotate", ["service.py"])
    assert len(request["packet"]["functions"]) == 2
    restarted = Application(app.root, app.store.path)
    assert restarted.status()["snapshot"]["id"] == app.status()["snapshot"]["id"]
    saved = restarted.submit_analysis(request["request_id"], annotation_result(request))
    assert saved["saved"] is True
    assert restarted.status()["annotations"] == {"current": 1, "stale": 0, "missing": 1}
    function = next(node for node in request["packet"]["functions"] if node["name"] == "create")
    detail = restarted.inspect(function["id"])["entity"]["data"]
    assert detail["overview"] == "Performs its invoice operation."
    assert detail["annotation_status"] == "current"


def test_cached_reads_notice_another_application_annotation(app: Application) -> None:
    assert "annotation" not in app.inspect("service.py")["entity"]["data"]
    other = Application(app.root, app.store.path)
    annotate(other, ["service.py"])
    assert app.inspect("service.py")["entity"]["data"]["annotation_status"] == "current"
    assert app.status()["annotations"]["current"] == 1


def test_inventory_pages_fit_budget_and_expose_next_offset(app: Application) -> None:
    for number in range(40):
        (app.root / f"invoice_operation_{number:03}.py").write_text("def run():\n    return 1\n")
    app.scan()
    first = app.modules(limit=100)
    assert len(json.dumps(first).encode()) <= 8000
    assert first["total"] == 42
    assert first["next_offset"] == len(first["items"])
    second = app.modules(limit=100, offset=first["next_offset"])
    assert not {n["id"] for n in first["items"]} & {n["id"] for n in second["items"]}


def test_module_graph_projects_symbol_references_with_original_evidence(app: Application) -> None:
    detail = app.inspect("persistence.py")
    incoming = [edge for edge in detail["incoming"] if edge["source"] == "module:service.py"]
    assert incoming
    assert all(
        edge["projected_from"]["target"].startswith("symbol:persistence.py") for edge in incoming
    )
    assert all(edge["path"] == "service.py" for edge in incoming)
    assert detail["projection"] == "module rollup of observed symbol references"


def test_old_same_snapshot_annotation_cannot_overwrite_newer_result(app: Application) -> None:
    first, first_result = annotate(app, ["service.py"])
    app.submit_analysis(first["request_id"], first_result)  # exact retry is idempotent
    second = app.analysis_request("annotate", ["service.py"])
    newer = annotation_result(second)
    newer["annotations"][0]["overview"] = "A corrected invoice responsibility."
    app.submit_analysis(second["request_id"], newer)
    with pytest.raises(ValueError, match="newer result|inputs changed"):
        app.submit_analysis(first["request_id"], first_result)
    assert (
        app.inspect("service.py")["entity"]["data"]["annotation"]["overview"]
        == "A corrected invoice responsibility."
    )


def test_changed_semantics_invalidate_pending_blind_review(app: Application) -> None:
    annotate(app)
    blind = app.analysis_request("fresh-eyes")
    revised = app.analysis_request("annotate", ["service.py"])
    result = annotation_result(revised)
    result["annotations"][0]["capabilities"] = ["Create and validate tenant-scoped invoice drafts."]
    app.submit_analysis(revised["request_id"], result)
    with pytest.raises(ValueError, match="inputs changed"):
        app.submit_analysis(blind["request_id"], fresh_result(blind))


def test_saved_review_freshness_tracks_semantic_inputs(app: Application) -> None:
    annotate(app)
    request = app.analysis_request("fresh-eyes")
    app.submit_analysis(request["request_id"], fresh_result(request))
    assert app.reviews()["items"][0]["status"] == "current"
    revised = app.analysis_request("annotate", ["service.py"])
    result = annotation_result(revised)
    result["annotations"][0]["capabilities"] = [
        "Create tenant invoices with explicit draft states."
    ]
    app.submit_analysis(revised["request_id"], result)
    assert app.reviews()["items"][0]["status"] == "stale"
    detail = app.inspect("review:" + request["request_id"])["entity"]["data"]
    assert detail["status"] == "stale"
    assert len(detail["result"]["result"]["alternatives"]) == 3


def test_evidence_uses_physical_lines_not_code_line_count(app: Application) -> None:
    path = app.root / "persistence.py"
    path.write_text("# preface\n\n\n\ndef save(invoice):\n    return invoice\n")
    app.scan()
    request = app.analysis_request("annotate", ["persistence.py"])
    result = annotation_result(request)
    result["annotations"][0]["contracts"][0]["evidence"][0]["line"] = 6
    assert app.submit_analysis(request["request_id"], result)["saved"]


def test_dependency_edits_invalidate_unchanged_caller_annotation(app: Application) -> None:
    annotate(app)
    assert app.status()["annotations"]["current"] == 2
    previous = app.status()["snapshot"]["id"]
    path = app.root / "persistence.py"
    path.write_text(path.read_text() + "\n# Persistence guarantee changed.\n")
    app.scan()
    status = app.status()
    assert status["snapshot"]["id"] != previous
    assert status["annotations"] == {"current": 0, "stale": 2, "missing": 0}
    modules = {node["path"]: node for node in app.modules()["items"]}
    assert modules["service.py"]["data"]["annotation_status"] == "stale"
    assert modules["persistence.py"]["data"]["annotation_status"] == "stale"
    brief = app.prepare_change("invoice")
    assert brief["contracts"]
    assert all(contract["annotation_status"] == "stale" for contract in brief["contracts"])
    with pytest.raises(ValueError, match="current behavior|missing/stale"):
        app.analysis_request("fresh-eyes")
    comparison = app.validate_change()
    assert comparison["base_snapshot_id"] == previous
    assert comparison["changed_paths"] == ["persistence.py"]


def test_symbol_lookup_finds_its_existing_responsibility_owner(app: Application) -> None:
    brief = app.prepare_change("save")
    assert any(owner["path"] == "persistence.py" for owner in brief["likely_owners"])


def test_unscanned_edits_reject_analysis_and_validation(app: Application) -> None:
    request = app.analysis_request("annotate", ["service.py"])
    source = app.root / "service.py"
    source.write_text(source.read_text() + "\n# Concurrent edit\n")
    with pytest.raises(ValueError, match="changed after mapping"):
        app.submit_analysis(request["request_id"], annotation_result(request))
    with pytest.raises(ValueError, match="changed after mapping"):
        app.validate_change()
    assert app.status()["annotations"]["current"] == 0
    app.scan()
    with pytest.raises(ValueError, match="stale snapshot"):
        app.submit_analysis(request["request_id"], annotation_result(request))


def test_annotation_coverage_is_complete_before_any_module_is_saved(app: Application) -> None:
    request = app.analysis_request("annotate", ["service.py", "persistence.py"])
    result = annotation_result(request)
    result["annotations"][-1]["functions"] = []
    with pytest.raises(ValueError, match="Every supplied function"):
        app.submit_analysis(request["request_id"], result)
    assert app.status()["annotations"]["current"] == 0
    app.submit_analysis(request["request_id"], annotation_result(request))
    assert app.status()["annotations"]["current"] == 2


def test_every_catalogue_card_is_accounted_for_every_selected_module(app: Application) -> None:
    request = app.analysis_request("patterns", ["service.py", "persistence.py"])
    assert len(request["packet"]["catalogue"]) == 133
    result = pattern_result(request)
    assert len(result["evaluations"]) == 266
    with pytest.raises(ValueError, match="exactly once"):
        app.submit_analysis(
            request["request_id"], result | {"evaluations": result["evaluations"][:-1]}
        )
    duplicate = copy.deepcopy(result)
    duplicate["evaluations"][-1] = duplicate["evaluations"][0]
    with pytest.raises(ValueError, match="duplicate|missing"):
        app.submit_analysis(request["request_id"], duplicate)
    app.submit_analysis(request["request_id"], result)
    reviews = Application(app.root, app.store.path).reviews("patterns")
    assert reviews["total"] == 1
    assert reviews["items"][0]["producer"] == result["producer"]


def test_fresh_eyes_packet_is_blind_and_keeps_all_behavior_requirements(app: Application) -> None:
    annotate(app)
    request = app.analysis_request("fresh-eyes")
    assert set(request) == {"request_id", "kind", "packet", "response_schema"}
    packet = json.dumps(request)
    for implementation_detail in (
        str(app.root),
        "service.py",
        "persistence.py",
        "module:",
        "symbol:",
        "PRIVATE_SOURCE_SENTINEL",
    ):
        assert implementation_detail not in packet
    requirements = request["packet"]["requirements"]
    assert len(requirements) == 4  # Two capabilities and both behavioral obligations.
    assert any("Create valid invoices" in item["behavior"] for item in requirements)
    assert any("Persist invoice state" in item["behavior"] for item in requirements)
    result = fresh_result(request)
    incomplete = copy.deepcopy(result)
    incomplete["alternatives"][2]["requirements"].pop()
    with pytest.raises(ValueError, match="every requirement"):
        app.submit_analysis(request["request_id"], incomplete)
    with pytest.raises(ValueError, match="three alternatives"):
        app.submit_analysis(
            request["request_id"], result | {"alternatives": result["alternatives"][:2]}
        )
    app.submit_analysis(request["request_id"], result)
    assert app.reviews("fresh-eyes")["total"] == 1
    restored = Application(app.root, app.store.path)
    detail = restored.inspect("review:" + request["request_id"])["entity"]
    assert detail["kind"] == "review"
    assert detail["data"]["status"] == "current"
    assert detail["data"]["result"]["result"] == result


@pytest.mark.parametrize("field", ["capabilities", "contracts"])
def test_fresh_eyes_rejects_source_path_leakage_in_functional_statements(
    app: Application, field: str
) -> None:
    request = app.analysis_request("annotate", ["service.py", "persistence.py"])
    result = annotation_result(request)
    if field == "capabilities":
        result["annotations"][0][field] = ["Use service.py to create invoices."]
    else:
        result["annotations"][0][field][0]["statement"] = "Preserve service.py internal behavior."
    app.submit_analysis(request["request_id"], result)
    with pytest.raises(
        ValueError, match="(?i)path|implementation|blind|functional|source identity"
    ):
        app.analysis_request("fresh-eyes")


@pytest.mark.parametrize(
    "malformation", ["module-id", "function-id", "evidence-path", "evidence-line"]
)
def test_malformed_annotation_results_fail_as_caller_errors(
    app: Application, malformation: str
) -> None:
    request = app.analysis_request("annotate", ["service.py"])
    result = annotation_result(request)
    annotation = result["annotations"][0]
    if malformation == "module-id":
        annotation["node_id"] = []
    elif malformation == "function-id":
        annotation["functions"][0]["node_id"] = []
    elif malformation == "evidence-path":
        annotation["contracts"][0]["evidence"][0]["path"] = []
    else:
        annotation["contracts"][0]["evidence"][0]["line"] = 999_999
    with pytest.raises(ValueError):
        app.submit_analysis(request["request_id"], result)
    assert app.status()["annotations"]["current"] == 0


def test_pattern_ids_must_be_strings_and_positive_scores_need_evidence(app: Application) -> None:
    request = app.analysis_request("patterns", ["service.py"])
    result = pattern_result(request)
    del result["evaluations"][0]["opportunity"]
    with pytest.raises(ValueError, match="explicit opportunity"):
        app.submit_analysis(request["request_id"], result)
    result = pattern_result(request)
    result["evaluations"][0]["module_id"] = []
    with pytest.raises(ValueError):
        app.submit_analysis(request["request_id"], result)
    result = pattern_result(request)
    result["evaluations"][0]["opportunity"] = 3
    with pytest.raises(ValueError, match="Evidence"):
        app.submit_analysis(request["request_id"], result)
    result["evaluations"][0]["evidence"] = [{"path": "service.py", "line": 1}]
    with pytest.raises(ValueError, match="current_fit"):
        app.submit_analysis(request["request_id"], result)
    result["evaluations"][0]["current_fit"] = "partial"
    with pytest.raises(ValueError, match="proposed_change"):
        app.submit_analysis(request["request_id"], result)
    result["evaluations"][0]["current_fit"] = []
    with pytest.raises(ValueError, match="current_fit"):
        app.submit_analysis(request["request_id"], result)


def test_fresh_eyes_requirement_ids_must_be_plain_strings(app: Application) -> None:
    annotate(app)
    request = app.analysis_request("fresh-eyes")
    result = fresh_result(request)
    result["alternatives"][0]["requirements"][0] = []
    with pytest.raises(ValueError):
        app.submit_analysis(request["request_id"], result)


def test_check_receipts_distinguish_stale_failed_reported_and_unchecked(app: Application) -> None:
    snapshot_id = app.status()["snapshot"]["id"]
    assert app.validate_change()["behavioral_status"] == "unchecked"
    passed = app.validate_change(
        [{"command": "pytest tests/test_invoices.py", "snapshot_id": snapshot_id, "exit_code": 0}]
    )
    assert passed["behavioral_status"] == "reported-passed"
    assert passed["checks"][0]["origin"] == "agent-or-CI-reported"
    stale = app.validate_change(
        [{"command": "pytest", "snapshot_id": "different-checkout", "exit_code": 0}]
    )
    assert stale["checks"][0]["status"] == "stale"
    assert stale["behavioral_status"] == "unresolved"
    failed = app.validate_change(
        [{"command": "pytest", "snapshot_id": snapshot_id, "exit_code": 1}]
    )
    assert failed["behavioral_status"] == "failed"
    with pytest.raises(ValueError):
        app.validate_change([{"command": "", "snapshot_id": snapshot_id, "exit_code": 0}])
    with pytest.raises(ValueError):
        app.validate_change([{"command": "pytest", "snapshot_id": snapshot_id, "exit_code": True}])


def test_unchanged_application_cycles_preserve_database_bytes(app: Application) -> None:
    request, result = annotate(app)
    before = app.store.path.read_bytes()
    identity = app.status()["snapshot"]["id"]
    for _ in range(5):
        assert app.scan()["snapshot"]["id"] == identity
        app.submit_analysis(request["request_id"], result)
    assert app.store.path.read_bytes() == before
    assert app.store.stats(str(app.root))["snapshots"] == 1
