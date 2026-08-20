#!/usr/bin/env python3
"""Report high-confidence cohesion risks from current module dossiers."""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_POLICY = Path("quality/semantic-cohesion-policy.json")


@dataclass(frozen=True, slots=True)
class CohesionIssue:
    path: str
    issue_type: str
    confidence: float
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.issue_type,
            "confidence": self.confidence,
            "message": self.message,
        }


def cohesion_issues(dossiers: list[dict[str, Any]], policy: dict[str, Any]) -> list[CohesionIssue]:
    """Turn semantic evidence into review prompts, never automatic refactors."""

    issues: list[CohesionIssue] = []
    minimum_confidence = float(policy["minimum_confidence"])
    responsibility_warning = int(policy["responsibility_warning"])
    split_score = int(policy["split_score_warning"])
    for dossier in dossiers:
        confidence = float(dossier.get("confidence") or 0)
        if confidence < minimum_confidence:
            continue
        value = dossier.get("value") or {}
        responsibilities = value.get("responsibilities") or []
        if len(responsibilities) > responsibility_warning:
            issues.append(
                CohesionIssue(
                    str(dossier["path"]),
                    "responsibility_breadth",
                    confidence,
                    f"dossier records {len(responsibilities)} responsibilities; review whether "
                    "they change for independent reasons",
                )
            )
        consolidation = value.get("consolidation_assessment") or {}
        score = int(consolidation.get("score") or 0)
        recommendation = str(consolidation.get("recommendation") or "").lower()
        if recommendation == "split" and score >= split_score:
            issues.append(
                CohesionIssue(
                    str(dossier["path"]),
                    "semantic_split_candidate",
                    confidence,
                    f"dossier recommends a split at {score}/100; require human review of its "
                    "evidence and counter-evidence before planning work",
                )
            )
    return sorted(issues, key=lambda item: (item.path, item.issue_type))


def load_current_dossiers(database: Path) -> list[dict[str, Any]]:
    uri = f"file:{database.expanduser().resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT fv.path, sd.confidence, sd.value_json
            FROM semantic_scope_states ss
            JOIN file_versions fv ON fv.id = ss.artifact_version_id
            JOIN semantic_documents sd
              ON sd.id = COALESCE(ss.context_document_id, ss.intrinsic_document_id)
            WHERE ss.scope_type = 'module' AND ss.status = 'current'
            ORDER BY fv.path
            """
        ).fetchall()
    return [
        {
            "path": str(row["path"]),
            "confidence": float(row["confidence"]),
            "value": json.loads(row["value_json"]),
        }
        for row in rows
    ]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--strict", action="store_true", help="Fail when review signals exist")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    policy = json.loads(args.policy.read_text(encoding="utf-8"))
    issues = cohesion_issues(load_current_dossiers(args.database), policy)
    if args.json:
        print(json.dumps({"issues": [item.as_dict() for item in issues]}))
    else:
        for item in issues:
            print(f"WARNING: {item.path} — {item.message} ({item.confidence:.0%} confidence)")
        print(f"Semantic-cohesion report: {len(issues)} review signal(s).")
    return 1 if args.strict and issues else 0


if __name__ == "__main__":
    raise SystemExit(main())
