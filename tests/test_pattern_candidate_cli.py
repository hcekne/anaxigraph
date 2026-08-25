from __future__ import annotations

import json

from anaxigraph.cli import main
from anaxigraph.semantic_service import SemanticServiceTarget


def test_candidate_query_uses_the_matching_authoritative_service(repository, capsys, monkeypatch):
    target = SemanticServiceTarget("http://127.0.0.1:9999", 17, "Sample", "/repo")
    captured = {}
    monkeypatch.setattr(
        "anaxigraph.cli_pattern_calibration.discover_semantic_service",
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
        "anaxigraph.cli_pattern_calibration.service_pattern_candidates", query_candidates
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
