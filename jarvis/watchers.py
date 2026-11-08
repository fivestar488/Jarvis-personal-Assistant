"""Watchers: "tell me when the price drops", "tell me when this page says In stock", "tell me when Amazon emails
that it shipped". Each one is a fixed kind of check that runs on a timer for free (no Claude involved) and alerts
you on the PC, phone and Telegram only when something changes. Jarvis never writes or runs code for a watcher."""
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import threading
import time
import xml.etree.ElementTree as ET

import requests

from . import config
from .tools import I, S, tool

WATCHERS_FILE = config.DATA_DIR / "watchers.json"
MAX_WATCHERS = 20
# Minutes between checks: the default, and the minimum (to be polite to websites).
DEFAULT_EVERY = {"page_text": 60, "page_change": 60, "price": 60, "rss": 60, "email": 10}
MIN_EVERY = {"page_text": 15, "page_change": 15, "price": 15, "rss": 15, "email": 5}
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/130.0 Safari/537.36", "Accept-Language": "en,he;q=0.8"}
PRICE_RE = re.compile(r"(?:[$£€₪]|USD|ILS|EUR|GBP|NIS)\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
                      r"|(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(?:[₪€]|ILS|NIS|EUR)")

_lock = threading.Lock()
_loop = None


# ---------------------------------------------------------------- the checks

def _page_text(url):
    """A web page as plain visible text."""
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", r.text)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


def _find_price(text, near=""):
    """The first price on the page (after the words in `near`, if given)."""
    if near:
        at = text.lower().find(near.lower())
        if at < 0:
            return None
        text = text[at:]
    m = PRICE_RE.search(text)
    return float((m.group(1) or m.group(2)).replace(",", "")) if m else None


def _feed_items(url):
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for node in root.iter():
        tag = node.tag.split("}")[-1]
        if tag in ("item", "entry"):
            title = next((c.text for c in node if c.tag.split("}")[-1] == "title"), "") or ""
            link = next((c.text or c.get("href", "") for c in node if c.tag.split("}")[-1] == "link"), "") or ""
            items.append({"title": html.unescape(title.strip()), "link": link.strip()})
    return items


def _email_ids(query):
    from . import google_tools
    gmail = google_tools._service("gmail", "v1")
    found = gmail.users().messages().list(userId="me", q=query, maxResults=10).execute().get("messages", [])
    return [m["id"] for m in found], gmail


def check(w):
    """Run one watcher. Updates w["state"] and returns an alert message, or None if nothing worth saying changed.
    The first run only records how things are now."""
    kind, target, st = w["kind"], w["target"], w["state"]
    first = not st
    if kind == "page_text":
        found = w["text"].lower() in _page_text(target).lower()
        was = st.get("found")
        st["found"] = found
        if not first and found != was and found == (w.get("mode", "appears") == "appears"):
            return f"\"{w['text']}\" {'is now on' if found else 'has gone from'} {target}"
    elif kind == "page_change":
        text = _page_text(target)[:20000]
        old = st.get("text")
        st["text"] = text
        if not first and old is not None and difflib.SequenceMatcher(None, old, text).quick_ratio() < 0.98:
            return f"the page changed: {target}"
    elif kind == "price":
        price = _find_price(_page_text(target), w.get("text", ""))
        if price is None:
            st["missing"] = st.get("missing", 0) + 1
            return "I can't find the price on the page any more" if st["missing"] == 3 else None
        old, below = st.get("price"), w.get("below")
        st.update(price=price, missing=0)
        if first:
            return None
        if below is not None:
            armed = st.get("armed", True)
            if price <= below and armed:
                st["armed"] = False
                return f"the price is {price:g}, at or under your target of {below:g}: {target}"
            if price > below:
                st["armed"] = True
        elif old is not None and price < old:
            return f"the price dropped from {old:g} to {price:g}: {target}"
    elif kind == "rss":
        items = _feed_items(target)
        keys = [hashlib.sha1((i["link"] or i["title"]).encode()).hexdigest()[:12] for i in items]
        seen = set(st.get("seen", []))
        st["seen"] = (st.get("seen", []) + [k for k in keys if k not in seen])[-300:]
        word = w.get("text", "").lower()
        new = [i for i, k in zip(items, keys) if k not in seen and (not word or word in i["title"].lower())]
        if not first and new:
            return f"{len(new)} new: " + "; ".join(i["title"] for i in new[:3])
    elif kind == "email":
        ids, gmail = _email_ids(target)
        seen = set(st.get("seen", []))
        st["seen"] = (st.get("seen", []) + [i for i in ids if i not in seen])[-300:]
        new = [i for i in ids if i not in seen]
        if not first and new:
            from . import google_tools
            m = gmail.users().messages().get(userId="me", id=new[0], format="metadata",
                                             metadataHeaders=["From", "Subject"]).execute()
            sender = google_tools._header(m, "From").split("<")[0].strip().strip('"')
            return f"new email from {sender}: \"{google_tools._header(m, 'Subject')}\"" + \
                (f" (and {len(new) - 1} more)" if len(new) > 1 else "")
    return None


def _describe_now(w):
    """What the first check saw, for the confirmation."""
    st = w["state"]
    if w["kind"] == "page_text":
        return f"\"{w['text']}\" is {'already' if st['found'] else 'not yet'} on the page"
    if w["kind"] == "price":
        return f"the price is {st['price']:g} right now" if st.get("price") is not None else \
            "I couldn't find a price on the page (the site may block automated checks)"
    if w["kind"] in ("rss", "email"):
        return f"{len(st.get('seen', []))} existing item(s) noted; I'll tell you about new ones"
    return "I've saved how the page looks now"


# ---------------------------------------------------------------- storage and the background loop

def _load():
    try:
        return json.loads(WATCHERS_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def _save(watchers):
    WATCHERS_FILE.write_text(json.dumps(watchers, indent=1, ensure_ascii=False), encoding="utf-8")


def run_due():
    """Check every watcher that's due. Returns the alerts sent."""
    from . import notify
    now = time.time()
    sent = []
    with _lock:
        watchers = _load()
        for w in watchers:
            if now - w.get("last_check", 0) < w["every"] * 60:
                continue
            w["last_check"] = now
            try:
                message = check(w)
                w["errors"] = 0
            except Exception as e:
                w["errors"] = w.get("errors", 0) + 1
                message = f"I can't check it any more ({type(e).__name__}). I'll keep trying." if w["errors"] == 5 else None
            if message:
                notify.alert("Watcher", f"{w['name']}: {message}")
                sent.append(f"{w['name']}: {message}")
        _save(watchers)
    return sent


def start():
    global _loop
    if _loop:
        return

    def loop():
        while True:
            try:
                run_due()
            except Exception:
                pass
            time.sleep(60)

    _loop = threading.Thread(target=loop, daemon=True)
    _loop.start()


# ---------------------------------------------------------------- tools

@tool("Watch something and alert the user (PC, phone, Telegram) when it changes, checked on a timer for free. Kinds: "
      "'page_text' (alert when `text` appears on a web page, or disappears with mode 'disappears'); 'page_change' "
      "(any real change to a page); 'price' (a page's price: alert when it drops, or reaches `below`; `text` = words "
      "just before the price if the page shows several); 'rss' (new items in a news feed, optionally only titles "
      "containing `text`); 'email' (new Gmail messages matching a Gmail search in `target`, e.g. "
      "'from:amazon subject:shipped'). Use for 'tell me when...' or 'let me know if...' requests.",
      {"kind": {"type": "string", "enum": list(DEFAULT_EVERY)},
       "target": S("The page or feed URL, or the Gmail search for kind 'email'"),
       "name": S("A short name for it, e.g. 'PS5 price'"),
       "text": S("page_text: the words to look for; price: words just before the price; rss: title filter"),
       "mode": {"type": "string", "enum": ["appears", "disappears"], "description": "page_text only"},
       "below": {"type": "number", "description": "price only: alert when the price is at or under this"},
       "every_minutes": I("How often to check (defaults: 60, or 10 for email)")},
      ["kind", "target", "name"])
def add_watcher(kind, target, name, text="", mode="appears", below=None, every_minutes=None):
    target, name = target.strip(), name.strip()
    if kind == "email":
        from . import google_tools
        if not google_tools.connected():
            return google_tools.NOT_CONNECTED
    elif not re.match(r"^https?://", target):
        return "The target must be a web address starting with http:// or https://."
    if kind == "page_text" and not text.strip():
        return "Say which words to look for."
    with _lock:
        watchers = _load()
    if len(watchers) >= MAX_WATCHERS:
        return f"There are already {MAX_WATCHERS} watchers. Remove one first."
    every = max(MIN_EVERY[kind], int(every_minutes or DEFAULT_EVERY[kind]))
    w = {"id": os.urandom(3).hex(), "kind": kind, "target": target, "name": name, "text": text.strip(), "mode": mode,
         "below": below, "every": every, "created": dt.datetime.now().isoformat(timespec="minutes"), "state": {}}
    try:
        check(w)  # first look: records how things are now
    except Exception as e:
        if type(e).__name__ == "NotConnected":
            return str(e)
        reason = {"ConnectionError": "couldn't reach it", "HTTPError": "the site refused", "Timeout": "it took too long",
                  "ParseError": "it isn't a news feed"}.get(type(e).__name__, type(e).__name__)
        return f"I couldn't read that ({reason}). The site may block automated checks, so I didn't add it."
    w["last_check"] = time.time()
    with _lock:
        _save(_load() + [w])
    return f"Watching \"{name}\" every {every} minutes (id {w['id']}). Right now {_describe_now(w)}."


@tool("List the things Jarvis is watching.")
def list_watchers():
    watchers = _load()
    if not watchers:
        return "Nothing is being watched."
    return "\n".join(f"[{w['id']}] {w['name']} ({w['kind']}, every {w['every']} min): {w['target']}" for w in watchers)


@tool("Stop watching something, by id or by part of its name.", {"match": S("Watcher id or part of its name")}, ["match"])
def remove_watcher(match):
    match = match.strip().lower()
    if not match:  # an empty match is "in" every name
        return "Say which watcher to remove. Nothing was removed."
    with _lock:
        watchers = _load()
        kept = [w for w in watchers if w["id"] != match and match not in w["name"].lower()]
        _save(kept)
    return f"Removed {len(watchers) - len(kept)} watcher(s)."
