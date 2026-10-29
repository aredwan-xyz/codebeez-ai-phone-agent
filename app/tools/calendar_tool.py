"""Google Calendar tool — schedule and check appointments."""

from datetime import datetime, timedelta
from typing import Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build

from app.config import get_settings
from app.models.call import CallSession
from app.tools.registry import ToolRegistry

log = structlog.get_logger()
settings = get_settings()


def _get_calendar_service():
    if not settings.google_credentials_path:
        raise RuntimeError("GOOGLE_CREDENTIALS_PATH not configured")
    creds = service_account.Credentials.from_service_account_file(
        settings.google_credentials_path,
        scopes=["https://www.googleapis.com/auth/calendar"],
    )
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


@ToolRegistry.register(
    name="schedule_appointment",
    description=(
        "Schedule a calendar appointment for the caller. "
        "Use when the caller wants to book a meeting, call, or appointment. "
        "Always confirm the date, time, and purpose before calling this tool."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Appointment title / subject"},
            "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
            "time": {"type": "string", "description": "Time in HH:MM 24h format"},
            "duration_minutes": {
                "type": "integer",
                "description": "Duration in minutes",
                "default": 30,
            },
            "attendee_email": {"type": "string", "description": "Caller's email address"},
            "notes": {"type": "string", "description": "Optional notes or agenda"},
        },
        "required": ["title", "date", "time"],
    },
)
async def schedule_appointment(args: dict, session: CallSession) -> dict[str, Any]:
    try:
        service = _get_calendar_service()
        start_dt = datetime.fromisoformat(f"{args['date']}T{args['time']}:00")
        end_dt = start_dt + timedelta(minutes=args.get("duration_minutes", 30))

        event_body: dict = {
            "summary": args["title"],
            "description": args.get("notes", ""),
            "start": {"dateTime": start_dt.isoformat(), "timeZone": settings.agent_timezone},
            "end": {"dateTime": end_dt.isoformat(), "timeZone": settings.agent_timezone},
        }
        if args.get("attendee_email"):
            event_body["attendees"] = [{"email": args["attendee_email"]}]

        event = (
            service.events()
            .insert(calendarId=settings.google_calendar_id, body=event_body, sendUpdates="all")
            .execute()
        )

        return {
            "success": True,
            "event_id": event["id"],
            "link": event.get("htmlLink"),
            "start": start_dt.isoformat(),
        }
    except Exception as e:
        log.exception("calendar.error")
        return {"success": False, "error": str(e)}


@ToolRegistry.register(
    name="check_availability",
    description="Check calendar availability for a given date range.",
    input_schema={
        "type": "object",
        "properties": {
            "date": {"type": "string", "description": "Date to check in YYYY-MM-DD"},
            "duration_minutes": {"type": "integer", "default": 30},
        },
        "required": ["date"],
    },
)
async def check_availability(args: dict, session: CallSession) -> dict[str, Any]:
    try:
        service = _get_calendar_service()
        day_start = datetime.fromisoformat(f"{args['date']}T09:00:00")
        day_end = datetime.fromisoformat(f"{args['date']}T17:00:00")

        events_result = (
            service.events()
            .list(
                calendarId=settings.google_calendar_id,
                timeMin=day_start.isoformat() + "Z",
                timeMax=day_end.isoformat() + "Z",
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )

        busy_slots = [
            {
                "start": e["start"].get("dateTime", e["start"].get("date")),
                "end": e["end"].get("dateTime", e["end"].get("date")),
            }
            for e in events_result.get("items", [])
        ]
        return {"date": args["date"], "busy_slots": busy_slots, "total_busy": len(busy_slots)}
    except Exception as e:
        log.exception("calendar.availability.error")
        return {"error": str(e)}
