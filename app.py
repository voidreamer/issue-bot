"""
Mattermost -> LLM -> GitLab/GitHub Issue Creator

FastAPI application — lifespan wiring + router includes.
"""

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI

from issue_bot import deps
from issue_bot.core.config import load_config
from issue_bot.core.store import Store
from issue_bot.routes import health, slash, actions, webhooks

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app):
    cfg = load_config()
    deps.CFG = cfg
    deps.http_client = httpx.AsyncClient(timeout=60.0)
    deps.store = Store(cfg["db_path"])
    deps.store.cleanup_expired()
    yield
    await deps.http_client.aclose()
    deps.store.close()


app = FastAPI(title="Issue Bot", lifespan=lifespan)
app.include_router(health.router)
app.include_router(slash.router)
app.include_router(actions.router)
app.include_router(webhooks.router)
