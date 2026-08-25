"""Top-level parser assembly for the AnaxiGraph command facade."""

from __future__ import annotations

import argparse

from anaxigraph import __version__
from anaxigraph.cli_agent_commands import configure_agent_commands
from anaxigraph.cli_index_commands import configure_index_commands
from anaxigraph.cli_pattern_commands import configure_pattern_commands
from anaxigraph.cli_repository_commands import configure_repository_commands
from anaxigraph.cli_semantic_commands import configure_semantic_commands
from anaxigraph.cli_server_commands import configure_server_commands
from anaxigraph.onboarding_cli import configure_initialize_command


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="anaxigraph",
        description=(
            "AnaxiGraph: a saved map of repository files, direct code links, findings, and Git history."
        ),
    )
    parser.add_argument("--version", action="version", version=f"AnaxiGraph {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    configure_initialize_command(commands)
    configure_repository_commands(commands)
    configure_semantic_commands(commands)
    configure_pattern_commands(commands)
    configure_server_commands(commands)
    configure_agent_commands(commands)
    configure_index_commands(commands)
    return parser
