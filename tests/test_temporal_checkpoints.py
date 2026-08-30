from __future__ import annotations

import subprocess
from pathlib import Path

from anaxigraph.history import import_git_history
from anaxigraph.persistence import (
    CHECKPOINT_INTERVAL,
    rebuild_checkpoints,
    reconstruct_files_with_diagnostics,
    reconstruct_relationships_with_diagnostics,
    snapshot_files,
    snapshot_relationship_edges,
)
from anaxigraph.storage import AnaxiIndex


def _long_history_repository(root: Path, commits: int = 33) -> Path:
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.invalid"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
    )
    for index in range(commits):
        (root / "service.py").write_text(
            f"from dependency import value\n\nCURRENT = {index}\n",
            encoding="utf-8",
        )
        subprocess.run(["git", "-C", str(root), "add", "."], check=True)
        subprocess.run(
            ["git", "-C", str(root), "commit", "-qm", f"Frame {index}"],
            check=True,
        )
    return root


def _canonical_frames(connection, snapshot_ids: list[int]) -> dict[int, tuple]:
    return {
        snapshot_id: (
            snapshot_files(connection, snapshot_id),
            snapshot_relationship_edges(connection, snapshot_id),
        )
        for snapshot_id in snapshot_ids
    }


def test_checkpoints_bound_reads_and_rebuild_without_changing_facts(tmp_path, database):
    repository = _long_history_repository(tmp_path / "long-history")
    import_git_history(database, repository, every_commit=True)

    with database.connect() as connection:
        snapshots = connection.execute(
            "SELECT id, sequence FROM snapshots ORDER BY sequence"
        ).fetchall()
        checkpoint_rows = connection.execute(
            """
            SELECT snapshot_id, sequence, source_delta_depth, file_state_hash,
                   relationship_state_hash
            FROM snapshot_checkpoints ORDER BY sequence
            """
        ).fetchall()
        maximum_file_depth = 0
        maximum_relationship_depth = 0
        for snapshot in snapshots:
            _files, file_diagnostics = reconstruct_files_with_diagnostics(
                connection,
                int(snapshot["id"]),
            )
            _edges, relationship_diagnostics = reconstruct_relationships_with_diagnostics(
                connection,
                int(snapshot["id"]),
            )
            maximum_file_depth = max(maximum_file_depth, file_diagnostics.traversed_deltas)
            maximum_relationship_depth = max(
                maximum_relationship_depth,
                relationship_diagnostics.traversed_deltas,
            )
        sample_ids = [int(snapshots[index]["id"]) for index in (0, 15, 16, 31, 32)]
        before = _canonical_frames(connection, sample_ids)
        hashes_before = [tuple(row)[3:] for row in checkpoint_rows]

        connection.execute("DELETE FROM snapshot_checkpoints")
        _files, unbounded = reconstruct_files_with_diagnostics(
            connection,
            int(snapshots[-1]["id"]),
        )
        rebuilt = rebuild_checkpoints(connection)
        after = _canonical_frames(connection, sample_ids)
        hashes_after = [
            tuple(row)
            for row in connection.execute(
                """
                SELECT file_state_hash, relationship_state_hash
                FROM snapshot_checkpoints ORDER BY sequence
                """
            ).fetchall()
        ]
        connection.commit()
        connection.execute("PRAGMA foreign_keys = OFF")
        rebuilt_without_foreign_key_actions = rebuild_checkpoints(connection)
        connection.commit()
        connection.execute("PRAGMA foreign_keys = ON")

    assert len(snapshots) == 33
    assert [row["sequence"] for row in checkpoint_rows] == [15, 31]
    assert [row["source_delta_depth"] for row in checkpoint_rows] == [16, 16]
    assert maximum_file_depth < CHECKPOINT_INTERVAL
    assert maximum_relationship_depth < CHECKPOINT_INTERVAL
    assert unbounded.traversed_deltas == 33
    assert rebuilt == {"snapshots": 33, "checkpoints": 2}
    assert rebuilt_without_foreign_key_actions == {"snapshots": 33, "checkpoints": 2}
    assert after == before
    assert hashes_after == hashes_before

    with database.connect() as connection:
        connection.execute("DELETE FROM snapshot_checkpoints")
        connection.execute("DELETE FROM schema_meta WHERE key = 'checkpoint_policy_version'")
        connection.commit()

    reopened = AnaxiIndex(database.path)
    with reopened.connect() as connection:
        restored = connection.execute(
            "SELECT sequence FROM snapshot_checkpoints ORDER BY sequence"
        ).fetchall()
        policy = connection.execute(
            "SELECT value FROM schema_meta WHERE key = 'checkpoint_policy_version'"
        ).fetchone()

    assert [row["sequence"] for row in restored] == [15, 31]
    assert policy[0] == "bounded-delta-v3"
