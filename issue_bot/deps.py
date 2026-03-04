"""
Shared state — populated during lifespan, importable by route modules.
"""

import httpx

from issue_bot.core.store import Store

CFG: dict = {}
http_client: httpx.AsyncClient = None  # type: ignore
store: Store = None  # type: ignore
