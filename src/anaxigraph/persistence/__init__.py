"""Narrow support facade for AnaxiIndex persistence internals."""

from anaxigraph.persistence.index_backup import (
    IndexBackup,
    backup_path,
    create_schema_backup,
    restore_schema_backup,
    validate_schema_backup,
)
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
from anaxigraph.relationships import (
    relationship_metadata,
    relationship_quality,
    resolution_status,
)

__all__ = [
    "SUPPORTED_SCHEMA_VERSIONS",
    "IndexBackup",
    "backup_path",
    "create_schema_backup",
    "initialize_index",
    "migrate_schema",
    "relationship_metadata",
    "relationship_quality",
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
