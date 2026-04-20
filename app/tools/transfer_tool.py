"""Transfer-to-human and call-end tools."""

from typing import Any

import structlog

from app.config import get_settings
from app.models.call import CallSession
from app.services.telephony import warm_transfer
from app.tools.registry import ToolRegistry

log = structlog.get_logger()
settings = get_settings()


@ToolRegistry.register(
    name="transfer_to_human",
    description=(
        "Transfer the caller to a human agent. Use when: the caller explicitly requests a human, "
        "the issue is too complex to resolve automatically, or the caller is frustrated. "
        "Always inform the caller before transferring."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "reason": {"type": "string", "description": "Why the transfer is needed"},
            "department": {
                "type": "string",
                "enum": ["sales", "support", "billing", "general"],
                "description": "Which department to transfer to",
            },
        },
        "required": ["reason"],
    },
)
async def transfer_to_human(args: dict, session: CallSession) -> dict[str, Any]:
    department = args.get("department", "general")
    transfer_numbers = {
        "sales": "+15551110001",
        "support": "+15551110002",
        "billing": "+15551110003",
        "general": "+15551110000",
    }
    target = transfer_numbers.get(department, transfer_numbers["general"])
    twiml_url = f"{settings.base_url}/calls/transfer-twiml?target={target}"

    try:
        warm_transfer(session.call_sid, target, twiml_url)
        log.info("transfer.initiated", department=department, target=target)
        return {"success": True, "department": department, "message": "Transfer initiated"}
    except Exception as e:
        log.exception("transfer.error")
        return {"success": False, "error": str(e)}


@ToolRegistry.register(
    name="end_call",
    description=(
        "End the call gracefully. Use only when the caller says goodbye or "
        "the conversation is clearly complete."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Brief summary of what was accomplished"},
        },
    },
)
async def end_call(args: dict, session: CallSession) -> dict[str, Any]:
    from app.services.telephony import hangup_call
    try:
        hangup_call(session.call_sid)
        return {"success": True, "summary": args.get("summary", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}
