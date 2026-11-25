"""Perimeter: Jarvis keeps an eye on who's trying to get in.

- Failed Windows sign-ins (wrong password or PIN): one or two is a caution; three or more within 10 minutes is a
  warning, and Jarvis snaps a webcam photo for your phone.
- New devices on your home Wi-Fi: for each network, Jarvis spends 2 days learning which devices are normal,
  then mentions ones it hasn't seen before. It only reads the PC's own list of nearby devices (the ARP
  table); it never scans the network.
"Perimeter report" sums it up. JARVIS_PERIMETER=off turns it off.
"""
import datetime as dt
import json
import re
import subprocess
import threading
import time

from . import config
from .tools import tool

DEVICES_FILE = config.DATA_DIR / "known_devices.json"
LEARN_DAYS = 2
_state = {"failures": [], "signin_ok": True, "device_alerts": [], "new_today": []}


def _run(cmd, timeout=20):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout


def failed_signins(since):
    """Times of failed sign-ins since a datetime (Security log, event 4625)."""
    script = ("try { Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625; StartTime=[datetime]'%s'} "
              "-ErrorAction Stop | ForEach-Object { $_.TimeCreated.ToString('s') } } "
              "catch { if ($_.Exception.Message -notmatch 'No events') { 'DENIED' } }") % since.strftime("%Y-%m-%dT%H:%M:%S")
    out = _run(["powershell", "-NoProfile", "-Command", script]).split()
    if "DENIED" in out:
        raise PermissionError("can't read the Windows security log")
    return [dt.datetime.fromisoformat(t) for t in out if t[:2] == "20"]


def wifi_name():
    m = re.search(r"^\s+SSID\s+:\s(.+)$", _run(["netsh", "wlan", "show", "interfaces"]), re.M)
    return m.group(1).strip() if m else None


def neighbours():
    """{mac: ip} of devices the PC has seen on the local network (not broadcast or multicast addresses)."""
    found = {}
    for ip, mac in re.findall(r"^\s+(\d+\.\d+\.\d+\.\d+)\s+([0-9a-f]{2}(?:-[0-9a-f]{2}){5})\s+dynamic", _run(["arp", "-a"]), re.M):
        first = int(mac[:2], 16)
        if mac != "ff-ff-ff-ff-ff-ff" and not first & 1:  # multicast/broadcast have the lowest bit set
            found[mac] = ip
    return found


def _load():
    try:
        return json.loads(DEVICES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def check_devices(now=None):
    """Remember devices per Wi-Fi network; returns the new ones worth mentioning [(network, mac, ip)]."""
    now = now or dt.datetime.now()
    ssid = wifi_name()
    if not ssid:
        return []
    data = _load()
    net = data.setdefault(ssid, {"first_seen": now.isoformat(timespec="minutes"), "devices": {}})
    learning = now - dt.datetime.fromisoformat(net["first_seen"]) < dt.timedelta(days=LEARN_DAYS)
    new = []
    for mac, ip in neighbours().items():
        if mac not in net["devices"]:
            net["devices"][mac] = {"ip": ip, "first": now.isoformat(timespec="minutes")}
            if not learning:
                new.append((ssid, mac, ip))
        else:
            net["devices"][mac]["ip"] = ip
    DEVICES_FILE.write_text(json.dumps(data, indent=1), encoding="utf-8")
    return new


def _snapshot():
    """A webcam photo for a sign-in alert (like security mode's)."""
    try:
        import cv2
        from . import security
        cam = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
        frame = None
        for _ in range(8):
            ok, frame = cam.read()
        cam.release()
        if frame is None:
            return None
        security.SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = security.SNAPSHOT_DIR / f"signin_{dt.datetime.now():%Y%m%d_%H%M%S}.jpg"
        cv2.imwrite(str(path), frame)
        return path
    except Exception:
        return None


def _tick(last_check):
    from . import notify
    now = dt.datetime.now()
    if _state["signin_ok"]:
        try:
            fails = failed_signins(last_check)
        except PermissionError:
            _state["signin_ok"] = False
            fails = []
        if fails:
            _state["failures"] = [t for t in _state["failures"] if now - t < dt.timedelta(minutes=10)] + fails
            n = len(_state["failures"])
            if n >= 3:
                notify.alert("Perimeter", f"Sir, {n} failed sign-in attempts on your PC in the last 10 minutes. "
                             "I've taken a photo of whoever's at the keyboard.", image_path=_snapshot(), level="warning")
                _state["failures"] = []
            else:
                notify.alert("Perimeter", "Someone just entered the wrong password on your PC, sir.", level="caution")
    if now.minute % 5 == 0 or not _state.get("devices_checked"):
        _state["devices_checked"] = True
        _state["device_alerts"] = [t for t in _state["device_alerts"] if now - t < dt.timedelta(hours=1)]
        for ssid, mac, ip in check_devices(now):
            _state["new_today"].append((now, ip))
            if len(_state["device_alerts"]) < 3:  # at most 3 an hour
                _state["device_alerts"].append(now)
                notify.alert("Perimeter", f"A new device has joined {ssid}, sir, at address {ip}.", level="note", phone=True)


def report():
    now = dt.datetime.now()
    lines = []
    if _state["signin_ok"]:
        try:
            today = failed_signins(now.replace(hour=0, minute=0, second=0, microsecond=0))
            lines.append("No failed sign-ins today." if not today else
                         f"{len(today)} failed sign-in attempt{'s' if len(today) != 1 else ''} today, the last at {today[-1]:%H:%M}.")
        except PermissionError:
            lines.append("I can't read the sign-in log on this account.")
    ssid = wifi_name()
    if ssid:
        net = _load().get(ssid)
        if net:
            learning = now - dt.datetime.fromisoformat(net["first_seen"]) < dt.timedelta(days=LEARN_DAYS)
            new = [ip for t, ip in _state["new_today"] if t.date() == now.date()]
            lines.append(f"{len(net['devices'])} known devices on {ssid}" + (", and I'm still learning which ones are normal." if learning
                         else f"; {len(new)} new today." if new else "; nothing new today."))
        else:
            lines.append(f"I haven't mapped {ssid} yet.")
    return "Perimeter report, sir. " + " ".join(lines)


@tool("Perimeter report: failed sign-in attempts on the PC today and new devices seen on the home Wi-Fi.")
def perimeter_report():
    return report()


def start():
    if not config.PERIMETER:
        return

    def loop():
        last = dt.datetime.now()
        while True:
            time.sleep(60)
            check_from, last = last, dt.datetime.now()
            try:
                _tick(check_from)
            except Exception:
                pass
    threading.Thread(target=loop, daemon=True, name="perimeter").start()
