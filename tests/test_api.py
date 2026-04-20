from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "ACtest")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test_token")
    monkeypatch.setenv("TWILIO_PHONE_NUMBER", "+15550000000")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setenv("DEEPGRAM_API_KEY", "test")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "test")


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_inbound_call_returns_twiml(client):
    resp = client.post(
        "/calls/inbound",
        data={"CallSid": "CA123", "From": "+15551234567", "To": "+15559876543"},
    )
    assert resp.status_code == 200
    assert "Stream" in resp.text or "Connect" in resp.text


def test_transfer_twiml(client):
    resp = client.get("/calls/transfer-twiml?target=%2B15551110001")
    assert resp.status_code == 200
    assert "Dial" in resp.text
