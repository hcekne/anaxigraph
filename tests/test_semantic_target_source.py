"""The single guard that lets a planned semantic job read its target from the mounted tree."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from semantic_support import _enable_agent_semantics

import anaxigraph
from anaxigraph.config import SemanticConfig, load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_agent import SemanticAgentService
from anaxigraph.semantic_graph import SupersededSemanticJob
from anaxigraph.semantic_pattern_requests import _source_evidence
from anaxigraph.semantic_requests import SemanticEvidenceService
from anaxigraph.semantic_target_source import read_mounted_source, require_unchanged_source
from anaxigraph.understanding import SemanticEngine

TARGET = "pkg/util.py"
INTRINSIC_MISSING = "The target module no longer exists in the mounted tree"
INTRINSIC_CHANGED = "The module changed after this semantic job was planned"
PATTERN_MISSING = "The file for this pattern check no longer exists"
PATTERN_CHANGED = "The pattern target changed after this work was planned"


# --- helper units -----------------------------------------------------------------------------


def test_read_mounted_source_returns_the_bytes_of_a_regular_file(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "module.py").write_bytes(b"VALUE = 1\n")

    assert read_mounted_source(root, "pkg/module.py", missing="gone") == b"VALUE = 1\n"


@pytest.mark.parametrize(
    "path",
    ["../outside.py", "pkg/missing.py", "pkg", "pkg/escape.py"],
    ids=["escapes_root", "missing_file", "directory", "symlink_outside_root"],
)
def test_read_mounted_source_refuses_anything_but_a_file_inside_root(
    tmp_path: Path, path: str
) -> None:
    root = tmp_path / "tree"
    (root / "pkg").mkdir(parents=True)
    (tmp_path / "outside.py").write_bytes(b"OUTSIDE = 1\n")
    (root / "pkg" / "escape.py").symlink_to(tmp_path / "outside.py")

    with pytest.raises(SupersededSemanticJob, match="^gone$"):
        read_mounted_source(root, path, missing="gone")


def test_read_mounted_source_reads_through_a_symlink_that_stays_inside_root(
    tmp_path: Path,
) -> None:
    # Discovery never plans a symlinked file, so this only happens when a symlink replaced the
    # planned file afterwards; the policy is to read the in-tree target and let the saved-hash
    # comparison decide whether the job is still valid.
    root = tmp_path / "tree"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "real.py").write_bytes(b"REAL = 1\n")
    (root / "pkg" / "alias.py").symlink_to(root / "pkg" / "real.py")

    assert read_mounted_source(root, "pkg/alias.py", missing="gone") == b"REAL = 1\n"


def test_require_unchanged_source_returns_the_digest_only_when_the_hash_matches() -> None:
    raw = b"print('hello')\n"
    digest = hashlib.sha256(raw).hexdigest()

    assert require_unchanged_source(raw, {"raw_hash": digest}, changed="moved") == digest
    with pytest.raises(SupersededSemanticJob, match="^moved$"):
        require_unchanged_source(raw, None, changed="moved")
    with pytest.raises(SupersededSemanticJob, match="^moved$"):
        require_unchanged_source(raw, {"raw_hash": "0" * 64}, changed="moved")


# --- both request builders ---------------------------------------------------------------------


def _scan(repository: Path, database) -> tuple[object, int]:
    stats = RepositoryScanner(database).scan(repository)
    detail = database.file_details(stats.repository_id, TARGET)
    assert detail is not None
    return stats, int(detail["file"]["artifact_id"])


def _job(stats, artifact_id: int, kind: str, path: str) -> dict:
    metadata: dict = {}
    if kind == "pattern_assessment":
        metadata = {
            "candidate": {"target": {"path": path, "level": "module", "label": path}},
            "pattern": {},
            "target_evidence": {},
        }
    return {
        "id": 7,
        "job_kind": kind,
        "scope_key": path,
        "snapshot_id": stats.snapshot_id,
        "artifact_id": artifact_id,
        "repository_id": stats.repository_id,
        "metadata": metadata,
    }


def _disturb(repository: Path, scenario: str) -> str:
    """Change the mounted tree after planning and return the path the job should name."""
    target = repository / TARGET
    outside = repository.parent / "outside.py"
    outside.write_bytes(b"OUTSIDE = 1\n")
    if scenario == "outside":
        return "../outside.py"
    if scenario == "deleted":
        target.unlink()
    elif scenario == "changed":
        target.write_bytes(target.read_bytes() + b"\nCHANGED = True\n")
    elif scenario == "escaping_symlink":
        target.unlink()
        target.symlink_to(outside)
    return TARGET


SCENARIOS = ["outside", "deleted", "changed", "escaping_symlink"]


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_intrinsic_request_supersedes_a_job_whose_target_is_gone_or_changed(
    repository: Path, database, scenario: str
) -> None:
    stats, artifact_id = _scan(repository, database)
    path = _disturb(repository, scenario)
    expected = INTRINSIC_CHANGED if scenario == "changed" else INTRINSIC_MISSING

    with pytest.raises(SupersededSemanticJob) as raised:
        SemanticEvidenceService(database)._intrinsic_request(
            _job(stats, artifact_id, "intrinsic", path), repository.resolve()
        )
    assert str(raised.value) == expected


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_pattern_source_evidence_supersedes_a_job_whose_target_is_gone_or_changed(
    repository: Path, database, scenario: str
) -> None:
    stats, artifact_id = _scan(repository, database)
    path = _disturb(repository, scenario)
    expected = PATTERN_CHANGED if scenario == "changed" else PATTERN_MISSING

    with pytest.raises(SupersededSemanticJob) as raised:
        _source_evidence(
            database,
            _job(stats, artifact_id, "pattern_assessment", path),
            repository.resolve(),
            SemanticConfig(),
        )
    assert str(raised.value) == expected


def test_pattern_source_evidence_still_serves_an_untouched_target(
    repository: Path, database
) -> None:
    stats, artifact_id = _scan(repository, database)

    evidence = _source_evidence(
        database,
        _job(stats, artifact_id, "pattern_assessment", TARGET),
        repository.resolve(),
        SemanticConfig(),
    )

    assert evidence["path"] == TARGET
    assert evidence["language"] == "python"
    assert "def double" in evidence["source"]


# --- the agent marks the job superseded with the same text ------------------------------------


def test_agent_marks_an_intrinsic_job_superseded_when_its_target_disappears(
    repository: Path, database
) -> None:
    _enable_agent_semantics(repository)
    config = load_config(repository)
    stats = RepositoryScanner(database).scan(repository)
    engine = SemanticEngine(database)
    engine.plan(stats.repository_id, repository, config)
    (repository / TARGET).unlink()

    row = None
    for _ in range(12):
        engine.claim_agent_work(stats.repository_id, repository, config, agent_id="guard-test")
        with database.connect() as connection:
            row = connection.execute(
                """
                SELECT status, error FROM semantic_jobs
                WHERE snapshot_id = ? AND job_kind = 'intrinsic' AND scope_key = ?
                """,
                (stats.snapshot_id, TARGET),
            ).fetchone()
        if row is not None and row["status"] == "superseded":
            break

    assert row is not None
    assert tuple(row) == ("superseded", INTRINSIC_MISSING)


class _RecordingPersistence:
    def __init__(self) -> None:
        self.superseded: list[tuple[int, str]] = []

    def mark_superseded(self, job_id: int, reason: str) -> None:
        self.superseded.append((job_id, reason))


def test_agent_marks_a_pattern_job_superseded_when_its_target_disappears(
    repository: Path, database
) -> None:
    stats, artifact_id = _scan(repository, database)
    persistence = _RecordingPersistence()
    agent = SemanticAgentService(None, None, None, SemanticEvidenceService(database), persistence)
    (repository / TARGET).unlink()

    packet = agent._work_packet(
        stats.repository_id,
        repository.resolve(),
        SemanticConfig(),
        _job(stats, artifact_id, "pattern_assessment", TARGET),
        "lease-token",
    )

    assert packet is None
    assert persistence.superseded == [(7, PATTERN_MISSING)]


# --- durable structural guard -----------------------------------------------------------------


def test_is_relative_to_is_only_evaluated_inside_the_shared_guard() -> None:
    package = Path(anaxigraph.__file__).resolve().parent
    users = sorted(
        str(path.relative_to(package))
        for path in package.rglob("*.py")
        if "is_relative_to" in path.read_text(encoding="utf-8")
    )
    assert users == ["semantic_target_source.py"]
