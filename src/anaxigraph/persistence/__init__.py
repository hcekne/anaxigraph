"""Narrow support facade for AnaxiIndex persistence internals."""

from anaxigraph.persistence.index_backup import (
    IndexBackup,
    backup_path,
    create_schema_backup,
    restore_schema_backup,
    validate_schema_backup,
)
from anaxigraph.persistence.index_doctor import inspect_index
from anaxigraph.persistence.index_initialization import initialize_index
from anaxigraph.persistence.migrations import (
    SUPPORTED_SCHEMA_VERSIONS,
    migrate_schema,
    transactional_schema_change,
    validate_schema_version,
)
from anaxigraph.persistence.temporal_facts import temporal_counts
from anaxigraph.persistence.temporal_reads import (
    snapshot_files,
    snapshot_relationship_edges,
    snapshot_symbols,
)
from anaxigraph.persistence.temporal_reconstruction import (
    CHECKPOINT_INTERVAL,
    CHECKPOINT_POLICY_VERSION,
    ReconstructionDiagnostics,
    canonical_state_hashes,
    ensure_checkpoint_policy,
    rebuild_checkpoints,
    reconstruct_files_with_diagnostics,
    reconstruct_relationships_with_diagnostics,
)
from anaxigraph.relationships import (
    relationship_metadata,
    relationship_quality,
    resolution_status,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "CHECKPOINT_INTERVAL",
    "CHECKPOINT_POLICY_VERSION",
    "IndexBackup",
    "ReconstructionDiagnostics",
    "ensure_checkpoint_policy",
    "backup_path",
    "canonical_state_hashes",
    "create_schema_backup",
    "initialize_index",
    "inspect_index",
    "migrate_schema",
    "relationship_metadata",
    "relationship_quality",
    "rebuild_checkpoints",
    "reconstruct_files_with_diagnostics",
    "reconstruct_relationships_with_diagnostics",
    "resolution_status",
    "restore_schema_backup",
    "snapshot_files",
    "snapshot_relationship_edges",
    "snapshot_symbols",
    "temporal_counts",
    "transactional_schema_change",
    "validate_schema_backup",
    "validate_schema_version",
]
