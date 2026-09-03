"""Executable invariant: the stored module identity equals the analyzer's identity."""

from __future__ import annotations

import dataclasses
import json

import pytest

from anaxigraph.ir import module_identity
from anaxigraph.ir_serialization import _derived_identity

IDENTITY_CASES = [
    ("./src/pkg/__init__.py", "python"),
    ("pkg\\sub\\mod.py", "python"),
    ("app/x.py", "python"),
    ("lib/y/__init__.py", "python"),
    ("server/z.py", "python"),
    ("__init__.py", "python"),
    ("src/__init__.py", "python"),
    ("web/App.tsx", "typescript"),
    ("README.md", "markdown"),
]


@pytest.mark.parametrize(("path", "language"), IDENTITY_CASES)
def test_derived_identity_matches_module_identity(path: str, language: str) -> None:
    live = module_identity(path, language)
    stored_shape = json.loads(json.dumps(dataclasses.asdict(live)))

    assert _derived_identity(path, language) == stored_shape
