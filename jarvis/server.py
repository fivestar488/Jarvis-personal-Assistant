"""The HUD: Jarvis's Iron Man-style interface, for this PC and your phone.

Access needs the secret key in data/access_key.txt (built into the link and the phone QR code), so nobody else
on your network, and no other website on this PC, can control Jarvis.
"""
import asyncio
import base64
import concurrent.futures
import datetime as dt
import secrets
import uuid
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, feeds, google_tools, network, tools
from .brain import Brain
from .voice import synthesize

WEB_DIR = config.ROOT / "web"
KEY_FILE = config.DATA_DIR / "access_key.txt"
RESET_PHRASES = {"reset", "new conversation", "start over", "new session"}


@asynccontextmanager
async def lifespan(_app):
    global loop, brain
    loop = asyncio.get_running_loop()
    tools.ui = HudInterface()
    brain = Brain(mode="hud", on_status=lambda s: from_thread(broadcast({"type": "status", "text": s})))
    tools.start_reminders()
    watcher = asyncio.create_task(watch_network())
    yield
    watcher.cancel()


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

clients: dict[str, WebSocket] = {}
pending_confirms: dict[str, concurrent.futures.Future] = {}
held_announcements: list[str] = []  # reminders that fired while no screen was connected
listen_on_connect = False  # hotkey pressed before the HUD window was open
loop: asyncio.AbstractEventLoop | None = None
brain: Brain | None = None
busy = asyncio.Lock()


def access_key():
    if not KEY_FILE.exists():
        KEY_FILE.write_text(secrets.token_urlsafe(16))
    return KEY_FILE.read_text().strip()


def check_key(key):
    if key != access_key():
        raise HTTPException(403)


# ---------------------------------------------------------------- phone link

phone_link = None        # the current {url, host, network, tailscale}, kept up to date by watch_network()
on_network_change = None  # set by jarvis.py to reprint the QR code in the console


async def watch_network():
    """Every few seconds, check whether the phone link changed (new Wi-Fi, Tailscale on/off) and announce it."""
    global phone_link
    while True:
        link = await asyncio.to_thread(network.current_link, access_key())
        if link != phone_link:
            first = phone_link is None
            phone_link = link
            if not first:
                await broadcast({"type": "network", **phone_payload()})
            if on_network_change:
                on_network_change(link, first)
        await asyncio.sleep(config.NETWORK_CHECK_SECONDS)


def phone_payload():
    if not phone_link:
        return {"online": False}
    return {"online": True, "svg": network.qr_svg(phone_link["url"]), "network": phone_link["network"],
            "host": phone_link["host"], "tailscale": phone_link["tailscale"], "secure": phone_link["secure"]}


async def broadcast(event):
    for ws in list(clients.values()):
        try:
            await ws.send_json(event)
        except Exception:
            pass


def from_thread(coro):
    """Run a coroutine on the server loop from a worker thread (tools and the brain run in threads)."""
    return asyncio.run_coroutine_threadsafe(coro, loop)


async def voice_for(text):
    try:
        return base64.b64encode(await synthesize(text)).decode()
    except Exception:
        return None  # no internet for TTS; the HUD still shows the text


_thinking_audio = None


async def thinking_audio():
    """Jarvis says "Thinking..." as soon as a command arrives. Generated once, then reused."""
    global _thinking_audio
    if _thinking_audio is None:
        _thinking_audio = await voice_for(config.THINKING_PHRASE)
    return _thinking_audio


class HudInterface:
    """Lets tools ask permission (a pop-up on every connected screen) and announce reminders."""

    def confirm(self, question):
        cid = uuid.uuid4().hex
        future = concurrent.futures.Future()
        pending_confirms[cid] = future
        from_thread(broadcast({"type": "confirm", "id": cid, "question": question}))
        try:
            return future.result(timeout=120)
        except concurrent.futures.TimeoutError:
            return False
        finally:
            pending_confirms.pop(cid, None)
            from_thread(broadcast({"type": "confirm_done", "id": cid}))

    def announce(self, text):
        async def send():
            if not clients:
                held_announcements.append(text)  # delivered when a screen next connects
                return
            await broadcast({"type": "announce", "text": text, "audio": await voice_for(text)})
        from_thread(send())


def summon():
    """Global hotkey pressed: tell the HUD to start listening (or do it as soon as the window connects)."""
    global listen_on_connect
    if clients and loop:
        from_thread(broadcast({"type": "listen"}))
    else:
        listen_on_connect = True


async def handle_message(text, origin):
    async with busy:
        await broadcast({"type": "user", "text": text, "origin": origin})
        if text.lower().strip(" .!") in RESET_PHRASES:
            brain.reset()
            reply = "Fresh start. What can I do for you?"
        else:
            await broadcast({"type": "state", "state": "thinking", "origin": origin, "audio": await thinking_audio()})
            reply = await asyncio.to_thread(brain.respond, text)
        await broadcast({"type": "reply", "text": reply, "audio": await voice_for(reply), "origin": origin})


@app.get("/")
async def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # Served from the root so it covers the whole app (needed for "Install app" on phones).
    return FileResponse(WEB_DIR / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/api/weather")
async def weather(key: str):
    check_key(key)
    try:
        return await asyncio.to_thread(feeds.weather)
    except Exception as e:
        raise HTTPException(503, str(e))


@app.get("/api/news")
async def news(key: str):
    check_key(key)
    return {"items": await asyncio.to_thread(feeds.headlines)}


@app.get("/api/calendar")
async def calendar(key: str):
    """Today's and tomorrow's events for the HUD timeline."""
    check_key(key)
    if not google_tools.connected():
        return {"connected": False, "events": []}
    start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        events = await asyncio.to_thread(google_tools.list_events, start, start + dt.timedelta(days=2))
    except google_tools.NotConnected as e:
        return {"connected": False, "events": [], "error": str(e)}
    return {"connected": True, "events": events}


@app.get("/api/phone")
async def phone(key: str):
    """The current phone link as a QR code."""
    check_key(key)
    return phone_payload()


@app.get("/api/stats")
async def stats(key: str):
    check_key(key)
    battery = psutil.sensors_battery()
    disk = psutil.disk_usage("C:/")
    return {
        "cpu": psutil.cpu_percent(),
        "ram": psutil.virtual_memory().percent,
        "disk": disk.percent,
        "battery": round(battery.percent) if battery else None,
        "charging": battery.power_plugged if battery else None,
        "processes": len(psutil.pids()),
        "uptime": str(dt.datetime.now() - dt.datetime.fromtimestamp(psutil.boot_time())).split(".")[0],
    }


@app.websocket("/ws")
async def websocket(ws: WebSocket, key: str = ""):
    await ws.accept()
    if key != access_key():
        await ws.close(code=4003)
        return
    client_id = uuid.uuid4().hex
    clients[client_id] = ws
    await ws.send_json({"type": "hello", "id": client_id, "user": config.USER_NAME, "wake_words": config.WAKE_WORDS,
                        "hotkey": config.HOTKEY})
    while held_announcements:
        text = held_announcements.pop(0)
        await ws.send_json({"type": "announce", "text": text, "audio": await voice_for(text)})
    global listen_on_connect
    if listen_on_connect:
        listen_on_connect = False
        await ws.send_json({"type": "listen"})
    try:
        while True:
            event = await ws.receive_json()
            if event.get("type") == "message" and event.get("text", "").strip():
                asyncio.create_task(handle_message(event["text"].strip(), client_id))
            elif event.get("type") == "confirm_reply":
                future = pending_confirms.get(event.get("id"))
                if future and not future.done():
                    future.set_result(bool(event.get("answer")))
    except WebSocketDisconnect:
        pass
    finally:
        clients.pop(client_id, None)


