"""A global keyboard shortcut (works in any app) using the Windows hotkey API, plus bringing the HUD window to the front."""
import ctypes
import ctypes.wintypes as wt
import threading

user32 = ctypes.windll.user32

MODIFIERS = {"ctrl": 0x2, "alt": 0x1, "shift": 0x4, "win": 0x8}
MOD_NOREPEAT = 0x4000  # holding the keys down fires once, not repeatedly
KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, **{f"f{n}": 0x6F + n for n in range(1, 13)}}
WM_HOTKEY = 0x0312
SW_RESTORE = 9


def _parse(combo):
    *mods, key = [p.strip().lower() for p in combo.split("+")]
    vk = KEYS.get(key) or (ord(key.upper()) if len(key) == 1 else None)
    if vk is None or any(m not in MODIFIERS for m in mods):
        raise ValueError(f"Can't understand the hotkey '{combo}'. Use something like ctrl+alt+j.")
    return sum(MODIFIERS[m] for m in mods) | MOD_NOREPEAT, vk


def start(combo, on_press, on_error):
    """Listen for the hotkey on a background thread. Calls on_error(message) if it can't be registered."""
    def loop():
        try:
            mods, vk = _parse(combo)
        except ValueError as e:
            return on_error(str(e))
        if not user32.RegisterHotKey(None, 1, mods, vk):
            return on_error(f"The hotkey {combo} is already used by another program. Set JARVIS_HOTKEY in .env to change it.")
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                on_press()
    threading.Thread(target=loop, daemon=True).start()


def focus_window(title_part):
    """Bring the first visible window whose title contains title_part to the front. Returns False if none is open."""
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def check(hwnd, _):
        length = user32.GetWindowTextLengthW(hwnd)
        if length and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title, length + 1)
            if title_part in title.value:
                found.append(hwnd)
                return False
        return True

    user32.EnumWindows(check, 0)
    if not found:
        return False
    if user32.IsIconic(found[0]):
        user32.ShowWindow(found[0], SW_RESTORE)
    user32.SetForegroundWindow(found[0])
    return True
