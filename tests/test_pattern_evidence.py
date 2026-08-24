from __future__ import annotations

from semantic_support import _fake_provider, _semantic_config

from anaxigraph.analyzers.python import PythonAnalyzer
from anaxigraph.config import load_config
from anaxigraph.pattern_evidence import PATTERN_EVIDENCE_VERSION
from anaxigraph.pattern_targets import target_key
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_projection_exposes_reusable_evidence_at_all_six_levels(repository, database):
    stats = RepositoryScanner(database).scan(repository)

    projection = database.pattern_evidence(stats.repository_id)
    repeated = database.pattern_evidence(stats.repository_id, stats.snapshot_id)

    assert projection["projection_version"] == PATTERN_EVIDENCE_VERSION
    assert projection["fingerprint"] == repeated["fingerprint"]
    assert projection["counts_by_level"]["module"] == stats.discovered
    assert projection["counts_by_level"]["symbol"] >= 6
    assert projection["counts_by_level"]["type"] >= 1
    assert projection["counts_by_level"]["subsystem"] >= 4
    assert projection["counts_by_level"]["area"] >= 4
    assert projection["counts_by_level"]["repository"] == 1
    assert len(projection["capability_contracts"]) == 3
    assert PythonAnalyzer.capabilities.fingerprint in projection["capability_contracts"]

    items = {item["target"]["key"]: item for item in projection["items"]}
    module_key = target_key("module", path="pkg/core.py")
    type_key = target_key("type", path="pkg/core.py", identity="pkg.core.Calculator")
    method_key = target_key(
        "symbol",
        path="pkg/core.py",
        identity="pkg.core.Calculator.calculate",
    )
    module = items[module_key]
    calculator = items[type_key]
    calculate = items[method_key]
    module_features = {item["name"]: item for item in module["features"]}

    assert calculator["target"]["parent_key"] == module_key
    assert calculate["target"]["parent_key"] == type_key
    assert module_features["code.lines"]["value"] > 0
    assert module_features["syntax.symbol_documentation"]["value"]["count"] >= 1
    assert module_features["semantic.dossier"]["availability"] == "unavailable"
    assert module["capability_fingerprints"] == [PythonAnalyzer.capabilities.fingerprint]
    assert all(len(item["input_fingerprint"]) == 64 for item in projection["items"])


def test_projection_fingerprints_invalidate_only_changed_targets_and_parents(repository, database):
    first_scan = RepositoryScanner(database).scan(repository)
    before = {
        item["target"]["key"]: item["input_fingerprint"]
        for item in database.pattern_evidence(first_scan.repository_id)["items"]
    }
    (repository / "pkg" / "util.py").write_text(
        '"""Small arithmetic helpers."""\n\ndef double(value: int) -> int:\n    return value * 3\n',
        encoding="utf-8",
    )

    second_scan = RepositoryScanner(database).scan(repository)
    after_projection = database.pattern_evidence(second_scan.repository_id)
    after = {item["target"]["key"]: item["input_fingerprint"] for item in after_projection["items"]}

    util_module = target_key("module", path="pkg/util.py")
    util_symbol = target_key("symbol", path="pkg/util.py", identity="pkg.util.double")
    core_module = target_key("module", path="pkg/core.py")
    assert before[util_module] != after[util_module]
    assert before[util_symbol] != after[util_symbol]
    assert before[core_module] == after[core_module]

    util_parent = next(
        item["target"]["parent_key"]
        for item in after_projection["items"]
        if item["target"]["key"] == util_module
    )
    assert before[util_parent] != after[util_parent]
    assert before["repository:root"] != after["repository:root"]


def test_lexical_symbol_marks_unsupported_documentation_as_unavailable(repository, database):
    stats = RepositoryScanner(database).scan(repository)
    projection = database.pattern_evidence(stats.repository_id)
    app_key = target_key("symbol", path="web/App.tsx", identity="web.App.App")
    app = next(item for item in projection["items"] if item["target"]["key"] == app_key)
    documentation = next(
        feature for feature in app["features"] if feature["name"] == "documentation.summary"
    )

    assert documentation["availability"] == "unavailable"
    assert documentation["confidence"] == 0


def test_projection_uses_only_current_dossiers_and_reviewed_taxonomy(
    repository, database, tmp_path
):
    provider = _fake_provider(tmp_path)
    _semantic_config(repository, provider, tmp_path / "semantic.log")
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    SemanticEngine(database).bootstrap(stats.repository_id, repository, config)

    projection = database.pattern_evidence(stats.repository_id)
    items = {item["target"]["key"]: item for item in projection["items"]}
    core = items[target_key("module", path="pkg/core.py")]
    features = {item["name"]: item for item in core["features"]}

    assert projection["counts_by_level"]["area"] == 1
    assert projection["counts_by_level"]["subsystem"] == 1
    assert core["target"]["parent_key"] == "subsystem:sample-runtime"
    assert features["semantic.dossier"]["availability"] == "available"
    assert features["semantic.responsibilities"]["value"] == ["Own pkg/core.py"]
