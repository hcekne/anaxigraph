"""Facade for intrinsic and contextual module semantic planning."""

from __future__ import annotations

import sqlite3
from typing import Any

from anaxigraph.semantic_config_port import SemanticConfig
from anaxigraph.semantic_module_context import plan_context_modules
from anaxigraph.semantic_module_intrinsic import plan_intrinsic_modules


class SemanticModulePlanner:
    def plan_intrinsic(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        relationships: dict[str, list[dict[str, Any]]],
        semantic: SemanticConfig,
        force: bool,
        retry_failed: bool,
    ) -> int:
        return plan_intrinsic_modules(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            relationships=relationships,
            semantic=semantic,
            force=force,
            retry_failed=retry_failed,
        )

    def plan_context(
        self,
        connection: sqlite3.Connection,
        *,
        repository_id: int,
        snapshot_id: int,
        inventory: dict[str, dict[str, Any]],
        relationships: dict[str, list[dict[str, Any]]],
        semantic: SemanticConfig,
        retry_failed: bool,
    ) -> int:
        return plan_context_modules(
            connection,
            repository_id=repository_id,
            snapshot_id=snapshot_id,
            inventory=inventory,
            relationships=relationships,
            semantic=semantic,
            retry_failed=retry_failed,
        )
