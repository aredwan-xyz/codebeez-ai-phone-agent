"""HubSpot CRM tool — lookup and update contact records."""

from typing import Any

import httpx
import structlog

from app.config import get_settings
from app.models.call import CallSession
from app.tools.registry import ToolRegistry

log = structlog.get_logger()
settings = get_settings()

HUBSPOT_BASE = "https://api.hubapi.com"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {settings.hubspot_api_key}",
        "Content-Type": "application/json",
    }


@ToolRegistry.register(
    name="lookup_crm",
    description=(
        "Look up a contact in HubSpot CRM by phone number or email. "
        "Use this at the start of a call to identify the caller and personalize the interaction."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "phone": {"type": "string", "description": "Phone number to search"},
            "email": {"type": "string", "description": "Email to search (alternative to phone)"},
        },
    },
)
async def lookup_crm(args: dict, session: CallSession) -> dict[str, Any]:
    if not settings.hubspot_api_key:
        return {"error": "CRM not configured"}

    phone = args.get("phone") or session.from_number
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{HUBSPOT_BASE}/crm/v3/objects/contacts/search",
                headers=_headers(),
                json={
                    "filterGroups": [
                        {
                            "filters": [
                                {
                                    "propertyName": "phone",
                                    "operator": "EQ",
                                    "value": phone,
                                }
                            ]
                        }
                    ],
                    "properties": [
                        "firstname",
                        "lastname",
                        "email",
                        "phone",
                        "company",
                        "jobtitle",
                        "hs_lead_status",
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("total", 0) == 0:
                return {"found": False}
            contact = data["results"][0]
            props = contact["properties"]
            return {
                "found": True,
                "id": contact["id"],
                "name": f"{props.get('firstname', '')} {props.get('lastname', '')}".strip(),
                "email": props.get("email"),
                "company": props.get("company"),
                "title": props.get("jobtitle"),
                "lead_status": props.get("hs_lead_status"),
            }
    except Exception as e:
        log.exception("crm.lookup.error")
        return {"error": str(e)}


@ToolRegistry.register(
    name="update_crm",
    description="Update a CRM contact record after a call interaction.",
    input_schema={
        "type": "object",
        "properties": {
            "contact_id": {"type": "string"},
            "notes": {"type": "string", "description": "Call notes to append"},
            "lead_status": {"type": "string", "description": "New lead status if changed"},
        },
        "required": ["contact_id"],
    },
)
async def update_crm(args: dict, session: CallSession) -> dict[str, Any]:
    if not settings.hubspot_api_key:
        return {"error": "CRM not configured"}

    properties: dict = {}
    if args.get("lead_status"):
        properties["hs_lead_status"] = args["lead_status"]

    try:
        async with httpx.AsyncClient() as client:
            if properties:
                resp = await client.patch(
                    f"{HUBSPOT_BASE}/crm/v3/objects/contacts/{args['contact_id']}",
                    headers=_headers(),
                    json={"properties": properties},
                )
                resp.raise_for_status()

            if args.get("notes"):
                await client.post(
                    f"{HUBSPOT_BASE}/crm/v3/objects/notes",
                    headers=_headers(),
                    json={
                        "properties": {
                            "hs_note_body": args["notes"],
                            "hs_timestamp": "now",
                        },
                        "associations": [
                            {
                                "to": {"id": args["contact_id"]},
                                "types": [
                                    {
                                        "associationCategory": "HUBSPOT_DEFINED",
                                        "associationTypeId": 202,
                                    }
                                ],
                            }
                        ],
                    },
                )

        return {"success": True}
    except Exception as e:
        log.exception("crm.update.error")
        return {"error": str(e)}
