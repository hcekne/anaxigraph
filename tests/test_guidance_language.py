from __future__ import annotations

from anaxigraph.guidance import FINDING_VIEWS, OVERLAYS, product_glossary


def test_graph_help_explains_measurements_without_old_metric_jargon():
    copy = " ".join(OVERLAYS.values()).lower()

    for unexplained_label in (
        "modules",
        "high coupling",
        "metric overlay",
        "path/runtime inference",
        "static reachability",
        "architecture drift",
    ):
        assert unexplained_label not in copy
    assert "direct code links" in OVERLAYS["coupling"]
    assert "does not prove a defect" in OVERLAYS["drift"]


def test_public_glossary_defines_the_saved_index_and_finding_views_concretely():
    glossary = product_glossary()

    assert glossary["product"]["anaxi_index"].startswith("The saved index")
    assert "between sessions" in glossary["product"]["anaxi_index"]
    assert FINDING_VIEWS["attention"].startswith("A short list")
    assert "pages keep a large list manageable" in FINDING_VIEWS["diagnostics"]
    assert "not a code-quality grade" in glossary["file_measurements"]["complexity"]
    assert "not a grade for the code" in glossary["file_measurements"]["attention_score"]
