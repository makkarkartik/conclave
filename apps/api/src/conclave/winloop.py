"""Windows: psycopg async requires a SelectorEventLoop; the default ProactorEventLoop
raises InterfaceError. Import this module before any event loop is created (main.py,
runner.py, tests/conftest.py). No-op elsewhere."""

from __future__ import annotations

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
