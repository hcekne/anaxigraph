"""Repository selection and core read/planning tools for AnaxiMCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from anaxigraph.agent import architecture_guidance, impact_analysis
from anaxigraph.architecture_charter import architecture_charter
from anaxigraph.architecture_guidance import AGENT_JOURNEY_VERSION, agent_journey_manifest
from anaxigraph.architecture_reassessment import architecture_reassessment
from anaxigraph.config import load_config
from anaxigraph.config_authority import effective_semantic_policy, service_config_authority
from anaxigraph.operational_health import served_map_status
from anaxigraph.scanner import RepositoryScanner
from anaxigraph.semantic_mcp import current_semantic_status
from anaxigraph.semantic_scan_refresh import semantic_refresh_after_scan
from anaxigraph.understanding import SemanticEngine

_GUIDE_JOURNEYS = frozenset({"understand", "build", "improve", "refactor", "redesign", "reassess"})


class McpToolContext:
    def __init__(
        self,
        database: Any,
        repository: Path | None,
        config_path: Path | None,
        repository_targets: tuple[Any, ...],
    ) -> None:
        self.database = database
        self.repository = repository
        self.config_path = config_path
        self.targets_by_path = {str(target.path.resolve()): target for target in repository_targets}

    def visible_repositories(self) -> list[dict[str, Any]]:
        rows = self.database.repositories()
        if self.targets_by_path:
            rows = [row for row in rows if str(Path(row["path"]).resolve()) in self.targets_by_path]
        return rows

    def select(self, selector: str = "") -> tuple[dict[str, Any], Path]:
        if selector:
            row = self.database.repository(int(selector) if selector.isdigit() else selector)
        else:
            row = (
                self.database.repository(self.repository)
                if self.repository
                else self.database.repository()
            )
        if row is None:
            raise ValueError("No analyzed repository is configured. Run anaxigraph scan first.")
        if self.targets_by_path and str(Path(row["path"]).resolve()) not in self.targets_by_path:
            raise ValueError("Repository is not in the active AnaxiGraph registry.")
        return row, Path(row["path"])

    def config_for(self, row: dict[str, Any], root: Path) -> Any:
        target = self.targets_by_path.get(str(root.resolve()))
        return load_config(root, target.config_path if target else self.config_path)

    def semantic_config_contract(
        self, row: dict[str, Any], root: Path, config: Any
    ) -> dict[str, Any]:
        target = self.targets_by_path.get(str(root.resolve()))
        return {
            "config_authority": service_config_authority(root, target, config),
            "semantic_policy": effective_semantic_policy(config.semantic),
        }

    def map_status(self, row: dict[str, Any], root: Path) -> dict[str, Any]:
        snapshot = self.database.latest_snapshot(int(row["id"]))
        if snapshot is None:
            raise ValueError("Repository has not been scanned")
        return served_map_status(root, snapshot)


class CoreMcpTools:
    def __init__(self, server: Any, context: McpToolContext, *, allow_scan: bool) -> None:
        self.server = server
        self.context = context
        self.database = context.database
        self.allow_scan = allow_scan

    def register(self) -> None:
        self._register_inventory_tools()
        self._register_agent_tools()
        if self.allow_scan:
            self.server.add_tool(
                self.scan,
                name="ANAXIGRAPH_SCAN",
                description=(
                    "Read the configured repository again and save a new code map. Repository "
                    "files stay read-only; only AnaxiGraph's external index changes. Set "
                    "refresh_semantics=true after an edit to prepare only file meanings whose "
                    "code fingerprints or architectural context changed."
                ),
            )

    def _register_inventory_tools(self) -> None:
        for handler, name, description in (
            (
                self.repositories,
                "ANAXIGRAPH_REPOSITORIES",
                "List indexed repositories and selectors for other AnaxiGraph tools.",
            ),
            (
                self.overview,
                "ANAXIGRAPH_OVERVIEW",
                "Summarize repository size, languages, code areas, test coverage, and finding counts.",
            ),
            (
                self.search,
                "ANAXIGRAPH_SEARCH",
                "Find files and named code parts that are most relevant to a concept or feature.",
            ),
            (
                self.file_details,
                "ANAXIGRAPH_FILE",
                "Inspect one file: what it does, direct links to other files, Git history, named code parts, saved AI description, evidence, and who or what created that description.",
            ),
        ):
            self.server.add_tool(handler, name=name, description=description)

    def _register_agent_tools(self) -> None:
        self.server.add_tool(
            self.guidance,
            name="ANAXIGRAPH_GUIDE",
            description=(
                "Use one of five intents: understand the system, build a capability, improve "
                "existing structure, redesign from a behavior-only capability brief, or reassess "
                "a completed edit. Build and improve return placement, affected code, reasons not "
                "to change, focused checks, and exact next actions. Redesign uses the fixed "
                "fresh-eyes review; reassess compares compatible before and after maps."
            ),
        )
        self.server.add_tool(
            self.impact,
            name="ANAXIGRAPH_IMPACT",
            description=(
                "Before changing a file or named code part, find code that uses it directly or "
                "indirectly, relevant tests, possible database changes, files marked for extra "
                "care, and reasons the change may be risky."
            ),
        )

    def repositories(self) -> dict[str, Any]:
        targets = self.context.targets_by_path
        return {
            "contract_version": "anaxigraph-agent-tools-v2",
            "agent_workflow": agent_journey_manifest(),
            "repositories": [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "path": row["path"],
                    "remote_url": row.get("remote_url"),
                    "scannable": str(Path(row["path"]).resolve()) in targets,
                    "map_status": self.context.map_status(row, Path(row["path"])),
                }
                for row in self.context.visible_repositories()
            ],
        }

    def overview(self, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        result = self.database.overview(int(row["id"]))
        result["map_status"] = self.context.map_status(row, root)
        config = self.context.config_for(row, root)
        semantic = current_semantic_status(self.database, int(row["id"]), config.semantic)
        semantic.update(self.context.semantic_config_contract(row, root, config))
        result["semantic"] = semantic
        result["architecture_charter"] = architecture_charter(row, result, semantic)
        return result

    def search(self, query: str, limit: int = 20, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        bounded = max(1, min(limit, 50))
        return {
            "query": query,
            "results": self.database.search(int(row["id"]), query, limit=bounded),
            "map_status": self.context.map_status(row, root),
        }

    def file_details(self, path: str, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        result = self.database.file_details(int(row["id"]), _safe_relative_path(path))
        if result is None:
            raise ValueError(f"File is not present in the current saved scan: {path}")
        result["map_status"] = self.context.map_status(row, root)
        return result

    def guidance(
        self,
        goal: str = "",
        intent: str = "build",
        focus: str = "",
        repository: str = "",
        fresh_eyes: bool = False,
        start: bool = False,
        proposal_count: int = 2,
        retry_failed: bool = False,
        reassess: bool = False,
        from_snapshot_id: int | None = None,
    ) -> dict[str, Any]:
        row, root = self.context.select(repository)
        config = self.context.config_for(row, root)
        selected, redesign, compare = _guide_selection(intent, fresh_eyes, reassess)
        if selected == "understand":
            return self._understand_journey(repository)
        if redesign:
            return self._redesign_journey(
                row, root, config, goal, start, proposal_count, retry_failed
            )
        if compare:
            return self._reassess_journey(row, config, goal, from_snapshot_id)
        if not goal.strip():
            raise ValueError("goal is required for build or improve guidance")
        return architecture_guidance(
            self.database,
            repository_id=int(row["id"]),
            goal=goal,
            config=config,
            intent=intent,
            focus=focus,
        )

    def _redesign_journey(
        self,
        row: dict[str, Any],
        root: Path,
        config: Any,
        goal: str,
        start: bool,
        proposal_count: int,
        retry_failed: bool,
    ) -> dict[str, Any]:
        engine = SemanticEngine(self.database)
        result = (
            engine.start_fresh_eyes_review(
                int(row["id"]),
                root,
                config,
                proposal_count=proposal_count,
                retry_failed=retry_failed,
            )
            if start
            else engine.fresh_eyes_status(int(row["id"]), config.semantic)
        )
        return _journey_result(result, "redesign", goal)

    def _reassess_journey(
        self,
        row: dict[str, Any],
        config: Any,
        goal: str,
        from_snapshot_id: int | None,
    ) -> dict[str, Any]:
        result = architecture_reassessment(
            self.database,
            repository_id=int(row["id"]),
            config=config,
            from_snapshot_id=from_snapshot_id,
            goal=goal,
        )
        return _journey_result(result, "reassess", goal)

    def _understand_journey(self, repository: str) -> dict[str, Any]:
        result = self.overview(repository)
        result["agent_journey"] = {
            "contract_version": AGENT_JOURNEY_VERSION,
            "intent": "understand",
            "current_step": "understand",
            "next_action": {
                "tool": "ANAXIGRAPH_GUIDE",
                "arguments": {"intent": "build", "goal": "<describe one coding goal>"},
                "reason": "Turn the repository-wide map into one bounded implementation decision.",
            },
        }
        return result

    def impact(self, target: str, repository: str = "") -> dict[str, Any]:
        row, root = self.context.select(repository)
        return impact_analysis(
            self.database,
            repository_id=int(row["id"]),
            target=target,
            config=self.context.config_for(row, root),
        )

    def scan(
        self,
        repository: str = "",
        refresh_semantics: bool | None = None,
    ) -> dict[str, Any]:
        row, root = self.context.select(repository)
        target = self.context.targets_by_path.get(str(root.resolve()))
        if target is None and self.context.targets_by_path:
            raise ValueError("Repository is indexed but is not a configured scan target")
        selected_config = target.config_path if target else self.context.config_path
        baseline = self.database.latest_snapshot(int(row["id"]))
        stats = RepositoryScanner(self.database).scan(root, config_path=selected_config)
        config = self.context.config_for(row, root)
        semantic = semantic_refresh_after_scan(
            self.database,
            repository_id=stats.repository_id,
            repository=root,
            snapshot_id=stats.snapshot_id,
            baseline_snapshot_id=int(baseline["id"]) if baseline else None,
            config=config,
            prepare=refresh_semantics,
        )
        return {**stats.as_dict(), "semantic_refresh": semantic["refresh"]}


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/").removeprefix("./")
    if not normalized or normalized.startswith("../") or "/../" in f"/{normalized}/":
        raise ValueError("A repository-relative file path is required")
    return normalized


def _guide_selection(intent: str, fresh_eyes: bool, reassess: bool) -> tuple[str, bool, bool]:
    selected = str(intent or "build").strip().lower()
    if selected not in _GUIDE_JOURNEYS:
        allowed = ", ".join(sorted(_GUIDE_JOURNEYS - {"refactor"}))
        raise ValueError(f"Guide intent must be one of: {allowed}")
    if selected == "understand" and (fresh_eyes or reassess):
        raise ValueError("Understand cannot be combined with fresh_eyes or reassess")
    redesign = fresh_eyes or selected == "redesign"
    compare = reassess or selected == "reassess"
    if redesign and compare:
        raise ValueError("Choose either fresh_eyes or reassess, not both")
    return selected, redesign, compare


def _journey_result(result: dict[str, Any], intent: str, goal: str) -> dict[str, Any]:
    if intent == "redesign" and str(result.get("state") or "") in {"not_started", "stale"}:
        next_action = {
            "tool": "ANAXIGRAPH_GUIDE",
            "arguments": {"intent": "redesign", "start": True, "proposal_count": 2},
            "reason": "Start two independent capability-first proposals.",
        }
    elif intent == "reassess" and str(result.get("state") or "") == "semantic_refresh_pending":
        next_action = (result.get("semantic_refresh") or {}).get("recommended_action") or {}
    else:
        next_action = result.get("next_action") or {
            "tool": "ANAXIGRAPH_GUIDE",
            "arguments": {"intent": "build", "goal": goal or "<describe one coding goal>"},
            "reason": "Use the architecture result for one bounded coding decision.",
        }
    return {
        **result,
        "agent_journey": {
            "contract_version": AGENT_JOURNEY_VERSION,
            "intent": intent,
            "current_step": intent,
            "next_action": next_action,
        },
    }
