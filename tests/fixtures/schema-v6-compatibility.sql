CREATE TABLE file_versions (
    id INTEGER PRIMARY KEY,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    path TEXT NOT NULL,
    language TEXT NOT NULL,
    runtime TEXT,
    declared_group TEXT,
    inferred_group TEXT,
    raw_hash TEXT NOT NULL,
    structural_hash TEXT NOT NULL,
    lines_of_code INTEGER NOT NULL,
    comment_lines INTEGER NOT NULL,
    complexity REAL NOT NULL,
    summary TEXT NOT NULL,
    responsibilities_json TEXT NOT NULL DEFAULT '[]',
    inputs_json TEXT NOT NULL DEFAULT '[]',
    outputs_json TEXT NOT NULL DEFAULT '[]',
    side_effects_json TEXT NOT NULL DEFAULT '[]',
    public_interfaces_json TEXT NOT NULL DEFAULT '[]',
    analyzer TEXT NOT NULL,
    analysis_status TEXT NOT NULL,
    parse_error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_changed_at TEXT NOT NULL,
    UNIQUE(snapshot_id, artifact_id)
);

CREATE TABLE symbols (
    id INTEGER PRIMARY KEY,
    artifact_version_id INTEGER NOT NULL REFERENCES file_versions(id) ON DELETE CASCADE,
    symbol_type TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    start_line INTEGER NOT NULL,
    end_line INTEGER NOT NULL,
    signature TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    complexity REAL NOT NULL DEFAULT 1,
    logical_lines INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE relationships (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    source_artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    target_artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    target_external TEXT,
    relationship_type TEXT NOT NULL,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    source_line INTEGER NOT NULL DEFAULT 0,
    weight REAL NOT NULL DEFAULT 1,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK(target_artifact_id IS NOT NULL OR target_external IS NOT NULL)
);

CREATE TABLE group_memberships (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES groups(id) ON DELETE CASCADE,
    confidence REAL NOT NULL,
    evidence TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(snapshot_id, artifact_id, group_id)
);
