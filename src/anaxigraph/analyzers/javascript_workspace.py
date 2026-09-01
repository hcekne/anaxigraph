"""Indexed JavaScript workspace facts and deterministic repository resolution."""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from anaxigraph.analyzers.json_support import load_json_document

_CONFIG_NAMES = {"jsconfig.json", "tsconfig.json"}
_EXTENSIONS = (
    "",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".json",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)


@dataclass(frozen=True, slots=True)
class WorkspaceResolution:
    paths: tuple[str, ...]
    internal: bool
    provenance: tuple[str, ...]


def extract_workspace_config(path: str, content: str) -> dict[str, Any] | None:
    """Return the bounded resolver projection of package/TypeScript configuration."""

    name = PurePosixPath(path).name.lower()
    if name != "package.json" and not _is_typescript_config(name):
        return None
    value = load_json_document(content)
    if not isinstance(value, dict):
        return None
    if name == "package.json":
        return _package_projection(value)
    return _typescript_projection(value)


def project_reference_dependencies(config: dict[str, Any] | None) -> tuple[str, ...]:
    if not config or config.get("kind") != "typescript_config":
        return ()
    return tuple(config.get("references") or ())


class JavaScriptWorkspace:
    """Resolve JS-family references only from files already present in the snapshot."""

    def __init__(
        self,
        prepared: Iterable[Any],
        paths: Iterable[str],
        configured_aliases: dict[str, str],
    ) -> None:
        self.paths = frozenset(paths)
        self.configured_aliases = dict(configured_aliases)
        self.packages: dict[str, list[tuple[str, str, dict[str, Any]]]] = {}
        self.package_manifests: list[tuple[str, str, dict[str, Any]]] = []
        self.typescript_configs: list[tuple[str, str, dict[str, Any]]] = []
        self.typescript_configs_by_path: dict[str, tuple[str, str, dict[str, Any]]] = {}
        for item in prepared:
            config = item.analysis.metadata.get("javascript_workspace")
            if not isinstance(config, dict):
                continue
            path = item.discovered.path
            directory = _parent(path)
            if config.get("kind") == "package":
                manifest = (path, directory, config)
                self.package_manifests.append(manifest)
                if config.get("name"):
                    self.packages.setdefault(str(config["name"]), []).append(manifest)
            elif config.get("kind") == "typescript_config":
                item = (path, directory, config)
                self.typescript_configs.append(item)
                self.typescript_configs_by_path[path] = item

    def resolve(self, source_path: str, target: str) -> WorkspaceResolution | None:
        clean = target.split("?", 1)[0].split("#", 1)[0]
        if target.startswith("#"):
            package_import = self._package_import(source_path, target)
            if package_import is not None:
                return package_import
            clean = target
        if clean.startswith("."):
            base = posixpath.normpath(posixpath.join(_parent(source_path), clean))
            return self._expanded((base,), True, ("relative_path",))
        if clean.startswith("/"):
            return self._expanded((clean.lstrip("/"),), True, ("repository_absolute",))
        configured = self._configured_alias(clean)
        if configured is not None:
            return configured
        tsconfig = self._typescript_alias(source_path, clean)
        if tsconfig is not None:
            return tsconfig
        package = self._workspace_package(clean)
        if package is not None:
            return package
        return self._typescript_base_url(source_path, clean)

    def _configured_alias(self, target: str) -> WorkspaceResolution | None:
        for alias, replacement in sorted(
            self.configured_aliases.items(), key=lambda item: len(item[0]), reverse=True
        ):
            matched = _configured_alias_suffix(alias, target)
            if matched is None:
                continue
            base = _apply_configured_alias(alias, replacement, matched)
            return self._expanded((base,), True, (f"anaxigraph_alias:{alias}->{replacement}",))
        return None

    def _typescript_alias(self, source_path: str, target: str) -> WorkspaceResolution | None:
        candidates: list[str] = []
        provenance: list[str] = []
        matched = False
        for root_config in self._nearest_configs(source_path):
            for path, directory, config in self._config_chain(root_config):
                matches = [
                    (alias, replacements, _pattern_suffix(alias, target))
                    for alias, replacements in (config.get("paths") or {}).items()
                ]
                matches = [item for item in matches if item[2] is not None]
                if not matches:
                    continue
                matched = True
                specificity = max(len(item[0].replace("*", "")) for item in matches)
                for alias, replacements, suffix in matches:
                    if len(alias.replace("*", "")) != specificity:
                        continue
                    base_url = str(config.get("base_url") or "")
                    for replacement in replacements:
                        relative = _apply_pattern(str(replacement), str(suffix))
                        candidates.append(
                            posixpath.normpath(posixpath.join(directory, base_url, relative))
                        )
                    provenance.append(f"tsconfig_paths:{path}:{alias}")
                break
        if not matched:
            return None
        return self._expanded(candidates, True, provenance)

    def _typescript_base_url(self, source_path: str, target: str) -> WorkspaceResolution | None:
        candidates = []
        provenance = []
        for root_config in self._nearest_configs(source_path):
            for path, directory, config in self._config_chain(root_config):
                base_url = config.get("base_url")
                if not isinstance(base_url, str):
                    continue
                candidates.append(posixpath.normpath(posixpath.join(directory, base_url, target)))
                provenance.append(f"tsconfig_baseUrl:{path}")
                break
        if not candidates:
            return None
        resolution = self._expanded(candidates, True, provenance)
        return resolution if resolution.paths else None

    def _workspace_package(self, target: str) -> WorkspaceResolution | None:
        package_name = next(
            (
                name
                for name in sorted(self.packages, key=len, reverse=True)
                if target == name or target.startswith(f"{name}/")
            ),
            None,
        )
        if package_name is None:
            return None
        subpath = target[len(package_name) :].lstrip("/")
        candidates: list[str] = []
        provenance = []
        for manifest, directory, config in self.packages[package_name]:
            candidates.extend(_package_candidates(directory, config, subpath))
            provenance.append(f"workspace_package:{manifest}:{package_name}")
        return self._expanded(candidates, True, provenance)

    def _package_import(self, source_path: str, target: str) -> WorkspaceResolution | None:
        manifests = [item for item in self.package_manifests if _is_below(source_path, item[1])]
        if not manifests:
            return None
        manifest, directory, config = max(
            manifests, key=lambda item: len(PurePosixPath(item[1]).parts)
        )
        values = _mapped_values(config.get("imports") or {}, target)
        if not values:
            return None
        candidates = [posixpath.normpath(posixpath.join(directory, value)) for value in values]
        return self._expanded(candidates, True, (f"package_imports:{manifest}:{target}",))

    def _nearest_configs(self, source_path: str) -> list[tuple[str, str, dict[str, Any]]]:
        values = [item for item in self.typescript_configs if _is_below(source_path, item[1])]
        if not values:
            return []
        depth = max(len(PurePosixPath(item[1]).parts) for item in values)
        nearest = [item for item in values if len(PurePosixPath(item[1]).parts) == depth]
        return sorted(nearest)

    def _config_chain(
        self, root: tuple[str, str, dict[str, Any]]
    ) -> list[tuple[str, str, dict[str, Any]]]:
        result = []
        current = root
        seen = set()
        while current[0] not in seen and len(result) < 8:
            result.append(current)
            seen.add(current[0])
            inherited = current[2].get("extends")
            candidate = self._extended_config(current[1], inherited)
            if candidate is None:
                break
            current = candidate
        return result

    def _extended_config(
        self,
        directory: str,
        inherited: Any,
    ) -> tuple[str, str, dict[str, Any]] | None:
        if not isinstance(inherited, str) or not inherited.startswith("."):
            return None
        base = posixpath.normpath(posixpath.join(directory, inherited))
        for path in (base, f"{base}.json", posixpath.join(base, "tsconfig.json")):
            if path in self.typescript_configs_by_path:
                return self.typescript_configs_by_path[path]
        return None

    def _expanded(
        self,
        bases: Iterable[str],
        internal: bool,
        provenance: Iterable[str],
    ) -> WorkspaceResolution:
        matches = sorted(
            {
                base + extension
                for raw in bases
                for base in (posixpath.normpath(raw).removeprefix("./"),)
                for extension in _EXTENSIONS
                if not base.startswith("../") and base + extension in self.paths
            }
        )
        return WorkspaceResolution(tuple(matches), internal, tuple(sorted(set(provenance))))


def _package_projection(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "package",
        "name": value.get("name") if isinstance(value.get("name"), str) else None,
        "entrypoints": _strings(
            value.get("types"), value.get("typings"), value.get("module"), value.get("main")
        ),
        "exports": _mapping_projection(value.get("exports"), default_key="."),
        "imports": _mapping_projection(value.get("imports"), default_key=None),
        "workspaces": _workspace_values(value.get("workspaces")),
    }


def _typescript_projection(value: dict[str, Any]) -> dict[str, Any]:
    compiler = value.get("compilerOptions") or {}
    if not isinstance(compiler, dict):
        compiler = {}
    raw_paths = compiler.get("paths") or {}
    if not isinstance(raw_paths, dict):
        raw_paths = {}
    paths = {str(key): list(_strings(item)) for key, item in raw_paths.items() if _strings(item)}
    references = []
    for item in value.get("references") or ():
        if isinstance(item, dict) and isinstance(item.get("path"), str):
            references.append(item["path"])
    return {
        "kind": "typescript_config",
        "extends": value.get("extends") if isinstance(value.get("extends"), str) else None,
        "base_url": compiler.get("baseUrl") if isinstance(compiler.get("baseUrl"), str) else None,
        "paths": paths,
        "references": list(dict.fromkeys(references)),
    }


def _package_candidates(directory: str, config: dict[str, Any], subpath: str) -> list[str]:
    export_key = f"./{subpath}" if subpath else "."
    mapped = _mapped_values(config.get("exports") or {}, export_key)
    values = mapped or ([subpath] if subpath else list(config.get("entrypoints") or ()))
    if not values and not subpath:
        values = ["src/index", "index"]
    return [posixpath.normpath(posixpath.join(directory, value)) for value in values]


def _mapping_projection(value: Any, *, default_key: str | None) -> dict[str, list[str]]:
    if isinstance(value, str) and default_key is not None:
        return {default_key: [value]}
    if not isinstance(value, dict):
        return {}
    if default_key is not None and not any(str(key).startswith(".") for key in value):
        return {default_key: list(_leaf_strings(value))}
    return {
        str(key): list(_leaf_strings(item))
        for key, item in value.items()
        if str(key).startswith((".", "#")) and tuple(_leaf_strings(item))
    }


def _mapped_values(mapping: dict[str, list[str]], target: str) -> list[str]:
    result = []
    for pattern, replacements in mapping.items():
        suffix = _pattern_suffix(pattern, target)
        if suffix is not None:
            result.extend(_apply_pattern(value, suffix) for value in replacements)
    return list(dict.fromkeys(result))


def _leaf_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value.removeprefix("./")
    elif isinstance(value, dict):
        for item in value.values():
            yield from _leaf_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _leaf_strings(item)


def _strings(*values: Any) -> tuple[str, ...]:
    result = []
    for value in values:
        if isinstance(value, str):
            result.append(value.removeprefix("./"))
        elif isinstance(value, list):
            result.extend(str(item).removeprefix("./") for item in value if isinstance(item, str))
    return tuple(dict.fromkeys(result))


def _workspace_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        value = value.get("packages")
    return list(_strings(value))


def _pattern_suffix(pattern: str, target: str) -> str | None:
    if "*" not in pattern:
        return "" if pattern.rstrip("/") == target.rstrip("/") else None
    prefix, suffix = pattern.split("*", 1)
    if target.startswith(prefix) and target.endswith(suffix):
        return target[len(prefix) : len(target) - len(suffix) if suffix else None]
    return None


def _configured_alias_suffix(pattern: str, target: str) -> str | None:
    if "*" in pattern:
        return _pattern_suffix(pattern, target)
    prefix = pattern.rstrip("*")
    return target[len(prefix) :].lstrip("/") if target.startswith(prefix) else None


def _apply_pattern(pattern: str, suffix: str) -> str:
    return pattern.replace("*", suffix).removeprefix("./")


def _apply_configured_alias(alias: str, replacement: str, suffix: str) -> str:
    if "*" in alias or "*" in replacement:
        return _apply_pattern(replacement, suffix)
    return posixpath.join(replacement, suffix).removeprefix("./")


def _is_typescript_config(name: str) -> bool:
    return name in _CONFIG_NAMES or name.startswith(("tsconfig.", "jsconfig."))


def _parent(path: str) -> str:
    value = str(PurePosixPath(path).parent)
    return "" if value == "." else value


def _is_below(path: str, directory: str) -> bool:
    return not directory or path == directory or path.startswith(f"{directory}/")
