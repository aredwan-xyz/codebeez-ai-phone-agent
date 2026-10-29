from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client(monkeypatch):
    # API boundary tests need no live databases or provider credentials.
    import app.main as main
    from app.config import get_settings

    monkeypatch.setattr(main, "init_db", AsyncMock())
    monkeypatch.setattr(main, "init_redis", AsyncMock())
    monkeypatch.setattr(get_settings(), "admin_api_key", "test-admin-key")
    monkeypatch.setattr(get_settings(), "twilio_auth_token", "test-twilio-token")
    monkeypatch.setattr(get_settings(), "base_url", "https://phone.example.test")
    monkeypatch.setattr(get_settings(), "outbound_enabled", False)
    monkeypatch.setattr(get_settings(), "outbound_allowed_numbers", [])
    with TestClient(app) as c:
        yield c
