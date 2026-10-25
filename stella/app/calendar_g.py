"""Google Calendar. Токен создаётся скриптом scripts/google_auth.py на ПК."""
import datetime as dt
import os

from . import config

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def enabled() -> bool:
    return os.path.exists(config.GOOGLE_TOKEN_FILE)


def _svc():
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(config.GOOGLE_TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(config.GOOGLE_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds, cache_discovery=False)


def _parse(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=config.TZ)


def _fmt(e: dict) -> dict:
    return {"id": e["id"], "title": e.get("summary", ""),
            "start": e["start"].get("dateTime", e["start"].get("date")),
            "end": e["end"].get("dateTime", e["end"].get("date"))}


def list_events(start: str, end: str) -> list[dict]:
    if not enabled():
        return [{"error": "календарь не подключён"}]
    r = _svc().events().list(calendarId=config.CALENDAR_ID, timeMin=_parse(start).isoformat(),
                             timeMax=_parse(end).isoformat(), singleEvents=True,
                             orderBy="startTime", maxResults=25).execute()
    return [_fmt(e) for e in r.get("items", [])]


def add_event(title: str, start: str, duration_min: int = 60) -> dict:
    if not enabled():
        return {"error": "календарь не подключён"}
    s = _parse(start)
    body = {"summary": title,
            "start": {"dateTime": s.isoformat()},
            "end": {"dateTime": (s + dt.timedelta(minutes=duration_min)).isoformat()}}
    return _fmt(_svc().events().insert(calendarId=config.CALENDAR_ID, body=body).execute())


def move_event(event_id: str, new_start: str) -> dict:
    if not enabled():
        return {"error": "календарь не подключён"}
    svc = _svc()
    e = svc.events().get(calendarId=config.CALENDAR_ID, eventId=event_id).execute()
    old_s, old_e = _parse(e["start"]["dateTime"]), _parse(e["end"]["dateTime"])
    s = _parse(new_start)
    e["start"] = {"dateTime": s.isoformat()}
    e["end"] = {"dateTime": (s + (old_e - old_s)).isoformat()}
    return _fmt(svc.events().update(calendarId=config.CALENDAR_ID, eventId=event_id, body=e).execute())
