"""The uv-friendly command line; application decisions live in Application."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _location(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repo", type=Path, default=argparse.SUPPRESS, help="Checkout to analyze")
    parser.add_argument(
        "--database", type=Path, default=argparse.SUPPRESS, help="Local SQLite path"
    )


def parser() -> argparse.ArgumentParser:
    from anaxigraph import __version__

    result = argparse.ArgumentParser(description="AnaxiGraph V2 — understand and improve code")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    _location(result)
    commands = result.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("scan", "Build or refresh the structural map"),
        ("status", "Show checkout identity and analysis readiness"),
        ("modules", "List mapped modules"),
        ("inspect", "Expand one entity and its relationships"),
        ("prepare", "Find ownership, reuse and checks for a change"),
        ("assess", "Assess proposed file placement"),
        ("validate", "Compare snapshots and attribute supplied check results"),
        ("request", "Prepare an annotation, Patterns or blind Fresh Eyes task"),
        ("submit", "Validate and save an agent's analysis result"),
        ("reviews", "Read saved architectural reviews"),
        ("serve", "Open the local dashboard API"),
        ("mcp", "Serve the shared application over MCP stdio"),
    ):
        command = commands.add_parser(name, help=help_text)
        _location(command)
        if name == "inspect":
            command.add_argument("entity_id")
            command.add_argument("--limit", type=int, default=30)
        elif name == "modules":
            command.add_argument("--sort", default="path")
            command.add_argument("--descending", action="store_true")
            command.add_argument("--limit", type=int, default=50)
            command.add_argument("--offset", type=int, default=0)
        elif name in {"prepare", "assess"}:
            command.add_argument("task")
            if name == "assess":
                command.add_argument("--files", nargs="+", required=True)
            else:
                command.add_argument("--limit", type=int, default=12)
        elif name == "validate":
            command.add_argument("--receipts", type=Path, help="JSON array of check receipts")
        elif name == "request":
            command.add_argument("kind", choices=("annotate", "patterns", "fresh-eyes"))
            command.add_argument("--scope", nargs="+")
        elif name == "submit":
            command.add_argument("request_id")
            command.add_argument(
                "result", type=Path, help="JSON object containing the agent result"
            )
        elif name == "reviews":
            command.add_argument("--kind")
        elif name == "serve":
            command.add_argument("--host", default="127.0.0.1")
            command.add_argument("--port", type=int, default=8766)
    return result


def _read_json(path: Path, expected: type) -> Any:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, expected):
        raise ValueError(f"{path} must contain a JSON {expected.__name__}")
    return value


def dispatch(application: Any, args: argparse.Namespace) -> dict[str, Any]:
    """Keep transport dispatch independent from application implementation."""
    if args.command in {"scan", "status"}:
        return getattr(application, args.command)()
    if args.command == "modules":
        return application.modules(args.sort, args.descending, args.limit, args.offset)
    if args.command == "inspect":
        return application.inspect(args.entity_id, args.limit)
    if args.command == "prepare":
        return application.prepare_change(args.task, args.limit)
    if args.command == "assess":
        return application.assess_plan(args.task, args.files)
    if args.command == "validate":
        receipts = _read_json(args.receipts, list) if args.receipts else None
        return application.validate_change(receipts)
    if args.command == "request":
        return application.analysis_request(args.kind, args.scope)
    if args.command == "submit":
        return application.submit_analysis(args.request_id, _read_json(args.result, dict))
    if args.command == "reviews":
        return application.reviews(args.kind)
    raise ValueError(f"Unsupported application command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    from anaxigraph.application import Application

    args = parser().parse_args(argv)
    try:
        application = Application(
            getattr(args, "repo", Path.cwd()), getattr(args, "database", None)
        )
        if args.command == "serve":
            import uvicorn

            from anaxigraph.interfaces.http import create_app

            uvicorn.run(create_app(application), host=args.host, port=args.port)
        elif args.command == "mcp":
            from anaxigraph.interfaces.mcp import create_mcp

            create_mcp(application).run(transport="stdio")
        else:
            print(json.dumps(dispatch(application, args), ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
