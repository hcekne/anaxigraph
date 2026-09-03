from __future__ import annotations

import json

from anaxigraph.scan_consistency import CHANGED_DURING_SCAN
from anaxigraph.snapshot_provenance import dirty_snapshot_caveat, snapshot_provenance


def _row(**overrides) -> dict:
    row = {
        "id": 7,
        "commit_sha": "a" * 40,
        "branch": "main",
        "snapshot_kind": "working_tree",
        "dirty": 1,
        "analysis_timestamp": "2026-09-02T10:00:00+00:00",
        "metadata_json": json.dumps({"working_tree_fingerprint": "f" * 64}),
    }
    row.update(overrides)
    return row


def test_provenance_reads_row_and_metadata_defensively():
    full = snapshot_provenance(_row())

    assert full == {
        "snapshot_id": 7,
        "commit_sha": "a" * 40,
        "branch": "main",
        "snapshot_kind": "working_tree",
        "dirty": True,
        "working_tree_fingerprint": "f" * 64,
        "scan_consistency": None,
        "analyzed_at": "2026-09-02T10:00:00+00:00",
    }
    minimal = snapshot_provenance({"id": 42})
    assert minimal["snapshot_id"] == 42
    assert minimal["dirty"] is False
    assert minimal["commit_sha"] is None
    assert minimal["working_tree_fingerprint"] is None
    for unusable in ("not json", '["a list"]', "", None):
        broken = snapshot_provenance(_row(metadata_json=unusable))
        assert broken["working_tree_fingerprint"] is None
        assert broken["dirty"] is True
    assert snapshot_provenance(None)["snapshot_id"] is None
    assert snapshot_provenance({"id": "not a number"})["snapshot_id"] is None


def test_dirty_caveat_names_the_commit_the_fingerprint_and_the_consequence():
    caveat = dirty_snapshot_caveat(snapshot_provenance(_row()))

    assert caveat is not None
    assert "dirty checkout" in caveat
    assert "aaaaaaaaaaaa" in caveat
    assert "working-tree fingerprint ffffffffffff" in caveat
    assert "cannot be reproduced from that commit alone" in caveat
    assert "read the same code" in caveat


def test_a_clean_snapshot_has_no_caveat_and_mid_scan_drift_keeps_one():
    clean = snapshot_provenance(_row(dirty=0))

    assert clean["dirty"] is False
    assert dirty_snapshot_caveat(clean) is None
    drifted = snapshot_provenance(
        _row(dirty=0, metadata_json=json.dumps({"scan_consistency": CHANGED_DURING_SCAN}))
    )
    assert drifted["scan_consistency"] == CHANGED_DURING_SCAN
    drifted_caveat = dirty_snapshot_caveat(drifted)
    assert drifted_caveat is not None
    assert "files changed while the scan ran" in drifted_caveat
    assert "no working-tree fingerprint was recorded" in drifted_caveat
    assert dirty_snapshot_caveat(snapshot_provenance({"id": 42})) is None
    unrecorded = dirty_snapshot_caveat(snapshot_provenance({"id": 42, "dirty": 1}))
    assert unrecorded is not None
    assert "an unrecorded" in unrecorded
