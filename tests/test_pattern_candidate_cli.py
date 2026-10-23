from __future__ import annotations

import json

from anaxigraph.cli import main
from anaxigraph.semantic_service import SemanticServiceTarget


def test_candidate_query_uses_the_matching_authoritative_service(repository, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    captured = {}
    monkeypatch.setattr(
        "anaxigraph.cli_pattern_commands.discover_semantic_service",
        lambda *_args, **_kwargs: target,
    )

    def query_candidates(service, request, *, snapshot_id=None):
        captured.update(
            service=service,
            pattern=request.pattern,
            selection=request.selection,
            snapshot_id=snapshot_id,
        )
        return {"contract_version": "pattern-candidate-query-v1", "items": []}

    monkeypatch.setattr(
        "anaxigraph.cli_pattern_commands.service_pattern_candidates", query_candidates
    )
    main(
        [
            "patterns",
            str(repository),
            "--candidates",
            "--pattern",
            "strategy",
            "--selection",
            "all",
            "--snapshot-id",
            "7",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)

    assert result["index"] == target.identity()
    assert captured == {
        "service": target,
        "pattern": "strategy",
        "selection": "all",
        "snapshot_id": 7,
    }


def test_catalogue_cli_preserves_coverage_and_manifest_filters(repository, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    captured = {}
    monkeypatch.setattr(
        "anaxigraph.cli_pattern_commands.discover_semantic_service", lambda *a, **k: target
    )

    def query(service, request, *, snapshot_id=None):
        captured.update(request.filters())
        return {"catalogue": {"expected": 133, "reviewed": 0}, "items": []}

    monkeypatch.setattr("anaxigraph.cli_pattern_commands.service_pattern_evaluations", query)
    main(
        [
            "patterns",
            str(repository),
            "--catalogue",
            "--state",
            "missing",
            "--include-manifest",
            "--json",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    assert result["catalogue"]["expected"] == 133
    assert captured["include_manifest"] and captured["state"] == "missing"
