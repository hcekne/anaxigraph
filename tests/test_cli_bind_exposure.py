from __future__ import annotations

from pathlib import Path

import pytest

import anaxigraph.cli_server_commands as server_commands
import anaxigraph.cli_services as cli_services
from anaxigraph.cli import main


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "[::1]"])
def test_loopback_binds_expose_nothing_new(host: str):
    assert server_commands.bind_exposure_notice(host, 8765, None, False) == []
    assert server_commands.bind_exposure_notice(host, 8765, ["anaxigraph:*"], True) == []


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.5", "workstation.internal"])
def test_non_loopback_binds_report_reachability_and_missing_login(host: str):
    notice = server_commands.bind_exposure_notice(host, 9123, None, False)

    assert len(notice) == 2
    assert "reachable from other machines" in notice[0]
    assert str(9123) in notice[0]
    assert "no login" in notice[1]
    assert "never on an untrusted or shared network" in notice[1]
    assert not any("--allow-agent-scan" in line for line in notice)


def test_non_loopback_notice_names_agent_scans_and_allowed_hosts():
    notice = server_commands.bind_exposure_notice("0.0.0.0", 8765, ["anaxigraph:*"], True)

    assert len(notice) == 3
    assert "anaxigraph:*" in notice[1]
    assert "--allow-agent-scan is on" in notice[2]
    assert "start scans" in notice[2]


def test_unspecified_ipv6_bind_renders_a_loopback_url():
    assert server_commands._display_host("::") == "[::1]"
    assert server_commands._display_host("0.0.0.0") == "127.0.0.1"
    assert server_commands._display_host("192.168.1.5") == "192.168.1.5"
    assert server_commands._display_host("localhost") == "localhost"


def _serve(repository: Path, tmp_path: Path, monkeypatch, extra: list[str]) -> None:
    monkeypatch.setattr(cli_services, "APP_FACTORY", lambda **_options: object())
    monkeypatch.setattr(server_commands.uvicorn, "run", lambda *_args, **_options: None)
    main(
        [
            "serve",
            "--repository",
            str(repository),
            "--db",
            str(tmp_path / "serve.db"),
            *extra,
        ]
    )


def test_serve_prints_the_exposure_notice_for_an_ipv6_wildcard_bind(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _serve(repository, tmp_path, monkeypatch, ["--host", "::", "--allow-agent-scan"])

    error = capsys.readouterr().err
    assert "Dashboard: http://[::1]:8765" in error
    assert "Exposure notice: AnaxiGraph is listening on [::]:8765" in error
    assert "reachable from other machines" in error
    assert "--allow-agent-scan is on" in error


def test_serve_on_the_default_loopback_host_prints_no_exposure_notice(
    repository: Path, tmp_path: Path, capsys, monkeypatch
):
    _serve(repository, tmp_path, monkeypatch, [])

    error = capsys.readouterr().err
    assert "Dashboard: http://127.0.0.1:8765" in error
    assert "Exposure notice" not in error
