"""Archive lookup keeps immutable reruns even without their original job manifests."""

import json

from saved_fresh_eyes_support import seed_legacy_review

from anaxigraph.scanner import RepositoryScanner
from anaxigraph.understanding import SemanticEngine


def test_orphaned_legacy_reruns_remain_accessible_with_unknown_generation_label(
    repository, database
):
    stats = RepositoryScanner(database).scan(repository)
    original = seed_legacy_review(database, stats.repository_id, stats.snapshot_id, grounding=False)
    with database.transaction() as connection:
        row = dict(
            connection.execute(
                "SELECT * FROM semantic_documents WHERE id=?", (original["review"],)
            ).fetchone()
        )
        row.pop("id")
        value = json.loads(row["value_json"])
        value["summary"] = "Original orphaned rerun, not a recomputed conclusion."
        row.update(
            input_hash="orphaned-review-input",
            value_json=json.dumps(value),
            executor_model="retained-historical-model",
        )
        columns = list(row)
        extra = connection.execute(
            f"INSERT INTO semantic_documents({','.join(columns)}) VALUES({','.join('?' for _ in columns)})",
            tuple(row.values()),
        ).lastrowid
        connection.execute(
            "UPDATE semantic_scope_states SET interface_hash='functional-v2|3:2' WHERE scope_type='fresh_eyes' AND scope_key='plan'"
        )
    with database.connect() as connection:
        before = [
            tuple(row) for row in connection.execute("SELECT * FROM semantic_documents ORDER BY id")
        ]
    engine = SemanticEngine(database)
    archive = engine.fresh_eyes_status(stats.repository_id, generation=1, details=True)
    assert archive["state"] == "archived"
    assert archive["generation_inferred"] is True
    assert any(
        "original generation number was not retained" in caveat for caveat in archive["caveats"]
    )
    records = {item["id"]: item for item in archive["archive"]["documents"]}
    assert set(original.values()) | {extra} == records.keys()
    assert records[extra]["value"] == value
    assert records[extra]["executor_model"] == "retained-historical-model"
    assert archive["strategy"] == records[original["review"]]["value"]
    compact = engine.fresh_eyes_status(stats.repository_id, generation=1, details=False)
    assert set(compact["archive"]["document_ids"]) == records.keys()
    with database.connect() as connection:
        assert [
            tuple(row) for row in connection.execute("SELECT * FROM semantic_documents ORDER BY id")
        ] == before
