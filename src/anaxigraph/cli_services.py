"""Dependency composition root shared by CLI command modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.api import create_app
from anaxigraph.config import load_config
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.storage import AnaxiIndex
from anaxigraph.understanding import SemanticEngine

INDEX_FACTORY = AnaxiIndex
APP_FACTORY = create_app
CONFIG_LOADER = load_config


def open_index(path: Path) -> AnaxiIndex:
    return INDEX_FACTORY(path)


def scanner(database: AnaxiIndex) -> RepositoryScanner:
    return RepositoryScanner(database)


def load_repository_config(repository: Path, config_path: Path | None = None) -> Any:
    return CONFIG_LOADER(repository, config_path)


def semantics(database: AnaxiIndex) -> SemanticEngine:
    return SemanticEngine(database)
