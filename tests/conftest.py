"""Shared fixtures for issue-bot tests."""

import os
import pytest
import httpx
from unittest.mock import AsyncMock

from issue_bot import deps
from issue_bot.core.store import Store


def make_test_config(**overrides) -> dict:
    """Create a minimal config dict for testing."""
    cfg = {
        "gitlab_token": "test-token",
        "gitlab_url": "https://gitlab.example.com",
        "mm_slash_token": "test-slash-token",
        "mm_site_url": "http://localhost:8065",
        "bot_url": "http://localhost:8321",
        "llm_provider": "openai",
        "llm_api_key": "test-key",
        "llm_model": "gpt-4o",
        "llm_base_url": "",
        "db_path": ":memory:",
        "webhook_secret": "",
        "mm_bot_token": "test-bot-token",
        "mm_notify_channel_id": "",
        "github_token": "test-gh-token",
        "github_url": "https://api.github.com",
        "default_project": "default",
        "projects": {
            "default": {
                "id": "42",
                "name": "Default Project",
                "labels": "bug,enhancement,infrastructure",
                "backend": "gitlab",
            },
        },
    }
    cfg.update(overrides)
    return cfg


# Env vars needed so the lifespan's load_config() doesn't crash
_LIFESPAN_ENV = {
    "GITLAB_TOKEN": "test-token",
    "MM_SLASH_TOKEN": "test-slash-token",
    "GITLAB_PROJECT_ID": "42",
    "BOT_DB_PATH": ":memory:",
}


@pytest.fixture
def cfg():
    return make_test_config()


@pytest.fixture
def store(tmp_path):
    db = Store(str(tmp_path / "test.db"))
    yield db
    db.close()


@pytest.fixture
def app_client(monkeypatch, store):
    """Create a TestClient with deps patched for testing."""
    for k, v in _LIFESPAN_ENV.items():
        monkeypatch.setenv(k, v)

    from fastapi.testclient import TestClient
    from app import app

    client = TestClient(app, raise_server_exceptions=False)

    # Override deps set by lifespan with test values
    cfg = make_test_config()
    deps.CFG = cfg
    deps.store = store
    deps.http_client = AsyncMock(spec=httpx.AsyncClient)
    yield client
