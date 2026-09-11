"""One word can mean two things on purpose, and a rule belongs to somebody.

A responsibility map says which modules sit together. It does not say what a term
means where, or who owns an invariant. These optional fields record both when the
evidence establishes them, and stay absent when it does not.
"""

from __future__ import annotations

from anaxigraph.architecture_charter_contract import ARCHITECTURE_CHARTER_SCHEMA
from anaxigraph.architecture_charter_corrections import CORRECTABLE_SECTIONS
from anaxigraph.semantic_freshness import semantic_input_hash


def test_scoped_definitions_and_ownership_are_optional():
    assert "definitions" in ARCHITECTURE_CHARTER_SCHEMA["properties"]
    assert "definitions" not in ARCHITECTURE_CHARTER_SCHEMA["required"]
    claim = ARCHITECTURE_CHARTER_SCHEMA["properties"]["invariants"]["items"]
    assert "owner_scope" in claim["properties"]
    assert "owner_scope" not in claim["required"]


def test_a_definition_records_where_a_meaning_holds_and_where_it_does_not():
    definition = ARCHITECTURE_CHARTER_SCHEMA["properties"]["definitions"]["items"]

    assert set(definition["required"]) == {
        "term",
        "meaning",
        "scope",
        "evidence",
        "distinct_from",
    }
    assert "different thing" in definition["properties"]["distinct_from"]["description"]


def test_the_charter_asks_for_missing_domain_knowledge_rather_than_inventing_it():
    described = ARCHITECTURE_CHARTER_SCHEMA["properties"]["definitions"]["description"]

    assert "ask for the missing domain knowledge" in described
    assert "inventing a meaning from names" in described or "inventing" in described


def test_a_principal_can_declare_a_scoped_meaning():
    assert "definitions" in CORRECTABLE_SECTIONS


def test_adding_these_fields_does_not_invalidate_saved_charters():
    """They live in the response schema, never in the input identity."""

    first = semantic_input_hash("repository-synthesis-v1", "v1", {"r": 1})
    second = semantic_input_hash("repository-synthesis-v1", "v1", {"r": 1})

    assert first == second
