from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from anaxigraph import git
from anaxigraph.config import load_config
from anaxigraph.history import import_git_history
from anaxigraph.scanner import RepositoryScanner, analysis_signature
from benchmarks.repository_factory import create_history_repository


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _commit(root: Path, message: str) -> str:
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", message], check=True)
    return _git(root, "rev-parse", "HEAD")


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "temporal"
    (root / "src" / "pkg").mkdir(parents=True)
    (root / "lib" / "pkg").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / ".anaxigraph.yml").write_text(
        """project:
  name: Temporal correctness fixture
include: [src/**, lib/**, docs/**]
groups:
  application:
    paths: [src/**, lib/**]
  documentation:
    paths: [docs/**]
architecture:
  rules:
    - id: small-files
      type: max_module_loc
      severity: info
      max: 2
semantic:
  enabled: false
""",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.email", "temporal@example.invalid")
    _git(root, "config", "user.name", "Temporal Fixture")
    return root


def _snapshot_id(database, repository: Path, commit_sha: str) -> int:
    row = database.repository(repository)
    assert row is not None
    snapshot = database.commit_snapshot(
        int(row["id"]), commit_sha, analysis_signature(load_config(repository))
    )
    assert snapshot is not None
    return int(snapshot["id"])


def _frame(database, snapshot_id: int) -> dict[str, Any]:
    with database.connect() as connection:
        files = connection.execute(
            """
            SELECT path, language, raw_hash, structural_hash, analysis_status,
                   declared_group, inferred_group, metadata_json
            FROM file_versions WHERE snapshot_id = ? ORDER BY path
            """,
            (snapshot_id,),
        ).fetchall()
        symbols = connection.execute(
            """
            SELECT fv.path, s.qualified_name, s.symbol_type
            FROM symbols s JOIN file_versions fv ON fv.id = s.artifact_version_id
            WHERE fv.snapshot_id = ? ORDER BY fv.path, s.qualified_name
            """,
            (snapshot_id,),
        ).fetchall()
        edges = connection.execute(
            """
            SELECT source.canonical_path AS source_path,
                   target.canonical_path AS target_path,
                   rel.target_external, rel.relationship_type, rel.metadata_json
            FROM relationships rel
            JOIN artifacts source ON source.id = rel.source_artifact_id
            LEFT JOIN artifacts target ON target.id = rel.target_artifact_id
            WHERE rel.snapshot_id = ?
            ORDER BY source_path, target_path, rel.target_external
            """,
            (snapshot_id,),
        ).fetchall()
        memberships = connection.execute(
            """
            SELECT a.canonical_path, g.name, g.source
            FROM group_memberships gm
            JOIN artifacts a ON a.id = gm.artifact_id
            JOIN groups g ON g.id = gm.group_id
            WHERE gm.snapshot_id = ? ORDER BY a.canonical_path, g.name, g.source
            """,
            (snapshot_id,),
        ).fetchall()
        metrics = connection.execute(
            "SELECT name, value FROM metrics WHERE snapshot_id = ? ORDER BY name, entity_id",
            (snapshot_id,),
        ).fetchall()
        findings = connection.execute(
            """
            SELECT f.stable_key FROM finding_occurrences occurrence
            JOIN findings f ON f.id = occurrence.finding_id
            WHERE occurrence.snapshot_id = ? ORDER BY f.stable_key
            """,
            (snapshot_id,),
        ).fetchall()
    return {
        "files": {row["path"]: dict(row) for row in files},
        "symbols": {(row["path"], row["qualified_name"], row["symbol_type"]) for row in symbols},
        "edges": [
            {
                **dict(row),
                "resolution": json.loads(row["metadata_json"])["resolution_status"],
            }
            for row in edges
        ],
        "memberships": {(row["canonical_path"], row["name"], row["source"]) for row in memberships},
        "metrics": [tuple(row) for row in metrics],
        "findings": [row["stable_key"] for row in findings],
    }


def test_frames_preserve_add_modify_delete_rename_copy_and_type_change(tmp_path, database):
    root = _repository(tmp_path)
    (root / "src" / "app.py").write_text(
        "from pkg.service import execute\n\ndef run():\n    return execute()\n", encoding="utf-8"
    )
    (root / "src" / "pkg" / "service.py").write_text(
        "def execute():\n    return 1\n", encoding="utf-8"
    )
    (root / "src" / "typed.py").write_text("VALUE = 1\n", encoding="utf-8")
    initial = _commit(root, "initial")

    (root / "src" / "app.py").write_text(
        "from pkg.service import execute\n\ndef run():\n    return execute() + 1\n",
        encoding="utf-8",
    )
    (root / "src" / "extra.py").write_text("def extra():\n    return 2\n", encoding="utf-8")
    changed = _commit(root, "modify and add")

    (root / "src" / "pkg" / "service.py").rename(root / "src" / "pkg" / "engine.py")
    (root / "src" / "app.py").write_text(
        "from pkg.engine import execute\n\ndef run():\n    return execute() + 1\n", encoding="utf-8"
    )
    (root / "src" / "extra_copy.py").write_text(
        (root / "src" / "extra.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    moved = _commit(root, "rename and copy")

    (root / "src" / "extra_copy.py").unlink()
    (root / "src" / "typed.py").unlink()
    os.symlink("extra.py", root / "src" / "typed.py")
    typed = _commit(root, "delete and type change")

    result = import_git_history(database, root, every_commit=True)
    assert result.selected_commits == 4
    first = _frame(database, _snapshot_id(database, root, initial))
    second = _frame(database, _snapshot_id(database, root, changed))
    third = _frame(database, _snapshot_id(database, root, moved))
    fourth = _frame(database, _snapshot_id(database, root, typed))

    assert set(first["files"]) == {"src/app.py", "src/pkg/service.py", "src/typed.py"}
    assert second["files"]["src/app.py"]["analysis_status"] == "structural_changed"
    assert ("src/extra.py", "src.extra.extra", "function") in second["symbols"]
    assert "src/pkg/service.py" not in third["files"]
    assert {"src/pkg/engine.py", "src/extra_copy.py"} <= set(third["files"])
    assert "src/extra_copy.py" not in fourth["files"]
    assert fourth["files"]["src/typed.py"]["raw_hash"] != first["files"]["src/typed.py"]["raw_hash"]
    assert ("src/app.py", "application", "declared") in fourth["memberships"]
    assert fourth["metrics"]
    assert fourth["findings"] == []


def test_selected_frames_include_all_changes_between_sampled_commits(tmp_path, database):
    root = _repository(tmp_path)
    target = root / "src" / "counter.py"
    target.write_text("VALUE = 0\n", encoding="utf-8")
    commits = [_commit(root, "initial")]
    for value in range(1, 7):
        target.write_text(f"VALUE = {value}\n", encoding="utf-8")
        if value == 3:
            (root / "src" / "middle.py").write_text("MIDDLE = True\n", encoding="utf-8")
        commits.append(_commit(root, f"change {value}"))

    result = import_git_history(database, root, max_snapshots=3)
    row = database.repository(root)
    timeline = database.timeline_snapshots(int(row["id"]))

    assert result.selected_commits == 3
    assert [item["commit_sha"] for item in timeline] == [commits[0], commits[3], commits[6]]
    last = _frame(database, _snapshot_id(database, root, commits[-1]))
    assert {"src/counter.py", "src/middle.py"} <= set(last["files"])


def test_namespace_changes_recompute_unique_ambiguous_and_unique_edges(tmp_path, database):
    root = _repository(tmp_path)
    (root / "src" / "pkg" / "shared.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "src" / "consumer.py").write_text("import pkg.shared\n", encoding="utf-8")
    unique = _commit(root, "unique module")
    (root / "lib" / "pkg" / "shared.py").write_text("VALUE = 2\n", encoding="utf-8")
    ambiguous = _commit(root, "ambiguous module")
    (root / "src" / "pkg" / "shared.py").unlink()
    restored = _commit(root, "unique module restored")

    import_git_history(database, root, every_commit=True)

    def resolutions(commit: str) -> list[str]:
        frame = _frame(database, _snapshot_id(database, root, commit))
        return [
            edge["resolution"]
            for edge in frame["edges"]
            if edge["source_path"] == "src/consumer.py"
        ]

    assert resolutions(unique) == ["resolved_internal"]
    assert resolutions(ambiguous) == ["ambiguous_internal"]
    assert resolutions(restored) == ["resolved_internal"]


def test_change_classes_keep_structural_and_interface_evidence(tmp_path, database):
    root = _repository(tmp_path)
    module = root / "src" / "service.py"
    module.write_text(
        '"""Initial description."""\n\ndef serve(value: int) -> int:\n    return value\n',
        encoding="utf-8",
    )
    initial = _commit(root, "initial")
    module.write_text(
        '"""Updated description."""\n\ndef serve(value: int) -> int:\n    return value\n',
        encoding="utf-8",
    )
    metadata = _commit(root, "documentation only")
    module.write_text(
        '"""Updated description."""\n\ndef serve(value: str) -> str:\n    return value.upper()\n',
        encoding="utf-8",
    )
    interface = _commit(root, "interface and behavior")

    import_git_history(database, root, every_commit=True)
    first = _frame(database, _snapshot_id(database, root, initial))["files"]["src/service.py"]
    second = _frame(database, _snapshot_id(database, root, metadata))["files"]["src/service.py"]
    third = _frame(database, _snapshot_id(database, root, interface))["files"]["src/service.py"]

    assert first["structural_hash"] == second["structural_hash"]
    assert second["analysis_status"] == "metadata_only"
    assert third["analysis_status"] == "structural_changed"
    assert json.loads(third["metadata_json"])["ir"]["exports"] == ["serve"]


def test_working_tree_scan_remains_current_after_first_parent_history(tmp_path, database):
    root = _repository(tmp_path)
    target = root / "src" / "app.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _commit(root, "initial")
    target.write_text("VALUE = 2\n", encoding="utf-8")
    head = _commit(root, "second")
    import_git_history(database, root, every_commit=True)

    subprocess.run(["git", "-C", str(root), "checkout", "-qb", "feature"], check=True)
    target.write_text("VALUE = 3\n", encoding="utf-8")
    stats = RepositoryScanner(database).scan(root, run_type="branch_working_tree")
    current = database.latest_snapshot(stats.repository_id)

    assert current["snapshot_kind"] == "working_tree"
    assert current["commit_sha"] == head
    assert current["branch"] == "feature"
    assert current["dirty"] == 1
    assert (
        database.file_details(stats.repository_id, "src/app.py")["file"]["analysis_status"]
        == "structural_changed"
    )


class _InterruptingScanner(RepositoryScanner):
    def __init__(self, database, *, fail_on: int) -> None:
        super().__init__(database)
        self.fail_on = fail_on
        self.revisions: list[str | None] = []

    def scan(self, repository, **kwargs):
        self.revisions.append(kwargs.get("revision"))
        if len(self.revisions) == self.fail_on:
            raise RuntimeError("simulated interruption")
        return super().scan(repository, **kwargs)


def test_interrupted_history_resumes_from_completed_frames(tmp_path, database):
    root = _repository(tmp_path)
    target = root / "src" / "app.py"
    target.write_text("VALUE = 0\n", encoding="utf-8")
    commits = [_commit(root, "initial")]
    for value in range(1, 4):
        target.write_text(f"VALUE = {value}\n", encoding="utf-8")
        commits.append(_commit(root, f"change {value}"))

    interrupted = _InterruptingScanner(database, fail_on=3)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        import_git_history(database, root, every_commit=True, scanner=interrupted)
    row = database.repository(root)
    before = {
        item["commit_sha"]: item["id"] for item in database.timeline_snapshots(int(row["id"]))
    }

    resumed = _InterruptingScanner(database, fail_on=99)
    result = import_git_history(database, root, every_commit=True, scanner=resumed)
    after = {item["commit_sha"]: item["id"] for item in database.timeline_snapshots(int(row["id"]))}

    assert set(before) == set(commits[:2])
    assert {commit: after[commit] for commit in before} == before
    assert resumed.revisions == [commits[2], commits[3], None]
    assert result.current_snapshot_id == database.latest_snapshot(int(row["id"]))["id"]


def test_revision_delta_classifies_every_tree_transition(tmp_path):
    root = _repository(tmp_path)
    files = {
        "modify.py": "VALUE = 1\n",
        "delete.py": "VALUE = 2\n",
        "rename.py": "VALUE = 3\n",
        "copy.py": "VALUE = 4\n",
        "typed.py": "VALUE = 5\n",
    }
    for name, content in files.items():
        (root / "src" / name).write_text(content, encoding="utf-8")
    first = _commit(root, "initial transitions")

    (root / "src" / "modify.py").write_text("VALUE = 10\n", encoding="utf-8")
    (root / "src" / "delete.py").unlink()
    (root / "src" / "rename.py").rename(root / "src" / "renamed.py")
    (root / "src" / "copied.py").write_text(
        (root / "src" / "copy.py").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "src" / "typed.py").unlink()
    os.symlink("copy.py", root / "src" / "typed.py")
    (root / "src" / "added.py").write_text("VALUE = 6\n", encoding="utf-8")
    second = _commit(root, "all transitions")

    delta = git.revision_delta(root, first, second)
    by_current_path = {item.new_path: item.status for item in delta.changes if item.new_path}

    assert {item.status for item in delta.changes} == {"A", "C", "D", "M", "R", "T"}
    assert by_current_path["src/renamed.py"] == "R"
    assert by_current_path["src/copied.py"] == "C"
    assert delta.removed_paths == frozenset({"src/delete.py", "src/rename.py"})


def test_history_reads_only_distinct_changed_blobs_and_records_reuse(
    tmp_path, database, monkeypatch
):
    root = tmp_path / "delta-history"
    manifest = create_history_repository(root, file_count=120)
    original = git.read_at_revision
    reads: list[tuple[str, str]] = []

    def counted(root, revision, path, *, max_bytes):
        reads.append((revision, path))
        return original(root, revision, path, max_bytes=max_bytes)

    monkeypatch.setattr(git, "read_at_revision", counted)
    result = import_git_history(database, root, every_commit=True)

    assert len(reads) == manifest["expected_distinct_artifact_raw_versions"] == 135
    with database.connect() as connection:
        history_runs = connection.execute(
            "SELECT metadata_json FROM analysis_runs WHERE run_type = 'history' ORDER BY id"
        ).fetchall()
        metadata_rows = connection.execute(
            "SELECT metadata_json FROM file_versions WHERE snapshot_id = ?",
            (result.current_snapshot_id,),
        ).fetchall()
    counters = [json.loads(row["metadata_json"]) for row in history_runs]
    file_metadata = [json.loads(row["metadata_json"]) for row in metadata_rows]

    assert sum(item["source_reads"] for item in counters) == 135
    assert sum(item["carried_forward"] for item in counters) > 700
    assert {item["invalidation_reason"] for item in file_metadata} <= {
        "carried_forward",
        "content_changed",
    }
    assert all("history_change_kind" in item and "source_read" in item for item in file_metadata)
