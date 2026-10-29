"""The HUD: a web interface for Jarvis that works on this PC and on your phone (same Wi-Fi).

Every browser that connects shares the same Jarvis. Access needs the secret key in data/access_key.txt,
which is built into the link / QR code printed at startup, so nobody else on your network can control your PC.
"""
import asyncio
import base64
import concurrent.futures
import datetime as dt
import secrets
import socket
import uuid
from contextlib import asynccontextmanager

import psutil
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, feeds, google_tools, tools
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
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

clients: dict[str, WebSocket] = {}
pending_confirms: dict[str, concurrent.futures.Future] = {}
held_announcements: list[str] = []  # reminders that fired while no screen was connected
loop: asyncio.AbstractEventLoop | None = None
brain: Brain | None = None
busy = asyncio.Lock()


def access_key():
    if not KEY_FILE.exists():
        KEY_FILE.write_text(secrets.token_urlsafe(16))
    return KEY_FILE.read_text().strip()


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # no packets sent; just picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"


def tailscale_ip():
    """This PC's Tailscale address, if Tailscale is installed and connected (lets your phone reach Jarvis from anywhere)."""
    import shutil
    import subprocess
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
        return out.splitlines()[0] if out else None
    except (OSError, subprocess.SubprocessError):
        return None


def check_key(key):
    if key != access_key():
        raise HTTPException(403)


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
    await ws.send_json({"type": "hello", "id": client_id, "user": config.USER_NAME, "wake_words": config.WAKE_WORDS})
    while held_announcements:
        text = held_announcements.pop(0)
        await ws.send_json({"type": "announce", "text": text, "audio": await voice_for(text)})
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


