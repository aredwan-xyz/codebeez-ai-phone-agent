from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app.config import get_settings


def signed(path, data=None, *, websocket=False):
    scheme = "wss" if websocket else "https"
    signature = RequestValidator("test-twilio-token").compute_signature(
        f"{scheme}://phone.example.test{path}",
        data or {},
    )
    return {"X-Twilio-Signature": signature}


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


@pytest.mark.parametrize(
    "path", ["/admin/calls", "/admin/callers", "/admin/calls/CA1/turns", "/admin/active-sessions"]
)
def test_admin_denied_without_auth(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize(
    "path", ["/admin/knowledge-base/ingest", "/admin/knowledge-base/ingest-text"]
)
def test_admin_writes_denied_without_auth(client, path):
    assert client.post(path).status_code == 401


def test_admin_missing_config_fails_closed(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "admin_api_key", "")
    assert client.get("/admin/calls").status_code == 503


def test_valid_admin_can_ingest(client):
    with patch("app.api.admin.ingest_document", new_callable=AsyncMock) as ingest:
        response = client.post(
            "/admin/knowledge-base/ingest-text",
            params={"source": "test", "content": "demo"},
            headers={"Authorization": "Bearer test-admin-key"},
        )
        assert response.status_code == 200
        ingest.assert_awaited_once_with(source="test", content="demo")


@pytest.mark.parametrize("path", ["/calls/inbound", "/calls/outbound", "/calls/status"])
def test_unsigned_twilio_callbacks_rejected(client, path):
    assert client.post(path, data={"CallSid": "CA123"}).status_code == 403


def test_inbound_call_returns_twiml(client):
    data = {"CallSid": "CA123", "From": "+15551234567", "To": "+15559876543"}
    response = client.post("/calls/inbound", data=data, headers=signed("/calls/inbound", data))
    assert response.status_code == 200
    assert "wss://phone.example.test/ws/call/CA123" in response.text


def test_tampered_callback_rejected(client):
    data = {"CallSid": "CA123", "From": "+15551234567", "To": "+15559876543"}
    headers = signed("/calls/inbound", data)
    data["CallSid"] = "CAattacker"
    assert client.post("/calls/inbound", data=data, headers=headers).status_code == 403


def test_forwarded_host_is_not_trusted(client):
    data = {"CallSid": "CA123", "From": "+15551234567", "To": "+15559876543"}
    signature = RequestValidator("test-twilio-token").compute_signature(
        "https://attacker.test/calls/inbound",
        data,
    )
    assert (
        client.post(
            "/calls/inbound",
            data=data,
            headers={
                "X-Twilio-Signature": signature,
                "X-Forwarded-Host": "attacker.test",
            },
        ).status_code
        == 403
    )


@pytest.mark.parametrize("method", ["get", "post"])
def test_signed_transfer_preserves_plus_number(client, monkeypatch, method):
    target = "+15551110001"
    monkeypatch.setattr(get_settings(), "outbound_enabled", True)
    monkeypatch.setattr(get_settings(), "outbound_allowed_numbers", [target])
    path = "/calls/transfer-twiml?" + urlencode({"target": target})
    response = getattr(client, method)(path, headers=signed(path))
    assert response.status_code == 200
    assert target in response.text


def test_transfer_rejects_unapproved_destination(client):
    path = "/calls/transfer-twiml?" + urlencode({"target": "+15551110001"})
    assert client.get(path, headers=signed(path)).status_code == 403


def test_outbound_requires_auth_and_destination_opt_in(client, monkeypatch):
    with patch("app.services.telephony.get_twilio_client") as factory:
        payload = {"to_number": "+15551110001"}
        assert client.post("/calls/make", json=payload).status_code == 401
        headers = {"Authorization": "Bearer test-admin-key"}
        assert client.post("/calls/make", json=payload, headers=headers).status_code == 403
        factory.assert_not_called()
        monkeypatch.setattr(get_settings(), "outbound_enabled", True)
        monkeypatch.setattr(get_settings(), "outbound_allowed_numbers", [payload["to_number"]])
        factory.return_value.calls.create.return_value.sid = "CAcreated"
        response = client.post("/calls/make", json=payload, headers=headers)
        assert response.json()["call_sid"] == "CAcreated"


def test_unsigned_websocket_rejected_before_session_access(client):
    with patch("app.api.websocket.SessionStore") as store:
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/call/CA123"):
            pass
        store.assert_not_called()


def test_signed_websocket_cannot_replace_call_identity(client):
    store = MagicMock(save_session=AsyncMock(), delete_session=AsyncMock())
    with patch("app.api.websocket.SessionStore", return_value=store):
        path = "/ws/call/CA123"
        with client.websocket_connect(path, headers=signed(path, websocket=True)) as ws:
            ws.send_json({"event": "start", "start": {"callSid": "CAother", "streamSid": "MZ1"}})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        store.save_session.assert_not_awaited()
        store.delete_session.assert_not_awaited()


def test_signed_websocket_starts_once_and_cleans_only_own_session(client):
    store = MagicMock(save_session=AsyncMock(), delete_session=AsyncMock())
    orchestrator = MagicMock(start=AsyncMock(), stop=AsyncMock())
    orchestrator._stt = MagicMock(start=AsyncMock(), stop=AsyncMock())
    with (
        patch("app.api.websocket.SessionStore", return_value=store),
        patch(
            "app.api.websocket.CallOrchestrator",
            return_value=orchestrator,
        ),
    ):
        path = "/ws/call/CA123"
        with client.websocket_connect(path, headers=signed(path, websocket=True)) as ws:
            start = {"event": "start", "start": {"callSid": "CA123", "streamSid": "MZ1"}}
            ws.send_json(start)
            ws.send_json(start)
            with pytest.raises(WebSocketDisconnect):
                ws.receive_text()
        store.save_session.assert_awaited_once()
        orchestrator.start.assert_awaited_once()
        store.delete_session.assert_awaited_once_with("CA123")
