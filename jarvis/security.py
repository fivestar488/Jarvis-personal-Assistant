"""Security mode: watches the webcam for movement and sends you a photo when something moves."""
import datetime as dt
import threading
import time
from pathlib import Path

from . import config
from .tools import I, tool

SNAPSHOT_DIR = Path.home() / "Pictures" / "Jarvis" / "security"
SENSITIVITY = 0.02     # fraction of the picture that must change to count as movement
ALERT_COOLDOWN = 30    # seconds between alerts, so one person walking past isn't 20 notifications

_thread = None
_stop = threading.Event()
_until = None
latest_frame = None    # the newest webcam frame, so look_through_camera can share the camera while this runs


def running():
    return bool(_thread and _thread.is_alive())


def _watch():
    import cv2
    from . import notify
    global latest_frame
    cam = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cam.isOpened():
        notify.alert("Security mode", "Security mode couldn't start: the webcam is in use or blocked.")
        return
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    previous, last_alert = None, 0.0
    try:
        for _ in range(15):  # let the camera's brightness settle before comparing frames
            cam.read()
        while not _stop.is_set() and not (_until and time.time() > _until):
            ok, frame = cam.read()
            if not ok:
                time.sleep(1)
                continue
            latest_frame = frame
            gray = cv2.GaussianBlur(cv2.cvtColor(cv2.resize(frame, (320, 240)), cv2.COLOR_BGR2GRAY), (21, 21), 0)
            if previous is not None:
                changed = cv2.threshold(cv2.absdiff(previous, gray), 25, 255, cv2.THRESH_BINARY)[1]
                if cv2.countNonZero(changed) / changed.size > SENSITIVITY and time.time() - last_alert > ALERT_COOLDOWN:
                    last_alert = time.time()
                    photo = SNAPSHOT_DIR / f"motion_{dt.datetime.now():%Y%m%d_%H%M%S}.jpg"
                    cv2.imwrite(str(photo), frame)
                    notify.alert("Security alert", f"Movement detected in front of your PC at {dt.datetime.now():%H:%M}.",
                                 image_path=photo)
            previous = gray
            time.sleep(0.3)
    finally:
        cam.release()
        latest_frame = None


@tool("Start security mode: watch the webcam for movement and alert the user (with a photo on their phone) "
      "when something moves. Use when he says 'watch the room', 'keep an eye on things', 'guard mode', etc.",
      {"minutes": I("Optional: stop automatically after this many minutes")})
def start_security_mode(minutes=None):
    global _thread, _until
    if running():
        return "Security mode is already on."
    _stop.clear()
    _until = time.time() + minutes * 60 if minutes else None
    _thread = threading.Thread(target=_watch, daemon=True)
    _thread.start()
    return ("Security mode on. Watching the webcam; you'll get an alert with a photo if anything moves"
            + (f", for the next {minutes} minutes." if minutes else ", until you tell me to stop."))


@tool("Stop security mode (stop watching the webcam).")
def stop_security_mode():
    if not running():
        return "Security mode isn't on."
    _stop.set()
    return "Security mode off."


@tool("Is security mode on, and how many movement photos were taken today?")
def security_status():
    today = list(SNAPSHOT_DIR.glob(f"motion_{dt.datetime.now():%Y%m%d}_*.jpg")) if SNAPSHOT_DIR.exists() else []
    return f"Security mode is {'on' if running() else 'off'}. {len(today)} movement photo(s) today, saved in {SNAPSHOT_DIR}."
