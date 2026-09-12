from __future__ import annotations

import io
import json
import subprocess
import urllib.error
from pathlib import Path

import pytest
import yaml

from scripts.check_release_record import check_release_record, pypi_published
from tests.test_git_hooks import git, install_fixture_hooks

CHANGELOG = """
<!-- changelog -->
```json
{
  "summary": "A tested release record",
  "description": "The fixture carries the entry the website publishes, because a record without one is rejected.",
  "highlights": ["One stated change.", "A second stated change.", "A third stated change."]
}
```
"""


def write_record(root: Path, changelog: str = CHANGELOG, **changes):
    record = {
        "version": "0.5.0",
        "publication": "published",
        "publication_evidence": "https://pypi.org/project/anaxigraph/0.5.0/",
        "artifacts": "verified",
        "artifacts_evidence": "https://github.com/hcekne/anaxigraph/actions/runs/123",
        "protected_merge": "bypassed",
        "protected_merge_evidence": "https://github.com/hcekne/anaxigraph/pull/5",
        "production": "rolled_back",
        "production_evidence": "https://github.com/hcekne/anaxigraph/issues/6",
        "ledger": "docs/ledger.md",
    }
    record.update(changes)
    directory = root / "docs/releases"
    directory.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "anaxigraph"\nversion = "0.5.0"\n')
    (root / "uv.lock").write_text('[[package]]\nname = "anaxigraph"\nversion = "0.5.0"\n')
    (directory / "0.5.0.md").write_text(
        "---\n" + yaml.safe_dump(record) + "---\n# AnaxiGraph 0.5.0\n" + changelog
    )
    (root / "docs/ledger.md").write_text(
        "- [x] <!-- release:publication --> Published.\n"
        "- [x] <!-- release:artifacts --> Verified.\n"
        "- [ ] <!-- release:protected_merge --> Bypassed, not satisfied.\n"
        "- [ ] <!-- release:production --> Failed and rolled back.\n"
    )


def test_truthful_published_but_rolled_back_record_passes(tmp_path):
    write_record(tmp_path)
    assert check_release_record(tmp_path) == []


@pytest.mark.parametrize("gate", ["publication", "artifacts", "protected_merge", "production"])
def test_ledger_checkbox_cannot_contradict_status(tmp_path, gate):
    write_record(tmp_path)
    path = tmp_path / "docs/ledger.md"
    text = path.read_text()
    for checked, replacement in (("x", " "), (" ", "x")):
        before = f"- [{checked}] <!-- release:{gate} -->"
        if before in text:
            path.write_text(text.replace(before, f"- [{replacement}] <!-- release:{gate} -->"))
            break
    assert gate in " ".join(check_release_record(tmp_path))


@pytest.mark.parametrize("gate", ["publication", "artifacts", "protected_merge", "production"])
def test_completed_or_bypassed_gates_require_evidence(tmp_path, gate):
    write_record(tmp_path, **{f"{gate}_evidence": ""})
    assert "evidence" in " ".join(check_release_record(tmp_path))


def test_published_release_cannot_still_call_itself_a_draft(tmp_path):
    write_record(tmp_path)
    path = tmp_path / "docs/releases/0.5.0.md"
    path.write_text(path.read_text() + "\nRelease candidate — publication is still pending.\n")
    assert "draft" in " ".join(check_release_record(tmp_path))


def test_missing_record_and_lock_version_mismatch_fail_closed(tmp_path):
    write_record(tmp_path)
    (tmp_path / "uv.lock").write_text('[[package]]\nname = "anaxigraph"\nversion = "0.4.0"\n')
    assert "uv.lock" in " ".join(check_release_record(tmp_path))
    (tmp_path / "docs/releases/0.5.0.md").unlink()
    assert "0.5.0.md" in " ".join(check_release_record(tmp_path))


@pytest.mark.parametrize("value", ["verified-ish", None, True])
def test_unknown_gate_status_is_not_accepted(tmp_path, value):
    write_record(tmp_path, production=value)
    assert "production" in " ".join(check_release_record(tmp_path))


def test_ledger_must_stay_inside_repository(tmp_path):
    write_record(tmp_path, ledger="../private.md")
    assert "ledger" in " ".join(check_release_record(tmp_path))


def test_online_check_detects_published_version_with_pending_record(tmp_path, monkeypatch):
    write_record(tmp_path, publication="pending")
    path = tmp_path / "docs/ledger.md"
    path.write_text(
        path.read_text().replace("[x] <!-- release:publication", "[ ] <!-- release:publication")
    )
    monkeypatch.setattr("scripts.check_release_record.pypi_published", lambda _version: True)
    assert check_release_record(tmp_path) == []
    assert "PyPI" in " ".join(check_release_record(tmp_path, verify_pypi=True))


def test_online_check_fails_closed_on_network_error(tmp_path, monkeypatch):
    write_record(tmp_path)

    def unavailable(_version):
        raise OSError("offline")

    monkeypatch.setattr("scripts.check_release_record.pypi_published", unavailable)
    assert "offline" in " ".join(check_release_record(tmp_path, verify_pypi=True))


def test_pypi_lookup_uses_exact_version_and_timeout(monkeypatch):
    def request(url, *, timeout):
        assert url == "https://pypi.org/pypi/anaxigraph/0.5.0/json"
        assert timeout == 10
        return io.StringIO(json.dumps({"info": {"version": "0.5.0"}, "urls": [{}]}))

    monkeypatch.setattr("urllib.request.urlopen", request)
    assert pypi_published("0.5.0")


@pytest.mark.parametrize("code", [404, 403, 500])
def test_only_pypi_404_is_an_unpublished_version(monkeypatch, code):
    def request(url, *, timeout):
        raise urllib.error.HTTPError(url, code, "test", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", request)
    if code == 404:
        assert pypi_published("0.5.1") is False
    else:
        with pytest.raises(urllib.error.HTTPError):
            pypi_published("0.5.1")


def test_installed_hook_rejects_staged_contradiction_despite_unstaged_fix(tmp_path):
    git(tmp_path, "init", "-q", "--initial-branch=fix/hooks")
    git(tmp_path, "config", "user.email", "hooks@example.invalid")
    git(tmp_path, "config", "user.name", "Hook tests")
    write_record(tmp_path)
    install_fixture_hooks(tmp_path, "release-record")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-qm", "valid record")
    ledger = tmp_path / "docs/ledger.md"
    original = ledger.read_text()
    ledger.write_text(
        original.replace("[x] <!-- release:publication", "[ ] <!-- release:publication")
    )
    git(tmp_path, "add", "docs/ledger.md")
    ledger.write_text(original)
    result = subprocess.run(
        ["git", "commit", "-m", "must not commit a contradictory record"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "Ledger checkbox for publication" in result.stdout + result.stderr
    assert ledger.read_text() == original


def test_a_release_record_without_a_website_entry_is_rejected(tmp_path):
    write_record(tmp_path, changelog="")

    assert any("changelog" in problem for problem in check_release_record(tmp_path))


def test_a_website_entry_with_too_few_highlights_is_rejected(tmp_path):
    thin = CHANGELOG.replace(
        '"highlights": ["One stated change.", "A second stated change.", "A third stated change."]',
        '"highlights": ["Only one."]',
    )
    write_record(tmp_path, changelog=thin)

    assert any(
        "three and eight highlights" in problem for problem in check_release_record(tmp_path)
    )


def test_a_website_entry_that_is_not_json_is_rejected(tmp_path):
    write_record(tmp_path, changelog="<!-- changelog -->\n```json\n{not json}\n```\n")

    assert any("not valid JSON" in problem for problem in check_release_record(tmp_path))
