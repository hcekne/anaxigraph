"""Narrow support facade for AnaxiIndex persistence internals."""

from anaxigraph.persistence.index_backup import (
    IndexBackup,
    backup_path,
    create_schema_backup,
    restore_schema_backup,
    validate_schema_backup,
)
from anaxigraph.persistence.migrations import (
    SUPPORTED_SCHEMA_VERSIONS,
    migrate_schema,
    transactional_schema_change,
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
    "migrate_schema",
    "relationship_metadata",
    "relationship_quality",
    "resolution_status",
    "restore_schema_backup",
    "transactional_schema_change",
    "validate_schema_backup",
]
