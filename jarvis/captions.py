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
        _queue.put(("quit", "", 0))
    return "Captions on." if on else "Captions off."
