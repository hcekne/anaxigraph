"""Coverage.py XML and LCOV adapters, including conservative edge coverage."""

from __future__ import annotations

import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from codeintel.config import CodeIntelConfig


@dataclass(frozen=True, slots=True)
class CoverageRecord:
    path: str
    provider: str
    line_coverage: float | None
    branch_coverage: float | None
    covered_lines: int | None
    total_lines: int | None
    evidence: str


def collect_coverage(
    connection: sqlite3.Connection,
    *,
    root: Path,
    config: CodeIntelConfig,
    snapshot_id: int,
    artifacts_by_path: dict[str, int],
) -> int:
    records: list[CoverageRecord] = []
    for configured in config.coverage_files:
        path = Path(configured)
        candidate = path if path.is_absolute() else root / path
        if not candidate.is_file():
            continue
        try:
            if candidate.suffix.lower() == ".xml":
                records.extend(_coverage_xml(candidate))
            elif candidate.name == "lcov.info" or candidate.suffix.lower() == ".info":
                records.extend(_lcov(candidate, root))
        except (OSError, ValueError, ET.ParseError):
            continue

    inserted = 0
    seen: set[tuple[int, str]] = set()
    for record in records:
        resolved = _resolve_path(record.path, artifacts_by_path, root)
        if resolved is None:
            continue
        artifact_id = artifacts_by_path[resolved]
        key = (artifact_id, record.provider)
        if key in seen:
            continue
        seen.add(key)
        connection.execute(
            """
            INSERT INTO coverage_measurements(
                snapshot_id, artifact_id, provider, line_coverage, branch_coverage,
                covered_lines, total_lines, evidence
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                artifact_id,
                record.provider,
                record.line_coverage,
                record.branch_coverage,
                record.covered_lines,
                record.total_lines,
                record.evidence,
            ),
        )
        inserted += 1
    inserted += _relationship_coverage(connection, snapshot_id)
    return inserted


def _coverage_xml(path: Path) -> list[CoverageRecord]:
    root = ET.parse(path).getroot()
    result: list[CoverageRecord] = []
    for class_node in root.findall(".//class"):
        filename = class_node.attrib.get("filename")
        if not filename:
            continue
        lines = class_node.findall("./lines/line")
        total = len(lines)
        covered = sum(1 for line in lines if int(line.attrib.get("hits", "0")) > 0)
        line_rate = class_node.attrib.get("line-rate")
        branch_rate = class_node.attrib.get("branch-rate")
        result.append(
            CoverageRecord(
                path=filename.replace("\\", "/"),
                provider="coverage.py-xml",
                line_coverage=float(line_rate) if line_rate is not None else _ratio(covered, total),
                branch_coverage=float(branch_rate) if branch_rate is not None else None,
                covered_lines=covered,
                total_lines=total,
                evidence=str(path),
            )
        )
    return result


def _lcov(path: Path, root: Path) -> list[CoverageRecord]:
    result: list[CoverageRecord] = []
    current: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line == "end_of_record":
            if current.get("SF"):
                source = Path(current["SF"])
                try:
                    source_path = str(source.resolve().relative_to(root.resolve()))
                except (ValueError, OSError):
                    source_path = current["SF"]
                total = _integer(current.get("LF"))
                covered = _integer(current.get("LH"))
                branch_total = _integer(current.get("BRF"))
                branch_covered = _integer(current.get("BRH"))
                result.append(
                    CoverageRecord(
                        path=source_path.replace("\\", "/"),
                        provider="lcov",
                        line_coverage=_ratio(covered, total),
                        branch_coverage=_ratio(branch_covered, branch_total),
                        covered_lines=covered,
                        total_lines=total,
                        evidence=str(path),
                    )
                )
            current = {}
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            if key in {"SF", "LF", "LH", "BRF", "BRH"}:
                current[key] = value
    return result


def _integer(value: str | None) -> int | None:
    return int(value) if value and value.isdigit() else None


def _ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or not denominator:
        return None
    return numerator / denominator


def _resolve_path(path: str, artifacts: dict[str, int], root: Path) -> str | None:
    normalized = path.replace("\\", "/").lstrip("./")
    if normalized in artifacts:
        return normalized
    try:
        absolute = str(Path(path).resolve().relative_to(root.resolve())).replace("\\", "/")
        if absolute in artifacts:
            return absolute
    except (ValueError, OSError):
        pass
    matches = [candidate for candidate in artifacts if candidate.endswith(f"/{normalized}")]
    return matches[0] if len(matches) == 1 else None


def _relationship_coverage(connection: sqlite3.Connection, snapshot_id: int) -> int:
    artifact_types = {
        int(row["id"]): row["artifact_type"]
        for row in connection.execute(
            """
            SELECT a.id, a.artifact_type FROM artifacts a
            JOIN file_versions fv ON fv.artifact_id = a.id
            WHERE fv.snapshot_id = ?
            """,
            (snapshot_id,),
        )
    }
    test_targets: dict[int, set[int]] = {}
    relationships = connection.execute(
        """
        SELECT id, source_artifact_id, target_artifact_id FROM relationships
        WHERE snapshot_id = ? AND target_artifact_id IS NOT NULL
        """,
        (snapshot_id,),
    ).fetchall()
    for row in relationships:
        source = int(row["source_artifact_id"])
        target = int(row["target_artifact_id"])
        if artifact_types.get(source) == "test":
            test_targets.setdefault(source, set()).add(target)
    inserted = 0
    for row in relationships:
        source = int(row["source_artifact_id"])
        target = int(row["target_artifact_id"])
        if artifact_types.get(source) == "test":
            continue
        proving_tests = [
            test_id for test_id, targets in test_targets.items() if {source, target} <= targets
        ]
        if not proving_tests:
            continue
        connection.execute(
            """
            INSERT INTO coverage_measurements(
                snapshot_id, relationship_id, provider, line_coverage, evidence
            ) VALUES (?, ?, 'static-test-graph', 1.0, ?)
            """,
            (
                snapshot_id,
                int(row["id"]),
                "A test module statically references both relationship endpoints: "
                + ", ".join(str(item) for item in proving_tests[:10]),
            ),
        )
        inserted += 1
    return inserted
