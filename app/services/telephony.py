"""Twilio REST API wrapper — outbound calls, status updates."""

import structlog
from twilio.rest import Client

from app.config import get_settings

log = structlog.get_logger()
settings = get_settings()

_client: Client | None = None


def get_twilio_client() -> Client:
    global _client
    if _client is None:
        _client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
    return _client


def make_outbound_call(to_number: str, twiml_url: str) -> str:
    """Initiate an outbound call. Returns the CallSid."""
    client = get_twilio_client()
    call = client.calls.create(
        to=to_number,
        from_=settings.twilio_phone_number,
        url=twiml_url,
        record=False,
    )
    log.info("call.outbound.created", sid=call.sid, to=to_number)
    return call.sid


def hangup_call(call_sid: str):
    client = get_twilio_client()
    client.calls(call_sid).update(status="completed")
    log.info("call.hangup", sid=call_sid)


def warm_transfer(call_sid: str, target_number: str, twiml_url: str):
    """Bridge the call to a human agent via TwiML redirect."""
    client = get_twilio_client()
    client.calls(call_sid).update(url=twiml_url, method="POST")
    log.info("call.transfer", sid=call_sid, target=target_number)
