"""Translate validated declarative mappings into immutable pattern cards."""

from __future__ import annotations

from typing import Any

from anaxigraph.pattern_catalog_models import (
    PatternCard,
    PatternRelations,
    PatternScoringGuidance,
    _capabilities,
    _mapping,
    _scope_levels,
    _signals,
    _text,
    _texts,
)


def pattern_card_from_dict(value: Any) -> PatternCard:
    mapping = _mapping(value, "pattern card")
    return PatternCard(
        stable_key=str(mapping.get("stable_key") or ""),
        version=int(mapping.get("version") or 0),
        name=_text(mapping.get("name"), "pattern name"),
        family=str(mapping.get("family") or ""),
        kind=str(mapping.get("kind") or ""),
        intent=_text(mapping.get("intent"), "pattern intent"),
        scope_levels=_scope_levels(mapping.get("scope_levels")),
        problem_signals=_signals(mapping.get("problem_signals"), "problem signals"),
        required_capabilities=_capabilities(mapping.get("required_capabilities")),
        supporting_evidence=_signals(mapping.get("supporting_evidence"), "supporting evidence"),
        counter_evidence=_signals(mapping.get("counter_evidence"), "counter evidence"),
        semantic_questions=_texts(mapping.get("semantic_questions"), "semantic questions"),
        relations=PatternRelations.from_dict(mapping.get("relations")),
        scoring=PatternScoringGuidance.from_dict(mapping.get("scoring")),
        benefits=_texts(mapping.get("benefits"), "pattern benefits"),
        liabilities=_texts(mapping.get("liabilities"), "pattern liabilities"),
        migration_cautions=_texts(mapping.get("migration_cautions"), "migration cautions"),
        verification_invariants=_texts(
            mapping.get("verification_invariants"), "verification invariants"
        ),
        references=_texts(mapping.get("references"), "pattern references"),
        schema_version=str(mapping.get("schema_version") or ""),
    )
