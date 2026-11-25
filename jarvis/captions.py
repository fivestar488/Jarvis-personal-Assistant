"""Live captions: what Jarvis is saying (and doing) in a strip at the bottom of the screen, on top of every app, so
you can follow him while the HUD is hidden. Clicks go straight through it. "Captions on" / "captions off", or
JARVIS_CAPTIONS=on in .env to start with them on."""
import ctypes
import queue
import threading

from . import config

STATE_FILE = config.DATA_DIR / "captions-on"
_queue = queue.Queue()
_thread = None
enabled = config.CAPTIONS or STATE_FILE.exists()


def _make_click_through(root):
    """Windows: let clicks pass through, keep it out of the taskbar and never take the keyboard focus."""
    GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = -20, 0x80000, 0x20, 0x80, 0x08000000
    try:
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                            style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
    except Exception:
        pass


def _run():
    import tkinter as tk
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    key = "#010203"  # this colour is see-through
    root.configure(bg=key)
    root.attributes("-transparentcolor", key)
    width = min(1100, root.winfo_screenwidth() - 80)
    status = tk.Label(root, text="", fg="#ffb347", bg=key, font=("Segoe UI", 11, "bold"))
    line = tk.Label(root, text="", fg="#e9f7ff", bg="#0b1622", font=("Segoe UI", 18), wraplength=width - 40,
                    justify="center", padx=18, pady=8)
    status.pack()
    line.pack()
    root.update_idletasks()
    _make_click_through(root)
    hide_at = {"line": None, "status": None}
    # The status strip: a slim always-on-top bar in the top-right corner
    strip = tk.Toplevel(root)
    strip.overrideredirect(True)
    strip.attributes("-topmost", True)
    strip.configure(bg=key)
    strip.attributes("-transparentcolor", key)
    strip_label = tk.Label(strip, text="", fg="#cdf2ff", bg="#0b1622", font=("Segoe UI", 10, "bold"), padx=10, pady=3)
    strip_label.pack()
    strip.withdraw()
    strip.update_idletasks()
    _make_click_through(strip)

    def show_strip(text, color):
        if not text:
            strip.withdraw()
            return
        strip_label.config(text=text, fg=color)
        strip.update_idletasks()
        w, h = strip_label.winfo_reqwidth(), strip_label.winfo_reqheight()
        strip.geometry(f"{w}x{h}+{root.winfo_screenwidth() - w - 14}+10")
        strip.deiconify()

    def place():
        root.update_idletasks()
        w, h = max(line.winfo_reqwidth(), status.winfo_reqwidth()), line.winfo_reqheight() + status.winfo_reqheight()
        x = (root.winfo_screenwidth() - w) // 2
        y = root.winfo_screenheight() - h - 70  # above the taskbar
        root.geometry(f"{w}x{h}+{x}+{y}")

    def tick():
        try:
            while True:
                kind, text, seconds = _queue.get_nowait()
                if kind == "quit":
                    root.destroy()
                    return
                if kind == "strip":  # (text, colour) for the status strip
                    show_strip(*text)
                    continue
                target = line if kind == "line" else status
                target.config(text=text)
                if hide_at[kind]:
                    root.after_cancel(hide_at[kind])
                hide_at[kind] = root.after(int(seconds * 1000), lambda t=target: (t.config(text=""), refresh())) if text else None
                refresh()
        except queue.Empty:
            pass
        root.after(100, tick)

    def refresh():
        if line.cget("text") or status.cget("text"):
            line.configure(bg="#0b1622" if line.cget("text") else key)
            place()
            root.deiconify()
        else:
            root.withdraw()

    root.withdraw()
    root.after(100, tick)
    root.mainloop()


def _ensure():
    global _thread
    if not (_thread and _thread.is_alive()):
        _thread = threading.Thread(target=_run, daemon=True, name="captions")
        _thread.start()


def say(text):
    """A caption for what Jarvis says. Stays up long enough to read."""
    if not enabled or not text:
        return
    _ensure()
    text = " ".join(str(text).split())
    if len(text) > 260:
        text = text[:257] + "..."
    _queue.put(("line", text, 2.5 + len(text.split()) * 0.42))


def status(text):
    """A smaller line above it for what he's doing ('Checking your calendar...')."""
    if not enabled or not text:
        return
    _ensure()
    _queue.put(("status", str(text)[:90], 4))


def set_enabled(on):
    global enabled
    enabled = on
    try:
        STATE_FILE.touch() if on else STATE_FILE.unlink(missing_ok=True)
    except OSError:
        pass
    if on:
        say("Captions on.")
    elif _thread and _thread.is_alive():
        _queue.put(("line", "", 0)) if strip_on() else _queue.put(("quit", "", 0))
    return "Captions on." if on else "Captions off."


# ---------- the status strip ----------

STRIP_FILE = config.DATA_DIR / "status-strip-on"
COLORS = {"nominal": "#cdf2ff", "note": "#cdf2ff", "caution": "#ffb347", "warning": "#ff8a3d", "critical": "#ff4b3a"}
_strip_thread = None


def strip_on():
    return config.STATUS_STRIP or STRIP_FILE.exists()


def strip_text():
    """'⚡ 76% · ONLINE · $0.02 · NEXT 18:00 GYM', and the colour for the worst status."""
    import psutil
    from . import focus, spend, vitals
    parts, worst = [], "nominal"
    b = psutil.sensors_battery()
    if b:
        level = "nominal" if b.power_plugged or b.percent > 25 else "caution" if b.percent > 15 else "warning" if b.percent > 7 else "critical"
        worst = max(worst, level, key=lambda l: vitals.RANK[l])
        parts.append(f"{'⚡' if b.power_plugged else '▮'} {round(b.percent)}%")
    online = vitals._online()
    parts.append("ONLINE" if online else "OFFLINE")
    if not online:
        worst = max(worst, "caution", key=lambda l: vitals.RANK[l])
    parts.append(f"${spend.today():.2f}")
    if focus.quiet():
        parts.append("DND")
    nxt = _next_event()
    if nxt:
        parts.append(nxt)
    return " · ".join(parts), COLORS[worst]


_event_cache = {"at": 0.0, "text": ""}


def _next_event():
    import datetime as dt
    import time
    if time.time() - _event_cache["at"] < 600:
        return _event_cache["text"]
    _event_cache["at"] = time.time()
    text = ""
    try:
        from . import google_tools
        if google_tools.connected():
            now = dt.datetime.now()
            for e in google_tools.list_events(now, now + dt.timedelta(hours=18)):
                start = dt.datetime.fromisoformat(e["start"]).replace(tzinfo=None) if not e["all_day"] else None
                if start and start > now:
                    text = f"NEXT {start:%H:%M} {e['title'].strip()[:22].upper()}"
                    break
    except Exception:
        pass
    _event_cache["text"] = text
    return text


def start_strip():
    global _strip_thread
    if _strip_thread and _strip_thread.is_alive():
        return

    def loop():
        import time
        while strip_on():
            try:
                _ensure()
                _queue.put(("strip", strip_text(), 0))
            except Exception:
                pass
            time.sleep(30)
        _queue.put(("strip", ("", ""), 0))
    _strip_thread = threading.Thread(target=loop, daemon=True, name="status-strip")
    _strip_thread.start()


def set_strip(on):
    STRIP_FILE.touch() if on else STRIP_FILE.unlink(missing_ok=True)
    if on:
        start_strip()
    else:
        _queue.put(("strip", ("", ""), 0))
    return "Status strip on, sir: top right of your screen." if on else "Status strip off."
