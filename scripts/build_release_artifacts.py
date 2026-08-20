#!/usr/bin/env python3
"""Build byte-reproducible AnaxiGraph release archives."""

from __future__ import annotations

import argparse
import copy
import gzip
import os
import subprocess
import sys
import tarfile
from pathlib import Path


def source_date_epoch(root: Path) -> int:
    configured = os.environ.get("SOURCE_DATE_EPOCH")
    if configured:
        return int(configured)
    result = subprocess.run(
        ["git", "-C", str(root), "show", "-s", "--format=%ct", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return int(result.stdout.strip())


def normalize_sdist(path: Path, epoch: int) -> None:
    temporary = path.with_name(f".{path.name}.normalized")
    with tarfile.open(path, "r:gz") as source:
        members = [(member, source.extractfile(member)) for member in source.getmembers()]
        with temporary.open("wb") as raw_output:
            with gzip.GzipFile(fileobj=raw_output, mode="wb", filename="", mtime=epoch) as zipped:
                with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as output:
                    for original, extracted in sorted(members, key=lambda item: item[0].name):
                        member = copy.copy(original)
                        member.mtime = epoch
                        member.uid = 0
                        member.gid = 0
                        member.uname = ""
                        member.gname = ""
                        member.pax_headers = {}
                        output.addfile(member, extracted)
    temporary.replace(path)


def build_release_artifacts(root: Path, outdir: Path, *, epoch: int | None = None) -> list[Path]:
    root = root.resolve()
    outdir = outdir.resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    if any(outdir.iterdir()):
        raise ValueError(f"release output directory must be empty: {outdir}")
    epoch = source_date_epoch(root) if epoch is None else epoch
    environment = {**os.environ, "SOURCE_DATE_EPOCH": str(epoch), "PYTHONHASHSEED": "0"}
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(outdir), str(root)],
        check=True,
        env=environment,
    )
    sdists = sorted(outdir.glob("*.tar.gz"))
    if len(sdists) != 1:
        raise ValueError(f"expected one source distribution, found {len(sdists)}")
    normalize_sdist(sdists[0], epoch)
    return sorted(outdir.iterdir())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--outdir", type=Path, default=Path("dist"))
    parser.add_argument("--source-date-epoch", type=int)
    args = parser.parse_args(argv)
    artifacts = build_release_artifacts(
        args.root,
        args.outdir,
        epoch=args.source_date_epoch,
    )
    for artifact in artifacts:
        print(artifact)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
