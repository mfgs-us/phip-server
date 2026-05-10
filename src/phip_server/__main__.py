"""Entry point — run with `phip-server` after install, or
`python -m phip_server`."""

from __future__ import annotations

import argparse
import sys

import uvicorn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="phip-server")
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    uvicorn.run(
        "phip_server.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        reload=args.reload,
        workers=args.workers,
        log_level=args.log_level,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
