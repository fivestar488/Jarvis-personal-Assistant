"""Oura Ring: last night's sleep and today's readiness, for the morning greeting and "how did I sleep?".

Setup (once): create an app at https://cloud.ouraring.com/oauth/applications with the redirect URI
http://localhost:8889/callback, put its client ID and secret in .env (JARVIS_OURA_CLIENT_ID / _SECRET), then run
jarvis.bat --connect-oura. Health data stays on this PC (data/oura_token.json holds only the sign-in).
"""
import base64
import datetime as dt
import hashlib
import json
import os
import secrets
import time
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests

from . import config
from .tools import tool

TOKEN_FILE = config.DATA_DIR / "oura_token.json"
AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
API = "https://api.ouraring.com/v2/usercollection/"
REDIRECT_URI = "http://localhost:8889/callback"
SCOPES = "daily personal"
HEADERS = {"User-Agent": "JarvisPersonalAssistant/1.0"}  # Oura requires a non-empty User-Agent
NOT_CONNECTED = ("Oura isn't connected yet. Tell the user to follow 'Connect Oura' in the README, then run "
                 "jarvis.bat --connect-oura")


def connected():
    return TOKEN_FILE.exists()


def connect():
    """Browser sign-in (OAuth with PKCE). Run once from the console: jarvis.bat --connect-oura"""
    if not (config.OURA_CLIENT_ID and config.OURA_CLIENT_SECRET):
        raise SystemExit("Put JARVIS_OURA_CLIENT_ID and JARVIS_OURA_CLIENT_SECRET in .env first (see 'Connect Oura' in the README).")
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    state = secrets.token_urlsafe(16)
    url = AUTHORIZE_URL + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": config.OURA_CLIENT_ID, "redirect_uri": REDIRECT_URI, "scope": SCOPES,
        "state": state, "code_challenge": challenge, "code_challenge_method": "S256"})
    got = {}

    class Callback(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            ok = got.get("state") == state and "code" in got
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Oura connected. You can close this tab.</h2>" if ok else
                             b"<h2>Oura sign-in didn't complete. Close this tab and try again.</h2>")

        def log_message(self, *args):
            pass

    server = HTTPServer(("localhost", 8889), Callback)
    webbrowser.open(url)
    server.handle_request()  # waits for the browser to come back
    server.server_close()
    if got.get("state") != state or "code" not in got:
        raise SystemExit(f"Oura sign-in failed: {got.get('error', 'no code returned')}")
    _save_token(requests.post(TOKEN_URL, headers=HEADERS, timeout=20, data={
        "grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT_URI,
        "client_id": config.OURA_CLIENT_ID, "client_secret": config.OURA_CLIENT_SECRET, "code_verifier": verifier}))


def _save_token(r):
    r.raise_for_status()
    t = r.json()
    t["expires_at"] = time.time() + t.get("expires_in", 86400) - 60
    TOKEN_FILE.write_text(json.dumps(t))


def _access_token():
    t = json.loads(TOKEN_FILE.read_text())
    if time.time() >= t.get("expires_at", 0) and t.get("refresh_token"):
        # Oura's refresh tokens are single use, so the new one must be saved straight away.
        _save_token(requests.post(TOKEN_URL, headers=HEADERS, timeout=20, data={
            "grant_type": "refresh_token", "refresh_token": t["refresh_token"],
            "client_id": config.OURA_CLIENT_ID, "client_secret": config.OURA_CLIENT_SECRET}))
        t = json.loads(TOKEN_FILE.read_text())
    return t["access_token"]


def _latest(collection, today):
    r = requests.get(API + collection, timeout=20, headers={**HEADERS, "Authorization": f"Bearer {_access_token()}"},
                     params={"start_date": (today - dt.timedelta(days=1)).isoformat(),
                             "end_date": (today + dt.timedelta(days=1)).isoformat()})
    r.raise_for_status()
    items = [i for i in r.json().get("data", []) if i.get("day")]
    return sorted(items, key=lambda i: i["day"])[-1] if items else None


def last_night():
    """{'day', 'sleep_score', 'readiness', 'hours'} for the latest night, or None."""
    today = dt.date.today()
    sleep_day, readiness = _latest("daily_sleep", today), _latest("daily_readiness", today)
    if not (sleep_day or readiness):
        return None
    hours = None
    try:  # the main sleep period, for how long you actually slept
        today_iso = (sleep_day or readiness)["day"]
        r = requests.get(API + "sleep", timeout=20, headers={**HEADERS, "Authorization": f"Bearer {_access_token()}"},
                         params={"start_date": today_iso, "end_date": (dt.date.fromisoformat(today_iso) + dt.timedelta(days=1)).isoformat()})
        periods = [p for p in r.json().get("data", []) if p.get("day") == today_iso and p.get("total_sleep_duration")]
        if periods:
            hours = max(p["total_sleep_duration"] for p in periods) / 3600
    except Exception:
        pass
    return {"day": (sleep_day or readiness)["day"], "sleep_score": (sleep_day or {}).get("score"),
            "readiness": (readiness or {}).get("score"), "hours": hours}


def describe(night):
    parts = []
    if night["hours"]:
        h, m = int(night["hours"]), round(night["hours"] % 1 * 60)
        parts.append(f"you slept {h} hours {m}" if m else f"you slept {h} hours")
    if night["sleep_score"] is not None:
        parts.append(f"sleep score {night['sleep_score']}")
    if night["readiness"] is not None:
        parts.append(f"readiness {night['readiness']}")
    text = ", ".join(parts)
    if night["readiness"] is not None and night["readiness"] < 70:
        text += ", so take it a bit easier today"
    return text[0].upper() + text[1:] + "." if text else ""


@tool("Last night's sleep and today's readiness from the user's Oura Ring. Use for 'how did I sleep?', "
      "'what's my readiness?', or a morning briefing.")
def sleep_report():
    if not connected():
        return NOT_CONNECTED
    night = last_night()
    if not night:
        return "Oura has no sleep data for last night yet (the ring may not have synced)."
    return f"{night['day']}: " + describe(night)
