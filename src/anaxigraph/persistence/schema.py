"""Versioned AnaxiIndex compatibility schema installed before explicit migrations."""

SCHEMA_VERSION = 11

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    remote_url TEXT,
    default_branch TEXT,
    current_snapshot_id INTEGER,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    parent_commit_sha TEXT,
    branch TEXT NOT NULL,
    commit_timestamp TEXT,
    analysis_timestamp TEXT NOT NULL,
    content_fingerprint TEXT NOT NULL,
    snapshot_kind TEXT NOT NULL DEFAULT 'working_tree',
    dirty INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(repository_id, content_fingerprint)
);

CREATE TABLE IF NOT EXISTS artifacts (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    canonical_path TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    first_seen_commit TEXT,
    deleted_commit TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(repository_id, canonical_path)
);

CREATE TABLE IF NOT EXISTS groups (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    parent_name TEXT,
    source TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    UNIQUE(repository_id, name, source)
);

CREATE TABLE IF NOT EXISTS metrics (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    name TEXT NOT NULL,
    value REAL NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS coverage_measurements (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    relationship_edge_id INTEGER REFERENCES relationship_edges(id) ON DELETE CASCADE,
    provider TEXT NOT NULL,
    line_coverage REAL,
    branch_coverage REAL,
    function_coverage REAL,
    covered_lines INTEGER,
    total_lines INTEGER,
    evidence TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    stable_key TEXT NOT NULL,
    finding_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    confidence REAL NOT NULL,
    summary TEXT NOT NULL,
    explanation TEXT NOT NULL,
    affected_artifacts_json TEXT NOT NULL DEFAULT '[]',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    recommended_action TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'deterministic',
    status TEXT NOT NULL DEFAULT 'new',
    first_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    last_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
    first_detected_at TEXT NOT NULL,
    last_detected_at TEXT NOT NULL,
    resolved_at TEXT,
    UNIQUE(repository_id, stable_key)
);

CREATE TABLE IF NOT EXISTS finding_occurrences (
    finding_id INTEGER NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    detected_at TEXT NOT NULL,
    evidence_json TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY(finding_id, snapshot_id)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER REFERENCES snapshots(id) ON DELETE SET NULL,
    run_type TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    analyzed_count INTEGER NOT NULL DEFAULT 0,
    reused_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE TABLE IF NOT EXISTS architecture_rules (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    rule_id TEXT NOT NULL,
    rule_type TEXT NOT NULL,
    severity TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    enabled INTEGER NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    UNIQUE(repository_id, rule_id)
);

CREATE TABLE IF NOT EXISTS semantic_claims (
    id INTEGER PRIMARY KEY,
    artifact_version_id INTEGER,
    file_fact_id INTEGER NOT NULL REFERENCES file_facts(id) ON DELETE CASCADE,
    claim_type TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    executor_id TEXT,
    executor_model TEXT,
    prompt_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS semantic_documents (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER,
    file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
    previous_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    document_kind TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    intent_fingerprint TEXT NOT NULL,
    value_json TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    confidence REAL NOT NULL,
    supporting_evidence_json TEXT NOT NULL DEFAULT '[]',
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    usage_source TEXT NOT NULL DEFAULT 'unknown',
    executor_effort TEXT,
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS semantic_jobs (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER,
    file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
    job_kind TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 0,
    input_hash TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    estimated_input_tokens INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    usage_source TEXT NOT NULL DEFAULT 'unknown',
    estimated_cost_usd REAL,
    actual_cost_usd REAL,
    available_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    worker_id TEXT,
    lease_expires_at TEXT,
    lease_token_hash TEXT,
    executor_id TEXT,
    executor_model TEXT,
    executor_effort TEXT,
    error TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS semantic_scope_states (
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    scope_type TEXT NOT NULL,
    scope_key TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifacts(id) ON DELETE CASCADE,
    artifact_version_id INTEGER,
    file_fact_id INTEGER REFERENCES file_facts(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    intrinsic_input_hash TEXT,
    context_input_hash TEXT,
    interface_hash TEXT,
    relationship_hash TEXT,
    context_fingerprint TEXT,
    intrinsic_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    context_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    last_checked_at TEXT NOT NULL,
    PRIMARY KEY(snapshot_id, scope_type, scope_key)
);

CREATE TABLE IF NOT EXISTS semantic_taxonomies (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    input_hash TEXT NOT NULL,
    status TEXT NOT NULL,
    source TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    executor_id TEXT,
    executor_model TEXT,
    prompt_version TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0,
    candidate_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    final_document_id INTEGER REFERENCES semantic_documents(id) ON DELETE SET NULL,
    review_passes INTEGER NOT NULL DEFAULT 0,
    validation_json TEXT NOT NULL DEFAULT '{}',
    facets_json TEXT NOT NULL DEFAULT '[]',
    change_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(snapshot_id, input_hash)
);

CREATE TABLE IF NOT EXISTS semantic_taxonomy_nodes (
    taxonomy_id INTEGER NOT NULL REFERENCES semantic_taxonomies(id) ON DELETE CASCADE,
    node_key TEXT NOT NULL,
    name TEXT NOT NULL,
    level TEXT NOT NULL,
    parent_key TEXT,
    description TEXT NOT NULL DEFAULT '',
    responsibility TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    counter_evidence_json TEXT NOT NULL DEFAULT '[]',
    display_order INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(taxonomy_id, node_key)
);

CREATE TABLE IF NOT EXISTS semantic_taxonomy_memberships (
    taxonomy_id INTEGER NOT NULL REFERENCES semantic_taxonomies(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    node_key TEXT NOT NULL,
    confidence REAL NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    locked INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(taxonomy_id, artifact_id),
    FOREIGN KEY(taxonomy_id, node_key)
        REFERENCES semantic_taxonomy_nodes(taxonomy_id, node_key) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS semantic_taxonomy_reviews (
    taxonomy_id INTEGER NOT NULL REFERENCES semantic_taxonomies(id) ON DELETE CASCADE,
    pass_index INTEGER NOT NULL,
    document_id INTEGER NOT NULL REFERENCES semantic_documents(id) ON DELETE CASCADE,
    verdict TEXT NOT NULL,
    issues_json TEXT NOT NULL DEFAULT '[]',
    validation_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(taxonomy_id, pass_index)
);

CREATE TABLE IF NOT EXISTS git_changes (
    id INTEGER PRIMARY KEY,
    repository_id INTEGER NOT NULL REFERENCES repositories(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL,
    committed_at TEXT,
    author_name TEXT,
    subject TEXT,
    path TEXT NOT NULL,
    change_type TEXT NOT NULL,
    additions INTEGER,
    deletions INTEGER,
    UNIQUE(repository_id, commit_sha, path)
);

CREATE INDEX IF NOT EXISTS idx_snapshots_repository ON snapshots(repository_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_artifacts_repository ON artifacts(repository_id, canonical_path);
CREATE INDEX IF NOT EXISTS idx_metrics_snapshot ON metrics(snapshot_id, name);
CREATE INDEX IF NOT EXISTS idx_findings_repository_status ON findings(repository_id, status);
CREATE INDEX IF NOT EXISTS idx_git_changes_repository_path ON git_changes(repository_id, path);
CREATE INDEX IF NOT EXISTS idx_semantic_documents_scope
    ON semantic_documents(repository_id, scope_type, scope_key, document_kind, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_jobs_queue
    ON semantic_jobs(repository_id, status, available_at, priority DESC, id);
CREATE INDEX IF NOT EXISTS idx_semantic_states_snapshot
    ON semantic_scope_states(snapshot_id, scope_type, status);
CREATE INDEX IF NOT EXISTS idx_semantic_taxonomies_snapshot
    ON semantic_taxonomies(snapshot_id, status, id DESC);
CREATE INDEX IF NOT EXISTS idx_semantic_taxonomy_memberships_node
    ON semantic_taxonomy_memberships(taxonomy_id, node_key);
"""
