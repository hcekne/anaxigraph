from __future__ import annotations

import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from scripts.check_changed_coverage import main as coverage_main
from scripts.check_git_policy import commit_errors, history_errors, push_errors

ROOT = Path(__file__).resolve().parents[1]


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-q", "--initial-branch=main")
    git(tmp_path, "config", "user.email", "hooks@example.invalid")
    git(tmp_path, "config", "user.name", "Hook tests")
    git(tmp_path, "commit", "--allow-empty", "-qm", "base")
    git(tmp_path, "branch", "baseline")
    return tmp_path


def test_commits_on_main_are_rejected_including_empty_commits(repository):
    assert "protected branch" in " ".join(commit_errors(repository))
    git(repository, "switch", "-qc", "fix/hooks")
    assert commit_errors(repository) == []


def test_merge_commit_is_rejected_on_a_feature_branch(repository):
    git(repository, "switch", "-qc", "feature/one")
    git(repository, "commit", "--allow-empty", "-qm", "one")
    git(repository, "switch", "-qc", "feature/two", "main")
    git(repository, "commit", "--allow-empty", "-qm", "two")
    git(repository, "merge", "--no-ff", "--no-commit", "feature/one")
    assert "merge commit" in " ".join(commit_errors(repository))


def test_ci_history_rejects_only_new_merges_and_fails_closed(repository):
    git(repository, "switch", "-qc", "feature/one")
    git(repository, "commit", "--allow-empty", "-qm", "one")
    git(repository, "switch", "-q", "main")
    git(repository, "merge", "--no-ff", "-qm", "legacy merge", "feature/one")
    git(repository, "branch", "accepted")
    git(repository, "switch", "-qc", "fix/hooks")
    git(repository, "commit", "--allow-empty", "-qm", "linear fix")
    assert history_errors(repository, "accepted", "HEAD") == []
    assert "merge commit" in " ".join(history_errors(repository, "baseline", "HEAD"))
    assert "unavailable" in " ".join(history_errors(repository, "missing", "HEAD"))
    assert "unavailable" in " ".join(history_errors(repository, "accepted", "missing"))


def test_config_installs_and_runs_the_documented_gates():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    assert set(config["default_install_hook_types"]) == {
        "pre-commit",
        "pre-merge-commit",
        "pre-push",
    }
    hooks = {hook["id"]: hook for repo in config["repos"] for hook in repo["hooks"]}
    for name in ("python-tests", "changed-code-coverage", "self-analysis-regression"):
        assert "pre-push" in hooks[name]["stages"]
        assert hooks[name]["always_run"]
        assert not hooks[name]["pass_filenames"]
    assert "origin/main" in hooks["changed-code-coverage"]["entry"]
    assert "HEAD^" not in hooks["changed-code-coverage"]["entry"]
    assert hooks["git-commit-policy"]["always_run"]
    assert "pre-merge-commit" in hooks["git-commit-policy"]["stages"]
    assert "--staged" not in hooks["push-module-size"]["entry"]
    assert hooks["module-size-ratchet"]["verbose"]


def test_ci_checks_real_pr_head_not_github_synthetic_merge():
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())
    checkout = workflow["jobs"]["quality"]["steps"][0]
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    step = next(
        step
        for step in workflow["jobs"]["quality"]["steps"]
        if "check_git_policy.py" in step.get("run", "")
    )
    assert "github.event.pull_request.head.sha" in step["env"]["POLICY_HEAD"]
    assert "github.event.pull_request.base.sha" in step["env"]["POLICY_BASE"]
    assert "github.event.before" in step["env"]["POLICY_BASE"]


def install_fixture_hooks(root: Path, *names: str):
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hooks = [
        deepcopy(hook) for repo in config["repos"] for hook in repo["hooks"] if hook["id"] in names
    ]
    for hook in hooks:
        script = (
            "check_release_record.py" if hook["id"] == "release-record" else "check_git_policy.py"
        )
        hook["entry"] = f'"{sys.executable}" "{ROOT / "scripts" / script}"'
    config = {"repos": [{"repo": "local", "hooks": hooks}]}
    (root / ".pre-commit-config.yaml").write_text(yaml.safe_dump(config))
    git(root, "add", ".pre-commit-config.yaml")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pre_commit",
            "install",
            "--hook-type",
            "pre-commit",
            "--hook-type",
            "pre-merge-commit",
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_installed_hook_blocks_empty_main_commit(repository):
    install_fixture_hooks(repository, "git-commit-policy")
    result = subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "must be rejected"],
        cwd=repository,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "protected branch main" in result.stdout + result.stderr


def test_push_guard_checks_history_target_and_uncommitted_changes(repository, monkeypatch):
    git(repository, "switch", "-qc", "fix/hooks")
    assert push_errors(repository, "baseline") == []
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", "refs/heads/main")
    assert "protected-branch push" in " ".join(push_errors(repository, "baseline"))
    monkeypatch.setenv("PRE_COMMIT_REMOTE_BRANCH", "refs/heads/fix/hooks")
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/fix/hooks")
    (repository / "staged.txt").write_text("pending\n")
    git(repository, "add", "staged.txt")
    assert "uncommitted" in " ".join(push_errors(repository, "baseline"))
    git(repository, "commit", "-qm", "committed")
    assert push_errors(repository, "baseline") == []
    monkeypatch.setenv("PRE_COMMIT_LOCAL_BRANCH", "refs/heads/main")
    assert "another tree" in " ".join(push_errors(repository, "baseline"))


def test_push_coverage_requires_comparable_base_before_reading_report(repository, capsys):
    assert coverage_main(["--root", str(repository), "--base", "missing", "--require-base"]) == 1
    assert "base unavailable" in capsys.readouterr().out


def test_real_push_is_stopped_by_failing_test_hook(repository):
    remote = repository / "remote.git"
    git(repository, "init", "--bare", "-q", str(remote))
    git(repository, "remote", "add", "origin", str(remote))
    git(repository, "switch", "-qc", "fix/hooks")
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        deepcopy(hook)
        for repo in config["repos"]
        for hook in repo["hooks"]
        if hook["id"] == "python-tests"
    )
    hook["entry"] = f'"{sys.executable}" -m pytest -q failing_test.py'
    (repository / ".pre-commit-config.yaml").write_text(
        yaml.safe_dump({"repos": [{"repo": "local", "hooks": [hook]}]})
    )
    (repository / "failing_test.py").write_text("def test_push_gate():\n    assert False\n")
    git(repository, "add", ".pre-commit-config.yaml", "failing_test.py")
    git(repository, "commit", "-qm", "failing test must not be pushed")
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install", "--hook-type", "pre-push"],
        cwd=repository,
        check=True,
        capture_output=True,
    )
    result = subprocess.run(
        ["git", "push", "origin", "HEAD:refs/heads/fix/hooks"],
        cwd=repository,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "test_push_gate" in result.stdout + result.stderr
    assert git(repository, "ls-remote", "origin", "refs/heads/fix/hooks") == ""
