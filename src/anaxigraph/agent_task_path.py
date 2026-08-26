"""Build one bounded goal-specific path through the existing repository map."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.agent_lexicon import goal_artifact_type, goal_terms

TASK_PATH_VERSION = "task-path-v1"


def task_path(
    goal: str,
    preferred: dict[str, Any],
    primary_files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
    tests: list[str],
    hierarchy: list[dict[str, Any]],
) -> dict[str, Any]:
    """Connect a coding goal to one area, subsystem, file, and bounded symbol list."""

    if not preferred:
        return _empty_path(goal)
    selected = _task_module(goal, preferred, primary_files, symbols)
    placement = selected.get("architecture_placement") or _fallback_placement(selected)
    nodes = _hierarchy_nodes(hierarchy)
    area = _group_level("area", str(placement["area"]), placement, nodes)
    subsystem = _group_level("subsystem", str(placement["subsystem"]), placement, nodes)
    selected_symbols = _goal_symbols(goal, str(selected.get("path") or ""), symbols)
    result = {
        "contract_version": TASK_PATH_VERSION,
        "status": _status(placement, selected_symbols),
        "goal": goal,
        "area": area,
        "subsystem": subsystem,
        "module": _module_step(selected, tests),
        "symbols": selected_symbols,
        "nearby_files": _nearby_files(selected, primary_files),
    }
    result["plain_language"] = _explanation(result)
    return result


def compact_task_path(value: Any, *, route_only: bool = False) -> dict[str, Any]:
    """Keep the route usable when the wider scope response reaches its byte limit."""

    packet = value if isinstance(value, dict) else {}
    if route_only:
        return _route_only(packet)
    return {
        "contract_version": packet.get("contract_version"),
        "status": packet.get("status"),
        "area": _compact_level(packet.get("area")),
        "subsystem": _compact_level(packet.get("subsystem")),
        "module": _compact_module(packet.get("module")),
        "symbols": [
            {
                "name": symbol.get("name"),
                "type": symbol.get("type"),
                "signature": _text(symbol.get("signature"), 240),
            }
            for symbol in (packet.get("symbols") or [])[:5]
        ],
        "nearby_files": [
            {
                "path": item.get("path"),
                "reason": _text(item.get("reason"), 160),
            }
            for item in (packet.get("nearby_files") or [])[:5]
        ],
        "plain_language": {
            "conclusion": (packet.get("plain_language") or {}).get("conclusion"),
            "how_to_use_this": (packet.get("plain_language") or {}).get("how_to_use_this"),
        },
    }


def _empty_path(goal: str) -> dict[str, Any]:
    return {
        "contract_version": TASK_PATH_VERSION,
        "status": "no_starting_file",
        "goal": goal,
        "area": {},
        "subsystem": {},
        "module": {},
        "symbols": [],
        "nearby_files": [],
        "plain_language": {
            "version": TASK_PATH_VERSION,
            "conclusion": "AnaxiGraph could not tie this goal to a starting file.",
            "how_to_use_this": "Use a more specific behavior, file name, or code name in the goal.",
            "limits": "No repository-map route was invented without a matching file.",
        },
    }


def _group_level(
    level: str,
    key: str,
    placement: dict[str, Any],
    nodes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    node = nodes.get(key) or {}
    language = node.get("plain_language") or {}
    name_key = f"{level}_name"
    return {
        "key": key,
        "name": placement.get(name_key) or language.get("display_name") or _name(key),
        "responsibility": language.get("what_this_group_does")
        or node.get("responsibility")
        or node.get("description")
        or "The current map does not state this group's job.",
        "why_grouped": language.get("why_these_files_are_together")
        or node.get("description")
        or "The current map does not record why these files are grouped together.",
        "why_this_file_is_here": placement.get("why_here") or "No placement reason is available.",
        "source": placement.get("source") or node.get("source") or "unknown",
    }


def _module_step(preferred: dict[str, Any], tests: list[str]) -> dict[str, Any]:
    candidate = preferred.get("semantic") or {}
    semantic = (
        candidate if str(candidate.get("status") or "") in {"current", "intrinsic_current"} else {}
    )
    language = semantic.get("plain_language") or {}
    responsibilities = _strings(semantic.get("responsibilities"), 5)
    return {
        "path": str(preferred.get("path") or ""),
        "name": Path(str(preferred.get("path") or "file")).name,
        "purpose": language.get("what_this_file_does")
        or semantic.get("summary")
        or preferred.get("summary")
        or "No file purpose was recorded.",
        "responsibility": semantic.get("architecture_role")
        or (responsibilities[0] if responsibilities else preferred.get("summary"))
        or "No main responsibility was recorded.",
        "contracts_to_preserve": _strings(semantic.get("public_contracts"), 8),
        "extension_points": _strings(semantic.get("extension_points"), 8),
        "callers_to_check": _strings(preferred.get("incoming_paths"), 10),
        "dependencies_to_check": _strings(preferred.get("outgoing_paths"), 10),
        "focused_tests": [str(test)[:1_000] for test in tests[:10]],
    }


def _goal_symbols(goal: str, path: str, symbols: list[dict[str, Any]]) -> list[dict[str, Any]]:
    terms = _terms(goal)
    ranked = []
    for symbol in symbols:
        if str(symbol.get("path") or "") != path:
            continue
        matches = terms & _terms(
            " ".join(str(symbol.get(key) or "") for key in ("name", "signature", "summary"))
        )
        if matches:
            ranked.append((-len(matches), int(symbol.get("start_line") or 0), symbol, matches))
    return [
        {
            "name": str(symbol.get("name") or "")[:300],
            "type": str(symbol.get("symbol_type") or "")[:100],
            "signature": str(symbol.get("signature") or "")[:500],
            "start_line": int(symbol.get("start_line") or 0),
            "end_line": int(symbol.get("end_line") or 0),
            "why_relevant": f"Its name or signature matches: {', '.join(sorted(matches))}.",
        }
        for _, _, symbol, matches in sorted(ranked, key=lambda item: item[:2])[:8]
    ]


def _task_module(
    goal: str,
    preferred: dict[str, Any],
    primary_files: list[dict[str, Any]],
    symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    if str(preferred.get("artifact_type") or "") == goal_artifact_type(goal):
        return preferred
    terms = _terms(goal)
    scores: dict[str, int] = {}
    for symbol in symbols:
        path = str(symbol.get("path") or "")
        scores[path] = scores.get(path, 0) + len(
            terms
            & _terms(
                " ".join(str(symbol.get(key) or "") for key in ("name", "signature", "summary"))
            )
        )
    candidates = [item for item in primary_files if scores.get(str(item.get("path") or ""), 0)]
    if not candidates:
        return preferred
    return max(
        candidates,
        key=lambda item: (
            scores[str(item.get("path") or "")],
            -primary_files.index(item),
        ),
    )


def _nearby_files(
    preferred: dict[str, Any], primary_files: list[dict[str, Any]]
) -> list[dict[str, str]]:
    path = str(preferred.get("path") or "")
    values = [
        (str(item.get("path") or ""), "also matches the coding goal")
        for item in primary_files
        if item.get("path") != path
    ]
    values.extend(
        (value, "calls the selected file") for value in preferred.get("incoming_paths") or []
    )
    values.extend(
        (value, "is used by the selected file") for value in preferred.get("outgoing_paths") or []
    )
    return [
        {"path": candidate, "reason": reason}
        for candidate, reason in dict(values).items()
        if candidate
    ][:10]


def _explanation(result: dict[str, Any]) -> dict[str, str]:
    module = result["module"]
    symbols = result["symbols"]
    destination = symbols[0]["name"] if symbols else module["path"]
    area = result["area"]["name"]
    subsystem = result["subsystem"]["name"]
    return {
        "version": TASK_PATH_VERSION,
        "conclusion": (
            f"For this goal, follow {area} → {subsystem} → {module['path']} → {destination}."
        ),
        "how_to_use_this": (
            "Start at the named code part, then use the listed contracts, callers, dependencies, "
            "and tests to keep the change inside its intended boundary."
        ),
        "limits": (
            "This is a focused route through the saved map, not an instruction to edit every "
            "nearby file. Runtime-only links may still be missing."
        ),
    }


def _status(placement: dict[str, Any], symbols: list[dict[str, Any]]) -> str:
    source = str(placement.get("source") or "")
    mapping = (
        "semantic"
        if source.startswith("AI-created")
        else "policy"
        if source == "project path rule"
        else "inferred"
    )
    return f"{mapping}_with_symbols" if symbols else f"{mapping}_module_only"


def _fallback_placement(preferred: dict[str, Any]) -> dict[str, str]:
    group = str(preferred.get("declared_group") or preferred.get("inferred_group") or "ungrouped")
    return {
        "area": group,
        "area_name": _name(group),
        "subsystem": group,
        "subsystem_name": _name(group),
        "source": "file-path guess without AI",
        "why_here": "No current architecture placement was attached to this file.",
    }


def _hierarchy_nodes(hierarchy: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}

    def visit(item: dict[str, Any]) -> None:
        result[str(item.get("name") or "")] = item
        for child in item.get("children") or []:
            visit(child)

    for root in hierarchy:
        visit(root)
    return result


def _compact_level(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    return {
        "key": item.get("key"),
        "name": item.get("name"),
        "responsibility": _text(item.get("responsibility"), 240),
        "why_grouped": _text(item.get("why_grouped"), 240),
        "why_this_file_is_here": _text(item.get("why_this_file_is_here"), 240),
        "source": item.get("source"),
    }


def _compact_module(value: Any) -> dict[str, Any]:
    item = value if isinstance(value, dict) else {}
    return {
        "path": item.get("path"),
        "responsibility": _text(item.get("responsibility"), 240),
        "contracts_to_preserve": _short_strings(item.get("contracts_to_preserve"), 4),
        "extension_points": _short_strings(item.get("extension_points"), 4),
        "callers_to_check": _short_strings(item.get("callers_to_check"), 5),
        "dependencies_to_check": _short_strings(item.get("dependencies_to_check"), 5),
        "focused_tests": _short_strings(item.get("focused_tests"), 5),
    }


def _route_only(packet: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": packet.get("contract_version"),
        "status": packet.get("status"),
        "area": {"name": (packet.get("area") or {}).get("name")},
        "subsystem": {"name": (packet.get("subsystem") or {}).get("name")},
        "module": {"path": (packet.get("module") or {}).get("path")},
        "symbols": [{"name": symbol.get("name")} for symbol in (packet.get("symbols") or [])[:5]],
        "plain_language": {"conclusion": (packet.get("plain_language") or {}).get("conclusion")},
    }


def _terms(value: str) -> set[str]:
    return goal_terms(value)


def _strings(value: Any, limit: int) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item)[:1_000] for item in value if str(item).strip()][:limit]


def _short_strings(value: Any, limit: int) -> list[str]:
    return [_text(item, 240) for item in value[:limit]] if isinstance(value, list) else []


def _name(value: str) -> str:
    return value.replace("-", " ").replace("_", " ").title()


def _text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]
