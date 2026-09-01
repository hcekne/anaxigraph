from __future__ import annotations

from pathlib import Path

import pytest

from scripts.build_release_artifacts import build_release_artifacts
from scripts.verify_release_artifacts import (
    ReleaseContractError,
    project_version,
    validate_tag,
    verify_distribution,
    write_checksums,
)

ROOT = Path(__file__).parents[1]


@pytest.fixture(scope="module")
def built_distributions(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    destinations = (
        tmp_path_factory.mktemp("distribution-one"),
        tmp_path_factory.mktemp("distribution-two"),
    )
    for destination in destinations:
        build_release_artifacts(ROOT, destination, epoch=1_700_000_000)
    return destinations


def test_project_version_and_release_tag_are_one_contract():
    version = project_version(ROOT)
    validate_tag(version, f"v{version}")
    with pytest.raises(ReleaseContractError, match="does not match"):
        validate_tag(version, "v999.999.999")


def test_built_wheel_and_sdist_preserve_runtime_and_license_contract(
    built_distributions: tuple[Path, Path],
    tmp_path: Path,
):
    version = project_version(ROOT)
    report = verify_distribution(ROOT, built_distributions[0], tag=f"v{version}")

    assert report["name"] == "anaxigraph"
    assert report["version"] == version
    assert {item["path"] for item in report["artifacts"]} == {
        f"anaxigraph-{version}-py3-none-any.whl",
        f"anaxigraph-{version}.tar.gz",
    }
    assert all(len(item["sha256"]) == 64 for item in report["artifacts"])
    assert all(len(item["parser_dependencies"]) == 3 for item in report["artifacts"])

    checksums = tmp_path / "SHA256SUMS"
    write_checksums(report, checksums)
    lines = checksums.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert all(f"  anaxigraph-{version}" in line for line in lines)


def test_release_archives_are_byte_reproducible(built_distributions: tuple[Path, Path]):
    first, second = built_distributions
    first_hashes = {path.name: path.read_bytes() for path in first.iterdir()}
    second_hashes = {path.name: path.read_bytes() for path in second.iterdir()}
    assert first_hashes == second_hashes


def test_release_workflow_can_probe_trusted_publishing_without_uploading():
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    probe, release = workflow.split("  build:\n", maxsplit=1)

    assert "workflow_dispatch:" in probe
    assert "if: github.event_name == 'workflow_dispatch'" in probe
    assert "https://pypi.org/_/oidc/mint-token" in probe
    assert "unset api_token" in probe
    assert "gh-action-pypi-publish" not in probe
    assert "twine upload" not in probe
    assert "if: github.event_name == 'release'" in release
