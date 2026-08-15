"""API server entrypoint: python -m conclave.serve [--port 8000] [--reload]

Exists (rather than `python -m uvicorn conclave.main:app`) because the uvicorn CLI
creates its event loop before importing the app — too late for the Windows selector
loop policy psycopg async requires. Here the policy is set first.
"""

from __future__ import annotations

import conclave.winloop  # noqa: F401 — must precede loop creation

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Conclave API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("conclave.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
