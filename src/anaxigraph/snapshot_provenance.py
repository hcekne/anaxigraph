"""One projection of the checkout a saved snapshot was read from.

A review or a Charter is only reproducible when the bytes behind it can be named. A commit
alone does not name them: a scan of a checkout with uncommitted changes reads content that
no commit contains, so a second model given "the same commit" is not given the same code and
the two results cannot honestly be compared. The scan already records what is needed - the
commit, the dirty flag, the working-tree fingerprint, and (when the tree moved between the
file reads of one scan) the ``scan_consistency`` verdict - so this module only projects those
recorded facts and states the consequence in one caveat sentence.

Rows arrive from several readers (``latest_snapshot`` returns ``SELECT s.*``, the overview
projects ``dict(snapshot)``, and tests hand in a minimal ``{"id": 42}``), so every field is
read defensively and a missing column is reported as unknown rather than assumed clean.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from anaxigraph.scan_consistency import CHANGED_DURING_SCAN


def snapshot_provenance(row: Mapping[str, Any] | None) -> dict[str, Any]:
    """Name the commit and working-tree state one saved snapshot was analyzed from."""

    values = row or {}
    metadata = _snapshot_metadata(values)
    return {
        "snapshot_id": _optional_int(values.get("id")),
        "commit_sha": _optional_text(values.get("commit_sha")),
        "branch": _optional_text(values.get("branch")),
        "snapshot_kind": _optional_text(values.get("snapshot_kind")),
        "dirty": bool(values.get("dirty")),
        "working_tree_fingerprint": _optional_text(metadata.get("working_tree_fingerprint")),
        "scan_consistency": _optional_text(metadata.get("scan_consistency")),
        "analyzed_at": _optional_text(values.get("analysis_timestamp")),
    }


def dirty_snapshot_caveat(provenance: Mapping[str, Any]) -> str | None:
    """Say why a result read from an uncommitted checkout cannot be reproduced or compared."""

    drifted = provenance.get("scan_consistency") == CHANGED_DURING_SCAN
    if not provenance.get("dirty") and not drifted:
        return None
    recorded = provenance.get("commit_sha")
    commit = str(recorded)[:12] if recorded else "an unrecorded commit"
    fingerprint = provenance.get("working_tree_fingerprint")
    identified = (
        f"working-tree fingerprint {str(fingerprint)[:12]}"
        if fingerprint
        else "no working-tree fingerprint was recorded"
    )
    observed = "files changed while the scan ran" if drifted else "uncommitted changes"
    return (
        f"This result was produced from a dirty checkout of {commit} ({observed}; {identified}), "
        "so it cannot be reproduced from that commit alone and two reviews of it cannot be shown "
        "to have read the same code. Commit the changes and rescan before comparing reviews."
    )


def _snapshot_metadata(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None
