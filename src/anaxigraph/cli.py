"""Stable command-line facade for AnaxiGraph."""

from __future__ import annotations

import sys

from anaxigraph.cli_common import emit_json
from anaxigraph.cli_parser import create_parser


def main(argv: list[str] | None = None) -> None:
    args = create_parser().parse_args(argv)
    try:
        result = args.handler(args)
        if result is not None:
            emit_json(result)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        raise SystemExit(130) from None
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"anaxigraph: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
