"""Miscellaneous call-control tools."""

from typing import Any

from app.models.call import CallSession
from app.security import require_allowed_outbound
from app.tools.registry import ToolRegistry


@ToolRegistry.register(
    name="send_sms",
    description=(
        "Send an SMS text message to the caller. "
        "Use to send confirmation details, links, or follow-up information."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "SMS message body (max 160 chars)"},
        },
        "required": ["message"],
    },
)
async def send_sms(args: dict, session: CallSession) -> dict[str, Any]:
    from app.services.telephony import get_twilio_client

    try:
        require_allowed_outbound(session.from_number)
        client = get_twilio_client()
        msg = client.messages.create(
            body=args["message"][:160],
            from_=session.to_number,
            to=session.from_number,
        )
        return {"success": True, "sid": msg.sid}
    except Exception as e:
        return {"success": False, "error": str(e)}
