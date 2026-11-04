"""Spotify control.

Without setup, Jarvis can tell what's playing (from the Spotify window) and pause/skip with media keys.
With your Spotify connected (see README "Connect Spotify"), he can play songs, playlists and your liked songs,
like the current song, and add it to playlists. Starting playback on demand needs Spotify Premium.
"""
import os
import time

from . import config
from .tools import S, tool

REDIRECT_URI = "http://127.0.0.1:8888/callback"
SCOPES = ("user-read-playback-state user-modify-playback-state user-read-currently-playing "
          "user-library-read user-library-modify playlist-read-private playlist-modify-private playlist-modify-public")
TOKEN_FILE = config.DATA_DIR / "spotify_token.json"
NOT_CONNECTED = ("Spotify isn't connected, so I can only see what's playing and pause or skip. To connect it, "
                 "follow 'Connect Spotify' in the README, then run: jarvis.bat --connect-spotify")


def _auth():
    from spotipy.cache_handler import CacheFileHandler
    from spotipy.oauth2 import SpotifyPKCE
    if not config.SPOTIFY_CLIENT_ID:
        raise RuntimeError("JARVIS_SPOTIFY_CLIENT_ID is missing from .env")
    return SpotifyPKCE(client_id=config.SPOTIFY_CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPES,
                       cache_handler=CacheFileHandler(cache_path=str(TOKEN_FILE)), open_browser=True)


def connect():
    """Interactive sign-in in the browser. Run once via `jarvis.py --connect-spotify`."""
    _auth().get_access_token(check_cache=False)


def connected():
    return bool(config.SPOTIFY_CLIENT_ID) and TOKEN_FILE.exists()


def _sp():
    import spotipy
    return spotipy.Spotify(auth_manager=_auth())


def _window_title():
    """The Spotify app's window title: 'Artist - Song' while playing, 'Spotify ...' when paused."""
    import ctypes
    import ctypes.wintypes as wt

    import psutil
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower() == "spotify.exe"}
    if not pids:
        return None
    user32, titles = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def check(hwnd, _):
        pid = wt.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        length = user32.GetWindowTextLengthW(hwnd)
        if pid.value in pids and length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            titles.append(buf.value)
        return True

    user32.EnumWindows(check, 0)
    return next((t for t in titles if " - " in t), None) or next((t for t in titles if t.startswith("Spotify")), None)


def _active_device(sp):
    """Make sure some Spotify device is ready to play, opening the desktop app if needed."""
    devices = sp.devices().get("devices", [])
    active = next((d for d in devices if d["is_active"]), None)
    if active:
        return active["id"]
    if not devices:
        os.startfile("spotify:")
        for _ in range(10):
            time.sleep(1.5)
            devices = sp.devices().get("devices", [])
            if devices:
                break
    if not devices:
        return None
    pc = next((d for d in devices if d["type"] == "Computer"), devices[0])
    return pc["id"]


def _premium_needed(e):
    return getattr(e, "http_status", None) == 403 or "PREMIUM" in str(e).upper()


@tool("What's playing on Spotify right now (song, artist, and whether it's paused).")
def spotify_now_playing():
    if connected():
        try:
            p = _sp().current_playback()
            if p and p.get("item"):
                item = p["item"]
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                pos, dur = p.get("progress_ms", 0) // 1000, item.get("duration_ms", 0) // 1000
                state = "playing" if p.get("is_playing") else "paused"
                return f"{item['name']} by {artists} ({state}, {pos // 60}:{pos % 60:02d} of {dur // 60}:{dur % 60:02d})."
            return "Nothing is playing on Spotify."
        except Exception:
            pass  # fall back to the window title
    title = _window_title()
    if title is None:
        return "Spotify isn't open."
    if " - " not in title:
        return "Spotify is open but nothing is playing (or it's paused)."
    artist, _, song = title.partition(" - ")
    return f"{song} by {artist}."


@tool("Play music on Spotify: a song, artist, album, one of the user's playlists, or their liked songs.",
      {"query": S("What to play, e.g. 'Bohemian Rhapsody', 'Arctic Monkeys', 'my gym playlist'. Ignored for liked songs."),
       "kind": {"type": "string", "enum": ["track", "artist", "album", "playlist", "liked"],
                "description": "What sort of thing to play. 'liked' = the user's Liked Songs."}},
      ["kind"])
def spotify_play(kind, query=""):
    if not connected():
        if query:
            os.startfile(f"spotify:search:{query}")
            return "Spotify isn't connected, so I've opened a Spotify search for it. " + NOT_CONNECTED
        return NOT_CONNECTED
    from spotipy import SpotifyException
    sp = _sp()
    uris, context, label = None, None, query
    if kind == "liked":
        tracks = [t["track"]["uri"] for t in sp.current_user_saved_tracks(limit=50)["items"] if t.get("track")]
        if not tracks:
            return "You don't have any liked songs yet."
        uris, label = tracks, "your liked songs"
    elif kind == "playlist":
        mine = [p for p in sp.current_user_playlists(limit=50)["items"] if p and query.lower().replace("my ", "").replace(" playlist", "") in p["name"].lower()]
        found = mine or [p for p in sp.search(q=query, type="playlist", limit=5)["playlists"]["items"] if p]
        if not found:
            return f"Couldn't find a playlist called '{query}'."
        context, label = found[0]["uri"], found[0]["name"]
    else:
        items = sp.search(q=query, type=kind, limit=1)[f"{kind}s"]["items"]
        if not items:
            return f"Couldn't find {kind} '{query}' on Spotify."
        item = items[0]
        label = item["name"] + (f" by {item['artists'][0]['name']}" if kind in ("track", "album") else "")
        if kind == "track":
            uris = [item["uri"]]
        else:
            context = item["uri"]
    try:
        device = _active_device(sp)
        sp.start_playback(device_id=device, uris=uris, context_uri=context)
        if kind == "liked":
            sp.shuffle(True, device_id=device)
        return f"Playing {label} on Spotify."
    except SpotifyException as e:
        if _premium_needed(e):
            os.startfile(context or uris[0])
            return f"I've opened {label} in Spotify. Starting playback automatically needs Spotify Premium, so press play."
        return f"Spotify said: {e.msg}"


@tool("Control Spotify playback: pause, resume, next, previous, shuffle on/off, or set Spotify's volume.",
      {"action": {"type": "string", "enum": ["pause", "resume", "next", "previous", "shuffle_on", "shuffle_off", "volume"]},
       "volume_percent": {"type": "integer", "description": "For action=volume: 0-100"}},
      ["action"])
def spotify_control(action, volume_percent=None):
    keys = {"pause": "playpause", "resume": "playpause", "next": "nexttrack", "previous": "prevtrack"}
    if connected():
        from spotipy import SpotifyException
        sp = _sp()
        try:
            {"pause": sp.pause_playback, "resume": sp.start_playback, "next": sp.next_track,
             "previous": sp.previous_track, "shuffle_on": lambda: sp.shuffle(True), "shuffle_off": lambda: sp.shuffle(False),
             "volume": lambda: sp.volume(max(0, min(100, volume_percent or 50)))}[action]()
            return f"Done: {action.replace('_', ' ')}."
        except SpotifyException as e:
            if not (_premium_needed(e) and action in keys):
                return f"Spotify said: {e.msg}"
    if action in keys:  # works without Premium or a connection: the keyboard's media keys
        import pyautogui
        pyautogui.press(keys[action])
        return f"Done: {action}."
    return NOT_CONNECTED


@tool("Like (save) the song that's playing on Spotify right now.")
def spotify_like_current():
    if not connected():
        return NOT_CONNECTED
    sp = _sp()
    p = sp.current_playback()
    if not p or not p.get("item"):
        return "Nothing is playing."
    sp.current_user_saved_tracks_add([p["item"]["id"]])
    return f"Added {p['item']['name']} to your Liked Songs."


@tool("Add the song that's playing on Spotify to one of the user's playlists.",
      {"playlist": S("Name (or part of the name) of the user's playlist")}, ["playlist"])
def spotify_add_to_playlist(playlist):
    if not playlist.strip():  # an empty name would match whichever playlist comes first
        return "Say which playlist to add it to."
    if not connected():
        return NOT_CONNECTED
    sp = _sp()
    p = sp.current_playback()
    if not p or not p.get("item"):
        return "Nothing is playing."
    matches =[pl for pl in sp.current_user_playlists(limit=50)["items"] if pl and playlist.lower() in pl["name"].lower()]
    if not matches:
        return f"You don't have a playlist matching '{playlist}'."
    sp.playlist_add_items(matches[0]["id"], [p["item"]["uri"]])
    return f"Added {p['item']['name']} to {matches[0]['name']}."
