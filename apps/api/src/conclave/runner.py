"""Standalone turn-runner role: python -m conclave.runner

Run any number of these alongside the API (CONCLAVE_EMBED_RUNNER=0); Postgres
arbitrates room claims via SKIP LOCKED.
"""

from __future__ import annotations

import conclave.winloop  # noqa: F401 — must precede loop creation (psycopg async on Windows)

import asyncio
import logging

from conclave.db.session import init_db
from conclave.services.turn_runner import runner_loop


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    async def _run() -> None:
        await init_db()
        await runner_loop()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
