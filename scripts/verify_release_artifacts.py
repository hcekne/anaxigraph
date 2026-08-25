#!/usr/bin/env python3
"""Verify AnaxiGraph's immutable release contract before publication."""

from __future__ import annotations

import argparse
import hashlib
import json
import tarfile
import tomllib
import urllib.error
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any

PROJECT_NAME = "anaxigraph"
EXPECTED_LICENSE = "Apache-2.0"
EXPECTED_PYTHON = ">=3.11"
REQUIRED_DASHBOARD_ASSETS = (
    "anaxigraph/dashboard/app.js",
    "anaxigraph/dashboard/favicon.svg",
    "anaxigraph/dashboard/findings-view.js",
    "anaxigraph/dashboard/history-view.js",
    "anaxigraph/dashboard/index.html",
    "anaxigraph/dashboard/mask-icon.svg",
    "anaxigraph/dashboard/styles.css",
)
REQUIRED_PATTERN_CATALOG = tuple(
    f"anaxigraph/catalog/patterns-{family}.json"
    for family in (
        "composition-workflow",
        "data-state",
        "function-construction",
        "integration-concurrency",
        "module-boundary",
        "object-interface",
        "reliability-testing",
        "subsystem-architecture",
    )
)


class ReleaseContractError(ValueError):
    """Raised when a prospective release violates the package contract."""


def project_version(root: Path) -> str:
    document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = document.get("project", {})
    if project.get("name") != PROJECT_NAME:
        raise ReleaseContractError(f"expected project name {PROJECT_NAME!r}")
    version = str(project.get("version") or "").strip()
    if not version:
        raise ReleaseContractError("project.version must be explicit and non-empty")
    if project.get("license") != EXPECTED_LICENSE:
        raise ReleaseContractError(f"project.license must be {EXPECTED_LICENSE!r}")
    if project.get("license-files") != ["LICENSE"]:
        raise ReleaseContractError("project.license-files must contain exactly LICENSE")
    return version


def validate_tag(version: str, tag: str | None) -> None:
    if tag and tag != f"v{version}":
        raise ReleaseContractError(f"tag {tag!r} does not match package version v{version}")


def _only_artifact(dist: Path, pattern: str, kind: str) -> Path:
    matches = sorted(dist.glob(pattern))
    if len(matches) != 1:
        raise ReleaseContractError(
            f"expected exactly one {kind} matching {pattern!r}, found {len(matches)}"
        )
    return matches[0]


def _safe_archive_names(names: set[str], artifact: Path) -> None:
    for name in names:
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts:
            raise ReleaseContractError(f"unsafe path {name!r} in {artifact.name}")


def verify_wheel(wheel: Path, version: str) -> dict[str, Any]:
    expected_name = f"{PROJECT_NAME}-{version}-py3-none-any.whl"
    if wheel.name != expected_name:
        raise ReleaseContractError(f"expected wheel {expected_name!r}, found {wheel.name!r}")
    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
        _safe_archive_names(names, wheel)
        dist_info = f"{PROJECT_NAME}-{version}.dist-info"
        metadata = BytesParser().parsebytes(archive.read(f"{dist_info}/METADATA"))
        wheel_metadata = BytesParser().parsebytes(archive.read(f"{dist_info}/WHEEL"))
        entry_points = archive.read(f"{dist_info}/entry_points.txt").decode("utf-8")

    expected_headers = {
        "Name": PROJECT_NAME,
        "Version": version,
        "License-Expression": EXPECTED_LICENSE,
        "Requires-Python": EXPECTED_PYTHON,
    }
    for header, expected in expected_headers.items():
        if metadata.get(header) != expected:
            raise ReleaseContractError(
                f"wheel {header} is {metadata.get(header)!r}, expected {expected!r}"
            )
    if metadata.get_all("License-File", []) != ["LICENSE"]:
        raise ReleaseContractError("wheel metadata must declare exactly License-File: LICENSE")
    if wheel_metadata.get("Root-Is-Purelib") != "true":
        raise ReleaseContractError("wheel must be platform-independent pure Python")
    if wheel_metadata.get_all("Tag", []) != ["py3-none-any"]:
        raise ReleaseContractError("wheel must carry exactly the py3-none-any tag")
    required = {
        *REQUIRED_DASHBOARD_ASSETS,
        *REQUIRED_PATTERN_CATALOG,
        f"{dist_info}/licenses/LICENSE",
    }
    missing = sorted(required - names)
    if missing:
        raise ReleaseContractError(f"wheel is missing package data: {', '.join(missing)}")
    if "anaxigraph = anaxigraph.cli:main" not in entry_points:
        raise ReleaseContractError("wheel is missing the anaxigraph console entry point")
    if any("codeintel" in name.casefold() for name in names):
        raise ReleaseContractError("wheel contains a retired codeintel path")
    return {"path": wheel.name, "files": len(names), "sha256": _sha256(wheel)}


def verify_sdist(sdist: Path, version: str) -> dict[str, Any]:
    expected_name = f"{PROJECT_NAME}-{version}.tar.gz"
    if sdist.name != expected_name:
        raise ReleaseContractError(f"expected sdist {expected_name!r}, found {sdist.name!r}")
    prefix = f"{PROJECT_NAME}-{version}"
    with tarfile.open(sdist, "r:gz") as archive:
        names = {member.name.rstrip("/") for member in archive.getmembers()}
        _safe_archive_names(names, sdist)
        pyproject_member = archive.extractfile(f"{prefix}/pyproject.toml")
        if pyproject_member is None:
            raise ReleaseContractError("sdist does not contain pyproject.toml")
        packaged = tomllib.loads(pyproject_member.read().decode("utf-8"))
    required = {
        f"{prefix}/LICENSE",
        f"{prefix}/README.md",
        f"{prefix}/pyproject.toml",
        *(f"{prefix}/src/{asset}" for asset in REQUIRED_DASHBOARD_ASSETS),
        *(f"{prefix}/src/{asset}" for asset in REQUIRED_PATTERN_CATALOG),
    }
    missing = sorted(required - names)
    if missing:
        raise ReleaseContractError(f"sdist is missing source data: {', '.join(missing)}")
    if packaged.get("project", {}).get("version") != version:
        raise ReleaseContractError("sdist pyproject version does not match its filename")
    if any("codeintel" in name.casefold() for name in names):
        raise ReleaseContractError("sdist contains a retired codeintel path")
    return {"path": sdist.name, "files": len(names), "sha256": _sha256(sdist)}


def verify_distribution(root: Path, dist: Path, *, tag: str | None = None) -> dict[str, Any]:
    version = project_version(root)
    validate_tag(version, tag)
    wheel = _only_artifact(dist, "*.whl", "wheel")
    sdist = _only_artifact(dist, "*.tar.gz", "source distribution")
    artifacts = [verify_wheel(wheel, version), verify_sdist(sdist, version)]
    return {"name": PROJECT_NAME, "version": version, "tag": tag, "artifacts": artifacts}


def ensure_version_is_unpublished(version: str, *, timeout: float = 15.0) -> None:
    url = f"https://pypi.org/pypi/{PROJECT_NAME}/{version}/json"
    request = urllib.request.Request(url, headers={"User-Agent": "anaxigraph-release-gate"})
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return
        raise ReleaseContractError(f"PyPI version check failed with HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ReleaseContractError(f"PyPI version check failed: {exc.reason}") from exc
    raise ReleaseContractError(
        f"{PROJECT_NAME} {version} already exists on PyPI; release files are immutable"
    )


def write_checksums(report: dict[str, Any], destination: Path) -> None:
    lines = [f"{item['sha256']}  {item['path']}" for item in report["artifacts"]]
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--dist", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--check-pypi", action="store_true")
    parser.add_argument("--checksums", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--version-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    version = project_version(root)
    validate_tag(version, args.tag)
    if args.check_pypi:
        ensure_version_is_unpublished(version)
    if args.version_only:
        print(version)
        return 0
    if args.dist is None:
        raise ReleaseContractError("--dist is required unless --version-only is used")
    report = verify_distribution(root, args.dist.resolve(), tag=args.tag)
    if args.checksums:
        write_checksums(report, args.checksums.resolve())
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
