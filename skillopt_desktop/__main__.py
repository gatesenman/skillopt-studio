"""Entry point for SkillOpt Studio (console script: ``skillopt-studio``)."""
from __future__ import annotations

import argparse

from .app import run_desktop


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="skillopt-studio",
                                     description="SkillOpt Studio — desktop skill optimizer")
    parser.add_argument("--port", type=int, default=0,
                        help="loopback port (0 = auto-select)")
    parser.add_argument("--no-window", action="store_true",
                        help="run the backend only; open the URL in a browser")
    parser.add_argument("--dev", action="store_true", help="enable webview devtools")
    args = parser.parse_args(argv)
    return run_desktop(port=args.port, open_window=not args.no_window, dev=args.dev)


if __name__ == "__main__":
    raise SystemExit(main())
