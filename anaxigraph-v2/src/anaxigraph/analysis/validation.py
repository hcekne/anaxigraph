"""Reject incomplete, oversized or ungrounded agent output before saving it."""

from __future__ import annotations

import json
from typing import Any

from anaxigraph.contracts import Graph


def _text(value: Any, field: str, limit: int = 1000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"{field} must be nonempty text of at most {limit} characters")
    return value.strip()


def _texts(value: Any, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > 30 or (required and not value):
        raise ValueError(f"{field} must be a bounded list of text")
    return [_text(item, field, 500) for item in value]


def _evidence(value: Any, graph: Graph, *, required: bool = False) -> None:
    if not isinstance(value, list) or len(value) > 30 or (required and not value):
        raise ValueError("Evidence must be a bounded list of source references")
    for reference in value:
        if not isinstance(reference, dict) or not isinstance(reference.get("path"), str):
            raise ValueError("Evidence path must be text")
        if reference["path"] not in graph.snapshot.files:
            raise ValueError("Evidence path must exist in the analyzed snapshot")
        if type(reference.get("line")) is not int or reference["line"] < 1:
            raise ValueError("Evidence line must be a positive integer")
        module = next(
            (n for n in graph.nodes if n.kind == "module" and n.path == reference["path"]), None
        )
        if module and reference["line"] > max(
            1, module.data.get("physical_lines", module.data.get("loc", 0))
        ):
            raise ValueError("Evidence line lies outside the mapped source file")


def _identities(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get(field), str) for item in value
    ):
        raise ValueError(f"Every item requires a text {field}")
    return [item[field] for item in value]


def validate_result(request: dict[str, Any], result: dict[str, Any], graph: Graph) -> None:
    """Validation establishes shape and coverage, not truth or model originality."""
    if not isinstance(result, dict) or len(json.dumps(result, allow_nan=False).encode()) > 262_144:
        raise ValueError("Analysis result must be a JSON object of at most 256 KiB")
    _text(result.get("producer"), "producer", 200)
    kind = request["kind"]
    if kind == "annotate":
        annotations = result.get("annotations")
        if not isinstance(annotations, list) or len(annotations) != len(request["scope"]):
            raise ValueError("Annotation result must cover every requested module exactly once")
        if set(_identities(annotations, "node_id")) != set(request["scope"]):
            raise ValueError("Annotation result has missing, duplicate or unexpected module IDs")
        for annotation in annotations:
            _text(annotation.get("overview"), "overview", 320)
            _text(annotation.get("detail"), "detail", 1500)
            _texts(annotation.get("capabilities"), "capabilities", required=True)
            _texts(annotation.get("uncertainty"), "uncertainty")
            functions = annotation.get("functions")
            expected = set(request["function_ids"][annotation["node_id"]])
            if not isinstance(functions, list) or len(functions) != len(expected):
                raise ValueError("Every supplied function needs exactly one overview sentence")
            if set(_identities(functions, "node_id")) != expected:
                raise ValueError("Function coverage contains missing or unexpected IDs")
            for function in functions:
                _text(function.get("overview"), "function overview", 320)
            contracts = annotation.get("contracts")
            if not isinstance(contracts, list) or len(contracts) > 30:
                raise ValueError("contracts must be a bounded list")
            for contract in contracts:
                if not isinstance(contract, dict):
                    raise ValueError("Each contract must be an object")
                _text(contract.get("statement"), "contract statement", 600)
                if not isinstance(contract.get("basis"), str) or contract["basis"] not in {
                    "declared",
                    "inferred",
                }:
                    raise ValueError("Contracts must distinguish declared from inferred basis")
                _evidence(contract.get("evidence"), graph, required=True)
    elif kind == "patterns":
        evaluations = result.get("evaluations")
        patterns = {card["id"] for card in request["packet"]["catalogue"]}
        expected_pairs = {(module, pattern) for module in request["scope"] for pattern in patterns}
        if not isinstance(evaluations, list) or len(evaluations) != len(expected_pairs):
            raise ValueError("Every requested module/catalogue pair must be evaluated exactly once")
        actual = set(
            zip(_identities(evaluations, "module_id"), _identities(evaluations, "pattern_id"))
        )
        if actual != expected_pairs:
            raise ValueError("Pattern coverage contains duplicate, missing or unexpected pairs")
        for evaluation in evaluations:
            score = evaluation.get("opportunity")
            if score is not None and (type(score) is not int or not 0 <= score <= 3):
                raise ValueError(
                    "Opportunity must be an integer 0–3 or null for insufficient evidence"
                )
            _texts(evaluation.get("pros"), "pros", required=True)
            _texts(evaluation.get("cons"), "cons", required=True)
            _text(evaluation.get("alternative"), "alternative", 600)
            _evidence(evaluation.get("evidence"), graph, required=bool(score))
            if score:
                if not isinstance(evaluation.get("current_fit"), str) or evaluation[
                    "current_fit"
                ] not in {"present", "partial", "absent", "unknown"}:
                    raise ValueError("Positive opportunities need an explicit current_fit")
                _text(evaluation.get("proposed_change"), "proposed_change", 1000)
    elif kind == "fresh-eyes":
        alternatives = result.get("alternatives")
        if not isinstance(alternatives, list) or len(alternatives) != 3:
            raise ValueError("Fresh Eyes requires three alternatives, retained independently")
        expected = {item["id"] for item in request["packet"]["requirements"]}
        designs = set()
        names = set()
        for alternative in alternatives:
            if not isinstance(alternative, dict):
                raise ValueError("Each alternative must be an object")
            names.add(_text(alternative.get("name"), "name", 160))
            designs.add(_text(alternative.get("design"), "design", 6000))
            coverage = alternative.get("requirements")
            if not isinstance(coverage, list) or any(not isinstance(x, str) for x in coverage):
                raise ValueError("Requirement coverage must be a list of requirement IDs")
            if (
                not isinstance(coverage, list)
                or len(coverage) != len(expected)
                or set(coverage) != expected
            ):
                raise ValueError("Each design must explicitly preserve every requirement")
            _texts(alternative.get("pros"), "pros", required=True)
            _texts(alternative.get("cons"), "cons", required=True)
            diagram = _text(alternative.get("diagram"), "diagram", 6000)
            if not diagram.startswith(("flowchart ", "graph ")):
                raise ValueError("Each alternative needs a high-level Mermaid flowchart")
        if len(names) != 3 or len(designs) != 3:
            raise ValueError("Alternatives must have distinct names and design descriptions")
    else:
        raise ValueError("Unknown analysis result kind")
