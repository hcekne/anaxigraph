#!/usr/bin/env python3
"""Build a deterministic ZIP of the dual Codex/Claude agent plugin."""

from __future__ import annotations

import argparse
import hashlib
import time
import zipfile
from pathlib import Path

if __package__:
    from scripts.build_release_artifacts import source_date_epoch
    from scripts.check_agent_package import PLUGIN, validate_agent_package
    from scripts.verify_release_artifacts import project_version
else:
    from build_release_artifacts import source_date_epoch
    from check_agent_package import PLUGIN, validate_agent_package
    from verify_release_artifacts import project_version


def build_agent_plugin(root: Path, output: Path, *, epoch: int | None = None) -> dict[str, object]:
    root = root.resolve()
    errors = validate_agent_package(root)
    if errors:
        raise ValueError("agent package is invalid: " + "; ".join(errors))
    version = project_version(root)
    expected = f"anaxigraph-agent-plugin-{version}.zip"
    if output.name != expected:
        raise ValueError(f"agent plugin output must be named {expected}")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise ValueError(f"agent plugin output already exists: {output}")
    epoch = source_date_epoch(root) if epoch is None else epoch
    timestamp = time.gmtime(max(epoch, 315_532_800))[:6]
    files = sorted(path for path in (root / PLUGIN).rglob("*") if path.is_file())
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = Path("anaxigraph") / path.relative_to(root / PLUGIN)
            info = zipfile.ZipInfo(relative.as_posix(), timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    return {"path": output.name, "version": version, "files": len(files), "sha256": digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-date-epoch", type=int)
    args = parser.parse_args(argv)
    result = build_agent_plugin(
        args.root,
        args.output,
        epoch=args.source_date_epoch,
    )
    print(f"{result['sha256']}  {result['path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
