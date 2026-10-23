"""Resolve lexical/imported call targets using indexed module and export facts."""

from __future__ import annotations

import json
import posixpath
from collections import defaultdict
from pathlib import PurePosixPath

from anaxigraph.call_graph_contract import CALLABLE_SYMBOL_KINDS


def call_owner(symbols, call):
    if "caller" in call:
        return next((item for item in symbols if item["qualified_name"] == call["caller"]), None)
    choices = [
        item
        for item in symbols
        if item["symbol_type"] in CALLABLE_SYMBOL_KINDS
        and item["start_line"] <= call["line"] <= item["end_line"]
    ]
    return min(choices, key=lambda item: item["end_line"] - item["start_line"], default=None)


def call_index(files, symbols):
    qualified, modules = defaultdict(list), defaultdict(list)
    by_path = {file["path"]: file for file in files}
    for file in files:
        file["call_metadata"] = json.loads(file.get("metadata_json") or "{}")
        identity = file["call_metadata"].get("ir", {}).get("module_identity", {})
        canonical = identity.get("canonical_name") or _module_name(file["path"])
        file["call_module"] = canonical
        file["call_aliases"] = set(identity.get("aliases", ())) | {canonical}
        for alias in file["call_aliases"]:
            modules[alias].append(file)
    for symbol in symbols:
        if symbol["symbol_type"] not in CALLABLE_SYMBOL_KINDS | {"class", "database_model"}:
            continue
        file = by_path[symbol["path"]]
        suffix = symbol["qualified_name"].removeprefix(file["call_module"] + ".")
        for alias in file["call_aliases"]:
            qualified[alias + "." + suffix].append(symbol)
    return {"qualified": qualified, "modules": modules, "paths": by_path}


def resolve_call(file, call, caller, index):
    if call.get("binding") == "dynamic":
        return []
    if call.get("import_binding"):
        binding = call["import_binding"]
        tail = call["target"].partition(".")[2]
        name = binding["name"]
        name = tail or "default" if name == "*" else name + ("." + tail if tail else "")
        return _imported(file, binding["module"], name, index, set())
    target = call.get("qualified_target")
    if target:
        return _unique(index["qualified"].get(target, []))
    raw = str(call["target"])
    aliases = file["call_metadata"].get("symbol_aliases", {})
    head, separator, tail = raw.partition(".")
    bound = aliases.get(head, head)
    target = bound + separator + tail if isinstance(bound, str) else raw
    return lexical_targets(caller, target, index["qualified"])


def lexical_targets(caller, target, qualified):
    if caller is None:
        return _unique(qualified.get(target, []))
    if target.startswith(("self.", "cls.", "this.")):
        target = caller["qualified_name"].rsplit(".", 1)[0] + "." + target.partition(".")[2]
    prefix = caller["qualified_name"]
    while prefix:
        name = prefix + "." + target
        if name in qualified:
            return _unique(qualified[name])
        prefix = prefix.rpartition(".")[0]
    return _unique(qualified.get(target, []))


def _imported(importer, module, name, index, seen):
    files = _module_files(importer, module, index)
    if len(files) != 1:
        return []
    file = files[0]
    key = (file["path"], name)
    if key in seen:
        return []
    seen.add(key)
    head, separator, tail = name.partition(".")
    binding = file["call_metadata"].get("export_bindings", {}).get(head)
    if binding is None:
        return []
    name = binding["name"] + separator + tail
    if binding.get("module"):
        return _imported(file, binding["module"], name, index, seen)
    return _unique(index["qualified"].get(file["call_module"] + "." + name, []))


def _module_files(importer, module, index):
    if not module.startswith("."):
        return index["modules"].get(module, [])
    base = posixpath.normpath(posixpath.join(str(PurePosixPath(importer["path"]).parent), module))
    extensions = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
    choices = [
        base,
        *(base + suffix for suffix in extensions),
        *(base + "/index" + suffix for suffix in extensions),
    ]
    return [index["paths"][path] for path in choices if path in index["paths"]]


def _module_name(path):
    pure = PurePosixPath(path)
    parts = list(pure.with_suffix("").parts)
    return ".".join(parts[:-1] if pure.stem == "__init__" else parts)


def _unique(values):
    return list(
        {
            (item["path"], item["qualified_name"], item["start_line"]): item for item in values
        }.values()
    )
