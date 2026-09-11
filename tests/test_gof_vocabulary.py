"""The Gang of Four names are vocabulary, not a checklist to complete in code.

Several of these patterns exist because a language lacked something. Where the
language now supplies it, the card has to say so, or the catalogue turns into an
argument for machinery nobody needs.
"""

from __future__ import annotations

import pytest

from anaxigraph.pattern_catalog import bundled_pattern_catalog

GANG_OF_FOUR = (
    "Abstract Factory",
    "Builder",
    "Factory Method",
    "Prototype",
    "Singleton",
    "Adapter",
    "Bridge",
    "Composite",
    "Decorator",
    "Facade",
    "Flyweight",
    "Proxy",
    "Chain of Responsibility",
    "Command",
    "Interpreter",
    "Iterator",
    "Mediator",
    "Memento",
    "Observer",
    "State",
    "Strategy",
    "Template Method",
    "Visitor",
)


@pytest.fixture(scope="module")
def cards():
    return {card.name: card for card in bundled_pattern_catalog().cards}


def test_every_gang_of_four_name_can_be_recognised(cards):
    assert [name for name in GANG_OF_FOUR if name not in cards] == []


@pytest.mark.parametrize(
    ("name", "idiom"),
    [
        ("Builder", "keyword arguments"),
        ("Prototype", "copy"),
        ("Iterator", "generators"),
        ("Flyweight", "measurement"),
    ],
)
def test_a_pattern_the_language_already_supplies_says_so(cards, name, idiom):
    liabilities = " ".join(cards[name].liabilities).lower()

    assert idiom.lower() in liabilities


def test_singleton_is_catalogued_as_a_failure_mode_not_a_recommendation(cards):
    singleton = cards["Singleton"]

    assert singleton.kind == "failure_mode"
    assert "hides a dependency" in " ".join(singleton.liabilities)


def test_each_added_card_states_what_would_disprove_it(cards):
    for name in ("Builder", "Prototype", "Singleton", "Flyweight", "Iterator"):
        assert cards[name].counter_evidence, f"{name} has no counter-evidence"
        assert cards[name].verification_invariants, f"{name} has no verification invariant"
