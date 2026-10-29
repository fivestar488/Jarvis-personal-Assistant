"""Gmail and Google Calendar. One-time setup: see "Connect Gmail & Calendar" in the README, then run
`jarvis.bat --connect-google`.
"""
import base64
import datetime as dt
import html
import re
import threading
from email.message import EmailMessage

from . import config
from .tools import I, S, _clip, confirm, tool

SCOPES = ["https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/calendar"]
CLIENT_FILE = config.DATA_DIR / "google_credentials.json"
TOKEN_FILE = config.DATA_DIR / "google_token.json"
NOT_CONNECTED = ("Gmail and Google Calendar aren't connected yet. Tell the user to follow 'Connect Gmail & Calendar' "
                 "in the README, then run: jarvis.bat --connect-google")

_lock = threading.Lock()
_services = {}


class NotConnected(Exception):
    pass


def connected():
    return TOKEN_FILE.exists()


def connect():
    """Interactive sign-in in the browser. Run once via `jarvis.py --connect-google`."""
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not CLIENT_FILE.exists():
        raise NotConnected(f"Missing {CLIENT_FILE}. Download your OAuth client JSON from Google Cloud and save it there.")
    creds = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES).run_local_server(port=0)
    TOKEN_FILE.write_text(creds.to_json())


def _service(name, version):
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    with _lock:
        if not TOKEN_FILE.exists():
            raise NotConnected(NOT_CONNECTED)
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if not creds.valid:
            try:
                creds.refresh(Request())
            except RefreshError:
                raise NotConnected("The Google sign-in has expired. Tell the user to run: jarvis.bat --connect-google")
            TOKEN_FILE.write_text(creds.to_json())
            _services.clear()
        if name not in _services:
            _services[name] = build(name, version, credentials=creds, cache_discovery=False)
        return _services[name]


def google_tool(description, properties=None, required=()):
    """Like @tool, but turns a missing connection into a message Jarvis can relay."""
    def wrap(fn):
        def safe(**kwargs):
            try:
                return fn(**kwargs)
            except NotConnected as e:
                return str(e)
        safe.__name__ = fn.__name__
        tool(description, properties, required)(safe)
        return fn
    return wrap


# ---------------------------------------------------------------- Gmail

def _header(msg, name):
    return next((h["value"] for h in msg["payload"].get("headers", []) if h["name"].lower() == name.lower()), "")


def _body(payload):
    """Best-effort plain text from a Gmail message payload."""
    def walk(part, mime):
        if part.get("mimeType") == mime and part.get("body", {}).get("data"):
            return base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", "replace")
        for sub in part.get("parts", []):
            found = walk(sub, mime)
            if found:
                return found
        return None
    text = walk(payload, "text/plain")
    if text:
        return text
    page = walk(payload, "text/html") or ""
    page = re.sub(r"(?is)<(script|style).*?</\1>", "", page)
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))).strip()


@google_tool("Search the user's Gmail. Uses Gmail search syntax, e.g. 'is:unread in:inbox', 'from:amazon newer_than:7d', "
             "'subject:invoice'. Returns sender, subject, date, a snippet and the message id.",
             {"query": S("Gmail search query (default: unread inbox mail)"), "max_results": I("Default 10")})
def gmail_search(query="is:unread in:inbox", max_results=10):
    gmail = _service("gmail", "v1")
    found = gmail.users().messages().list(userId="me", q=query, maxResults=min(max_results, 25)).execute()
    lines = []
    for ref in found.get("messages", []):
        m = gmail.users().messages().get(userId="me", id=ref["id"], format="metadata",
                                         metadataHeaders=["From", "Subject", "Date"]).execute()
        lines.append(f"[{m['id']}] From: {_header(m, 'From')} | Subject: {_header(m, 'Subject')} | "
                     f"Date: {_header(m, 'Date')}\n    {html.unescape(m.get('snippet', ''))}")
    return "\n".join(lines) or "No emails match."


@google_tool("Read the full text of one email by its message id (from gmail_search).",
             {"message_id": S("Message id")}, ["message_id"])
def gmail_read(message_id):
    m = _service("gmail", "v1").users().messages().get(userId="me", id=message_id, format="full").execute()
    head = f"From: {_header(m, 'From')}\nTo: {_header(m, 'To')}\nSubject: {_header(m, 'Subject')}\nDate: {_header(m, 'Date')}\n\n"
    return _clip(head + _body(m["payload"]), 12000)


def _build(to, subject, body, reply_to_id):
    msg = EmailMessage()
    msg["To"], msg["Subject"] = to, subject
    msg.set_content(body)
    thread_id = None
    if reply_to_id:
        original = _service("gmail", "v1").users().messages().get(
            userId="me", id=reply_to_id, format="metadata", metadataHeaders=["Message-ID", "Subject"]).execute()
        msg["In-Reply-To"] = msg["References"] = _header(original, "Message-ID")
        thread_id = original["threadId"]
    raw = {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}
    if thread_id:
        raw["threadId"] = thread_id
    return raw


EMAIL_PROPS = {
    "to": S("Recipient email address"),
    "subject": S("Subject line (for replies, usually 'Re: ' + original subject)"),
    "body": S("Email body text"),
    "reply_to_id": S("Message id being replied to, if this is a reply"),
}


@google_tool("Save an email as a Gmail draft for the user to review and send. Prefer this over gmail_send unless "
             "the user clearly asked to send.", EMAIL_PROPS, ["to", "subject", "body"])
def gmail_draft(to, subject, body, reply_to_id=None):
    _service("gmail", "v1").users().drafts().create(
        userId="me", body={"message": _build(to, subject, body, reply_to_id)}).execute()
    return f"Draft to {to} saved in Gmail."


@google_tool("Send an email from the user's Gmail. The user is asked to approve it first.",
             EMAIL_PROPS, ["to", "subject", "body"])
def gmail_send(to, subject, body, reply_to_id=None):
    if not confirm(f"Send this email?\nTo: {to}\nSubject: {subject}\n\n{body}"):
        return "User declined to send."
    _service("gmail", "v1").users().messages().send(userId="me", body=_build(to, subject, body, reply_to_id)).execute()
    return f"Email sent to {to}."


@google_tool("Mark an email as read.", {"message_id": S("Message id")}, ["message_id"])
def gmail_mark_read(message_id):
    _service("gmail", "v1").users().messages().modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}).execute()
    return "Marked as read."


# ---------------------------------------------------------------- Calendar

def _local(when):
    return when.astimezone() if when.tzinfo else when.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)


def list_events(start, end):
    """Events from all of the user's visible calendars between two datetimes, sorted by start."""
    cal = _service("calendar", "v3")
    calendars = [c for c in cal.calendarList().list().execute().get("items", []) if c.get("selected", c.get("primary"))]
    events = []
    for c in calendars:
        items = cal.events().list(calendarId=c["id"], timeMin=_local(start).isoformat(), timeMax=_local(end).isoformat(),
                                  singleEvents=True, orderBy="startTime", maxResults=50).execute().get("items", [])
        for e in items:
            all_day = "date" in e["start"]
            s = e["start"].get("dateTime") or e["start"]["date"]
            f = e["end"].get("dateTime") or e["end"]["date"]
            events.append({
                "id": e["id"], "calendar_id": c["id"], "title": e.get("summary", "(no title)"),
                "start": s, "end": f, "all_day": all_day, "location": e.get("location", ""),
                "calendar": c.get("summaryOverride") or c.get("summary", ""),
            })
    return sorted(events, key=lambda e: (e["start"][:10], not e["all_day"], e["start"]))


@google_tool("List events on the user's Google Calendar (all their calendars).",
             {"days": I("How many days to look ahead, starting today (default 1 = today only)"),
              "start_date": S("Optional start date YYYY-MM-DD (default today)")})
def calendar_events(days=1, start_date=None):
    start = dt.datetime.fromisoformat(start_date) if start_date else dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    events = list_events(start, start + dt.timedelta(days=days))
    if not events:
        return "No events."
    lines = []
    for e in events:
        when = e["start"] + " (all day)" if e["all_day"] else f"{e['start']} to {e['end']}"
        lines.append(f"[{e['calendar_id']}|{e['id']}] {e['title']} — {when}" + (f" @ {e['location']}" if e["location"] else ""))
    return "\n".join(lines)


@google_tool("Add an event to the user's primary Google Calendar.",
             {"title": S("Event title"),
              "start": S("Start as local ISO datetime 'YYYY-MM-DDTHH:MM', or 'YYYY-MM-DD' for an all-day event"),
              "end": S("End, same format. Default: 1 hour after start (or same day for all-day)"),
              "location": S("Optional location"), "description": S("Optional notes")},
             ["title", "start"])
def calendar_create_event(title, start, end=None, location="", description=""):
    body = {"summary": title, "location": location, "description": description}
    if len(start) == 10:
        day = dt.date.fromisoformat(start)
        last = dt.date.fromisoformat(end) if end else day
        body["start"] = {"date": day.isoformat()}
        body["end"] = {"date": (last + dt.timedelta(days=1)).isoformat()}
    else:
        s = _local(dt.datetime.fromisoformat(start))
        f = _local(dt.datetime.fromisoformat(end)) if end else s + dt.timedelta(hours=1)
        body["start"], body["end"] = {"dateTime": s.isoformat()}, {"dateTime": f.isoformat()}
    created = _service("calendar", "v3").events().insert(calendarId="primary", body=body).execute()
    return f"Added '{title}' to the calendar. Link: {created.get('htmlLink')}"


@google_tool("Delete a calendar event. The user is asked to approve it first.",
             {"event_ref": S("The '[calendar_id|event_id]' reference from calendar_events, without brackets"),
              "title": S("The event's title, shown to the user when asking")},
             ["event_ref", "title"])
def calendar_delete_event(event_ref, title):
    calendar_id, _, event_id = event_ref.strip("[]").rpartition("|")
    if not confirm(f"Delete '{title}' from your calendar?"):
        return "User declined."
    _service("calendar", "v3").events().delete(calendarId=calendar_id or "primary", eventId=event_id).execute()
    return f"Deleted '{title}'."
