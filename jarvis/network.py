"""Phone access: works out the link your phone should use right now, and makes QR codes for it.

The link changes whenever the PC changes network (office Wi-Fi, home Wi-Fi...), so the server re-checks it
every few seconds and hands out a fresh QR code when it changes. If Tailscale is running, its address is
used instead: it stays the same everywhere and works even when a router blocks devices from seeing each other.
"""
import io
import json
import shutil
import socket
import subprocess

from . import config

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # don't flash console windows every few seconds


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))  # sends nothing; just picks the network card that reaches the internet
            return s.getsockname()[0]
    except OSError:
        return None


def wifi_name():
    try:
        out = subprocess.run(["netsh", "wlan", "show", "interfaces"], capture_output=True, text=True,
                             timeout=5, creationflags=NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in out.splitlines():
        name, _, value = line.partition(":")
        if name.strip() == "SSID":
            return value.strip() or None
    return None


def _tailscale(*args):
    exe = shutil.which("tailscale") or r"C:\Program Files\Tailscale\tailscale.exe"
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return None
    return r


_serving = False


def tailscale():
    """{ip, https_host} when Tailscale is connected, else None. https_host is set when the secure address works.

    The secure address (https://<pc>.<tailnet>.ts.net) needs "HTTPS Certificates" enabled in Tailscale's
    DNS settings. It's what lets phones install JARVIS as an app and use the microphone.
    """
    global _serving
    r = _tailscale("status", "--json")
    if not r or r.returncode:
        return None
    try:
        status = json.loads(r.stdout)
    except ValueError:
        return None
    me = status.get("Self") or {}
    ip = next((a for a in me.get("TailscaleIPs") or [] if a.startswith("100.")), None)
    if status.get("BackendState") != "Running" or not ip:
        return None
    host = (me.get("DNSName") or "").rstrip(".")
    https_host = None
    if host and status.get("CertDomains"):
        if not _serving:
            # Tailscale forwards https://<host> to Jarvis on this PC, with a real certificate. Lasts until turned off.
            done = _tailscale("serve", "--bg", "--https=443", f"http://127.0.0.1:{config.PORT}")
            _serving = bool(done and done.returncode == 0)
        https_host = host if _serving else None
    return {"ip": ip, "https_host": https_host}


def current_link(key):
    """Where your phone should go right now: {url, host, network, tailscale, secure}, or None when offline."""
    ts = tailscale()
    if ts and ts["https_host"]:
        url, host = f"https://{ts['https_host']}/?key={key}", ts["https_host"]
    elif ts:
        url, host = f"http://{ts['ip']}:{config.PORT}/?key={key}", ts["ip"]
    elif lan_ip():
        host = lan_ip()
        url = f"http://{host}:{config.PORT}/?key={key}"
    else:
        return None
    return {
        "url": url,
        "host": host,
        "network": "Tailscale" if ts else (wifi_name() or "Wired network"),
        "tailscale": bool(ts),
        "secure": url.startswith("https"),
    }


def qr_svg(url):
    import qrcode
    import qrcode.image.svg
    out = io.BytesIO()
    qrcode.make(url, image_factory=qrcode.image.svg.SvgPathFillImage, border=2).save(out)
    return out.getvalue().decode()


def print_qr(url):
    import qrcode
    qr = qrcode.QRCode(border=1)
    qr.add_data(url)
    qr.print_ascii(invert=True)
