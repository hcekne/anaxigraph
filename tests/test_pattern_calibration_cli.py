from __future__ import annotations

import json
from pathlib import Path

from anaxigraph.cli import main
from anaxigraph.semantic_service import SemanticServiceTarget

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "benchmarks/pattern-calibration/anaxigraph.json"


def test_calibration_cli_uses_matching_authoritative_service(repository, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    calls = {"candidates": 0, "evaluations": 0}
    monkeypatch.setattr(
        "anaxigraph.cli_pattern_calibration.discover_semantic_service",
        lambda *_args, **_kwargs: target,
    )

    def candidates(_service, _request, *, snapshot_id=None):
        calls["candidates"] += 1
        assert snapshot_id == 8
        return {"snapshot_id": 8, "plan_ready": False, "items": []}

    def evaluations(_service, _request, *, snapshot_id=None):
        calls["evaluations"] += 1
        assert snapshot_id == 8
        return {"snapshot_id": 8, "items": []}

    monkeypatch.setattr("anaxigraph.cli_pattern_calibration.service_pattern_candidates", candidates)
    monkeypatch.setattr(
        "anaxigraph.cli_pattern_calibration.service_pattern_evaluations", evaluations
    )
    main(
        [
            "patterns",
            str(repository),
            "--calibrate",
            str(MANIFEST),
            "--snapshot-id",
            "8",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["contract_version"] == "pattern-calibration-report-v1"
    assert result["status"] == "incomplete"
    assert result["index"] == target.identity()
    assert calls == {"candidates": 7, "evaluations": 7}


def test_calibration_cli_reads_the_explicit_local_index(repository, tmp_path, capsys):
    database = tmp_path / "calibration.db"
    main(["scan", str(repository), "--db", str(database), "--json"])
    capsys.readouterr()

    main(
        [
            "patterns",
            str(repository),
            "--db",
            str(database),
            "--calibrate",
            str(MANIFEST),
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["contract_version"] == "pattern-calibration-report-v1"
    assert result["index"] == {"authority": "local", "database": str(database)}
    assert result["manifest"]["cases"] == 7
