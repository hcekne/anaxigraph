from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from anaxigraph.indexing import capture_sources, index


def write(root: Path, relative: str, content: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def repository(root: Path) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.email", "fixture@example.test")
    git(root, "config", "user.name", "Fixture")


def test_relative_imports_calls_nested_symbols_and_tests(tmp_path):
    write(tmp_path, "src/billing/__init__.py", "")
    write(
        tmp_path,
        "src/billing/service.py",
        'def fetch(tenant: str) -> list:\n    """Return this tenant records."""\n    return []\n',
    )
    write(
        tmp_path,
        "src/billing/export.py",
        "from .service import fetch\n\ndef export(tenant):\n    def format_rows(rows):\n        return str(rows)\n    return format_rows(fetch(tenant))\n",
    )
    write(
        tmp_path,
        "tests/test_export.py",
        "from billing.export import export\ndef test_export():\n    assert export('a') == '[]'\n",
    )
    graph = index(tmp_path)
    ids = {n.id for n in graph.nodes}
    assert "symbol:src/billing/export.py#export.format_rows" in ids
    assert any(
        e.kind == "calls"
        and e.source == "symbol:src/billing/export.py#export"
        and e.target == "symbol:src/billing/service.py#fetch"
        and e.resolution == "resolved"
        for e in graph.edges
    )
    assert any(
        e.kind == "tests" and e.target == "symbol:src/billing/export.py#export" for e in graph.edges
    )
    module = next(n for n in graph.nodes if n.id == "module:src/billing/export.py")
    assert module.data["function_count"] == 2
    assert module.data["loc"] > 0
    function = next(n for n in graph.nodes if n.id.endswith("service.py#fetch"))
    assert function.data["signature"] == "fetch(tenant: str) -> list"
    assert function.data["docstring"] == "Return this tenant records."
    assert all(e.source in ids and e.target in ids for e in graph.edges)


def test_shadowed_parameter_and_dynamic_dispatch_are_not_claimed_resolved(tmp_path):
    write(
        tmp_path,
        "app.py",
        "def send():\n    pass\n\ndef use(send, provider):\n    send()\n    provider.run()\n\nclass Base:\n    def run(self):\n        self.other()\n    def other(self):\n        pass\n",
    )
    graph = index(tmp_path)
    calls = [e for e in graph.edges if e.kind == "calls"]
    assert not any(e.source.endswith("#use") and e.target == "symbol:app.py#send" for e in calls)
    assert any(e.source.endswith("#use") and e.resolution == "unresolved" for e in calls)
    assert any(e.target.endswith("#Base.other") and e.resolution == "ambiguous" for e in calls)


def test_git_exclusions_cache_and_unchanged_scans_keep_identity(tmp_path):
    repository(tmp_path)
    write(tmp_path, "app.py", "def live():\n    return 1\n")
    write(tmp_path, ".gitignore", "runtime/\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "initial")
    first = index(tmp_path)
    assert first.snapshot.dirty is False
    write(tmp_path, "runtime/huge.py", "not parsed")
    write(tmp_path, ".anaxigraph-v2/index.db", "cache")
    write(tmp_path, "anaxigraph/manifest.json", "portable")
    second = index(tmp_path)
    assert second.snapshot.id == first.snapshot.id
    assert second.snapshot.dirty is False
    assert not any("runtime" in n.path for n in second.nodes)
    assert index(tmp_path).snapshot.id == first.snapshot.id
    write(tmp_path, "new.py", "pass\n")
    assert index(tmp_path).snapshot.dirty is True
    assert index(tmp_path).snapshot.id != first.snapshot.id


def test_content_change_staged_change_and_clone_path_change_identity(tmp_path):
    root = tmp_path / "first"
    root.mkdir()
    repository(root)
    write(root, "app.py", "value = 1\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "initial")
    baseline = index(root)
    write(root, "app.py", "value = 2\n")
    changed = index(root)
    assert changed.snapshot.files["app.py"] == hashlib.sha256(b"value = 2\n").hexdigest()
    assert changed.snapshot.id != baseline.snapshot.id
    git(root, "add", "app.py")
    assert index(root).snapshot.dirty
    clone = tmp_path / "second"
    subprocess.run(["git", "clone", "-q", str(root), str(clone)], check=True)
    assert index(clone).snapshot.id != baseline.snapshot.id
    worktree = tmp_path / "linked"
    git(root, "worktree", "add", "--detach", str(worktree))
    assert index(worktree).snapshot.root == str(worktree.resolve())
    assert index(worktree).snapshot.id != baseline.snapshot.id


def test_parse_failure_encoding_and_unsupported_language_coverage(tmp_path):
    write(tmp_path, "bad.py", "def broken(:\n")
    write(tmp_path, "frontend.ts", "export const value = 1")
    (tmp_path / "latin.py").write_bytes(b"# coding: latin-1\nname = 'caf\xe9'\n")
    graph = index(tmp_path)
    module = next(n for n in graph.nodes if n.path == "bad.py")
    assert module.data["parse_status"] == "error"
    assert any("SyntaxError" in diagnostic for diagnostic in graph.diagnostics)
    assert any("not parsed" in diagnostic for diagnostic in graph.diagnostics)
    assert "frontend.ts" in graph.snapshot.files
    assert any(n.path == "latin.py" for n in graph.nodes)


def test_source_is_never_executed_and_large_inputs_are_explicit(tmp_path):
    marker = tmp_path / "executed"
    write(
        tmp_path,
        "danger.py",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('wrong')\n",
    )
    write(tmp_path, "large.py", "x" * 2_000_001)
    write(tmp_path, "skip/hidden.py", "pass")
    graph = index(tmp_path, excluded=("skip/",))
    assert not marker.exists()
    assert "skip/hidden.py" not in graph.snapshot.files
    assert "large.py" not in graph.snapshot.files
    assert any(
        "large.py" in diagnostic and "not analyzed" in diagnostic
        for diagnostic in graph.diagnostics
    )


def test_same_package_in_nested_projects_does_not_cross_resolve(tmp_path):
    write(tmp_path, "src/pkg/worker.py", "def run():\n    pass\n")
    write(tmp_path, "src/pkg/app.py", "from pkg.worker import run\nrun()\n")
    write(tmp_path, "new/src/pkg/worker.py", "def run():\n    pass\n")
    write(tmp_path, "new/src/pkg/app.py", "from pkg.worker import run\nrun()\n")
    graph = index(tmp_path)
    assert any(
        e.kind == "calls"
        and e.source == "module:src/pkg/app.py"
        and e.target == "symbol:src/pkg/worker.py#run"
        for e in graph.edges
    )
    assert any(
        e.kind == "calls"
        and e.source == "module:new/src/pkg/app.py"
        and e.target == "symbol:new/src/pkg/worker.py#run"
        for e in graph.edges
    )


def test_callback_references_and_class_lexical_scope_are_honest(tmp_path):
    write(
        tmp_path,
        "app.py",
        "def callback():\n    pass\n\nregistry = {'event': callback}\n\nclass Service:\n    def action(self):\n        callback()\n    def callback(self):\n        pass\n",
    )
    graph = index(tmp_path)
    assert any(
        e.kind == "references"
        and e.source == "module:app.py"
        and e.target == "symbol:app.py#callback"
        for e in graph.edges
    )
    assert any(
        e.kind == "calls"
        and e.source == "symbol:app.py#Service.action"
        and e.target == "symbol:app.py#callback"
        for e in graph.edges
    )
    assert not any(
        e.kind == "calls"
        and e.source == "symbol:app.py#Service.action"
        and e.target == "symbol:app.py#Service.callback"
        for e in graph.edges
    )


def test_unknown_instances_are_scoped_and_arguments_are_not_graph_names(tmp_path):
    write(
        tmp_path,
        "app.py",
        "def first(provider):\n    provider.run()\ndef second(provider):\n    provider.run()\nFactory('private-value').run()\n",
    )
    graph = index(tmp_path)
    targets = {
        e.target for e in graph.edges if e.kind == "calls" and e.source.startswith("symbol:")
    }
    assert len(targets) == 2
    assert not any("private-value" in n.id or "private-value" in n.name for n in graph.nodes)


def test_metadata_is_bounded_without_truncating_source_or_coverage(tmp_path):
    arguments = ", ".join(f"argument_{number}" for number in range(70))
    source = f"def work({arguments}):\n    return 1\n"
    write(tmp_path, "app.py", source)
    graph = index(tmp_path)
    function = next(node for node in graph.nodes if node.kind == "function")
    assert len(function.data["signature"]) <= 500
    assert len(function.data["parameters"]) == 50
    assert function.data["parameter_count"] == 70
    assert {"signature", "parameters"} <= set(function.data["truncated_fields"])
    assert graph.snapshot.files["app.py"] == hashlib.sha256(source.encode()).hexdigest()
    assert next(node for node in graph.nodes if node.kind == "module").data["function_count"] == 1


def test_large_default_literal_is_only_truncated_in_display_metadata(tmp_path):
    source = "def work(value=" + repr("x" * 5000) + "):\n    return value\n"
    write(tmp_path, "app.py", source)
    graph = index(tmp_path)
    function = next(node for node in graph.nodes if node.kind == "function")
    assert len(function.data["signature"]) == 500
    assert "signature" in function.data["truncated_fields"]
    assert graph.snapshot.files["app.py"] == hashlib.sha256(source.encode()).hexdigest()


def test_module_symbol_and_submodule_imports_preserve_resolution_and_unknown_members(tmp_path):
    write(tmp_path, "src/pkg/__init__.py", "")
    write(tmp_path, "src/pkg/sub.py", "def work(value):\n    return value\n")
    write(
        tmp_path,
        "src/pkg/app.py",
        "from pkg import sub as member\nimport pkg.sub\nimport pkg.sub as direct\n"
        "from pkg.sub import work as imported\n\ndef use():\n"
        "    member.work(1)\n    pkg.sub.work(1)\n    direct.work(1)\n"
        "    imported(1)\n    direct.unknown()\n",
    )

    graph = index(tmp_path)
    calls = [
        edge
        for edge in graph.edges
        if edge.kind == "calls" and edge.source == "symbol:src/pkg/app.py#use"
    ]

    resolved = [edge for edge in calls if edge.resolution == "resolved"]
    assert len(resolved) == 4
    assert {edge.target for edge in resolved} == {"symbol:src/pkg/sub.py#work"}
    unknown = [edge for edge in calls if edge.resolution == "unresolved"]
    assert len(unknown) == 1
    assert unknown[0].target.startswith("external:")


@pytest.mark.parametrize(
    ("raw", "decoded"),
    [
        (b"value = 'plain UTF-8'\n", "value = 'plain UTF-8'\n"),
        (b"# coding: latin-1\nvalue = 'caf\xe9'\n", "# coding: latin-1\nvalue = 'caf\xe9'\n"),
        (b"# coding: cp1252\nvalue = '\x80'\n", "# coding: cp1252\nvalue = '\u20ac'\n"),
        (b"\xef\xbb\xbfvalue = 1\n", "value = 1\n"),
    ],
)
def test_source_capture_preserves_full_source_and_python_encoding(tmp_path, raw, decoded):
    (tmp_path / "app.py").write_bytes(raw)
    fingerprints = {"app.py": hashlib.sha256(raw).hexdigest()}

    assert capture_sources(tmp_path, ["app.py"], fingerprints) == {"app.py": decoded}


def test_source_capture_rejects_drift_unmapped_paths_and_oversized_packets(tmp_path):
    original = b"value = 1\n"
    fingerprints = {"app.py": hashlib.sha256(original).hexdigest()}
    (tmp_path / "app.py").write_bytes(b"value = 2\n")
    with pytest.raises(ValueError, match="changed after mapping"):
        capture_sources(tmp_path, ["app.py"], fingerprints)
    with pytest.raises(ValueError, match="analyzed snapshot"):
        capture_sources(tmp_path, ["unmapped.py"], fingerprints)
    oversized = b"#" * 100_001
    (tmp_path / "app.py").write_bytes(oversized)
    fingerprints["app.py"] = hashlib.sha256(oversized).hexdigest()
    with pytest.raises(ValueError, match="100000-byte input limit"):
        capture_sources(tmp_path, ["app.py"], fingerprints)


def test_source_capture_rejects_symlink_ancestors_even_when_fingerprints_match(tmp_path):
    root, outside = tmp_path / "repo", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    raw = b"value = 1\n"
    (outside / "app.py").write_bytes(raw)
    (root / "alias").symlink_to(outside, target_is_directory=True)
    fingerprints = {"alias/app.py": hashlib.sha256(raw).hexdigest()}

    with pytest.raises(ValueError, match="not a regular repository input"):
        capture_sources(root, ["alias/app.py"], fingerprints)


def test_source_capture_rejects_invalid_python_encoding_instead_of_replacing_bytes(tmp_path):
    raw = b"value = '\xff'\n"
    (tmp_path / "app.py").write_bytes(raw)
    with pytest.raises(ValueError, match="Source encoding"):
        capture_sources(tmp_path, ["app.py"], {"app.py": hashlib.sha256(raw).hexdigest()})
