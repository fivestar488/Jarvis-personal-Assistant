"""Setup doctor: checks everything Jarvis needs and says, in plain English, how to fix anything that's wrong.

Run it with jarvis-doctor.bat (or "jarvis.bat --doctor"), or ask Jarvis "check my setup". Made for people who aren't
developers: no error codes, just what's wrong and what to do. It changes nothing on your PC.
"""
import importlib
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OK, WARN, FAIL = "ok", "warn", "fail"  # warn = optional or partly working; fail = Jarvis won't work properly
PACKAGES = {  # import name -> what it's for
    "anthropic": "the Claude brain", "dotenv": "settings", "fastapi": "the HUD", "uvicorn": "the HUD",
    "edge_tts": "Jarvis's voice", "pygame": "playing sound", "speech_recognition": "the microphone",
    "pyaudio": "the microphone", "faster_whisper": "speech recognition", "psutil": "PC status",
    "pyautogui": "keyboard and volume control", "cv2": "the webcam", "googleapiclient": "Gmail and Calendar",
    "spotipy": "Spotify", "pywebpush": "phone notifications", "pypdf": "reading PDFs", "numpy": "audio",
}


def _check_python():
    v = sys.version_info
    if (3, 10) <= v[:2] <= (3, 13):
        return OK, "Python", f"{v.major}.{v.minor}", ""
    return FAIL, "Python", f"{v.major}.{v.minor} isn't supported", "Install Python 3.12, then run setup.bat again."


def _check_packages():
    missing = []
    for name, use in PACKAGES.items():
        try:
            importlib.import_module(name)
        except Exception:
            missing.append(f"{name} ({use})")
    if not missing:
        return OK, "Components", f"all {len(PACKAGES)} installed", ""
    return FAIL, "Components", "missing: " + ", ".join(missing), "Run setup.bat again: it installs anything missing."


def _check_env():
    if (ROOT / ".env").exists():
        return OK, "Settings file", ".env found", ""
    return FAIL, "Settings file", "there's no .env file", "Run setup.bat: it creates one and asks for your API key."


def _check_internet():
    for host in ("api.anthropic.com", "www.google.com"):
        try:
            socket.create_connection((host, 443), timeout=5).close()
            return OK, "Internet", "connected", ""
        except OSError:
            continue
    return FAIL, "Internet", "can't reach the internet", "Check your Wi-Fi. Without internet only the free offline mode works."


def _check_claude():
    from . import config
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if config.BRAIN == "local":
        return OK, "Claude API", "not needed (free offline mode is on)", ""
    if not key:
        return FAIL, "Claude API", "no API key", ("Get a key at https://console.anthropic.com/settings/keys and paste it "
                                                  "after ANTHROPIC_API_KEY= in the .env file.")
    import anthropic
    client = anthropic.Anthropic(max_retries=0, timeout=20)
    try:  # the smallest possible request (one word from the cheapest model, a tiny fraction of a cent)
        client.messages.create(model=config.HELPER_MODEL, max_tokens=1, messages=[{"role": "user", "content": "Hi"}])
        return OK, "Claude API", "key works and has credit", ""
    except anthropic.AuthenticationError:
        return FAIL, "Claude API", "the API key was refused", ("Make a new key at https://console.anthropic.com/settings/keys "
                                                               "and replace the old one in .env.")
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower():
            meanwhile = ("Until then Jarvis uses the free offline mode." if config.BRAIN == "auto" else
                         "Or set JARVIS_BRAIN=auto to use the free offline mode meanwhile.")
            return FAIL, "Claude API", "the key works but there's no credit", (
                "Add credit at https://console.anthropic.com/settings/billing ($5 is enough to start; ask Jarvis "
                f"'how much credit do I need'). {meanwhile}")
        return WARN, "Claude API", f"the test request failed: {str(e)[:120]}", "Check the model names in .env."
    except anthropic.APIConnectionError:
        return FAIL, "Claude API", "couldn't reach Anthropic", "Check your internet connection or firewall."
    except anthropic.APIError as e:
        return WARN, "Claude API", f"unexpected answer: {str(e)[:120]}", "Try again in a minute."


def _check_voice():
    try:
        import asyncio
        from .voice import synthesize
        audio = asyncio.run(synthesize("Test", tone=None))
        if audio:
            return OK, "Voice", "Jarvis's voice works", ""
    except Exception:
        pass
    return WARN, "Voice", "couldn't reach Microsoft's voice service", (
        "Check the internet. Until then Jarvis uses the robotic Windows voice.")


def _check_speakers():
    try:
        import pygame
        if not pygame.mixer.get_init():  # (inside Jarvis it may already be playing sound)
            pygame.mixer.init()
            pygame.mixer.quit()
        return OK, "Speakers", "sound output found", ""
    except Exception:
        return FAIL, "Speakers", "no sound output", "Plug in speakers or headphones and check the volume isn't muted."


def _privacy_denied(device):
    """Has Windows' privacy setting blocked apps from the microphone / camera?"""
    try:
        import winreg
        path = rf"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\{device}"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as k:
            return winreg.QueryValueEx(k, "Value")[0] == "Deny"
    except OSError:
        return False


def _check_microphone():
    if _privacy_denied("microphone"):
        return FAIL, "Microphone", "Windows is blocking apps from the microphone", (
            "Run fix-mic.bat, or open Settings > Privacy & security > Microphone and turn on microphone access.")
    try:
        import pyaudio
        pa = pyaudio.PyAudio()
        inputs = [pa.get_device_info_by_index(i)["name"] for i in range(pa.get_device_count())
                  if pa.get_device_info_by_index(i).get("maxInputChannels", 0) > 0]
        pa.terminate()
    except Exception:
        inputs = []
    if inputs:
        return OK, "Microphone", f"{len(inputs)} input{'s' if len(inputs) != 1 else ''} found", ""
    return FAIL, "Microphone", "no microphone found", "Plug in a microphone or headset, then run this again."


def _check_camera():
    from . import config
    if _privacy_denied("webcam"):
        return WARN, "Webcam", "Windows is blocking apps from the camera", (
            "Settings > Privacy & security > Camera: turn on camera access (needed for scans, gestures, security mode).")
    try:
        import cv2
        cam = cv2.VideoCapture(config.CAMERA_INDEX, cv2.CAP_DSHOW)
        ok = cam.isOpened() and cam.read()[0]
        cam.release()
    except Exception:
        ok = False
    if ok:
        return OK, "Webcam", "working", ""
    return WARN, "Webcam", "couldn't open the camera (optional)", (
        "Only needed for scans, hand gestures and security mode. Close other apps using it, or check "
        "JARVIS_CAMERA_INDEX in .env.")


def _check_google():
    from . import config
    if not (config.DATA_DIR / "google_credentials.json").exists():
        return WARN, "Gmail & Calendar", "not set up (optional)", "See 'Connect Gmail and Google Calendar' in the README."
    if not (config.DATA_DIR / "google_token.json").exists():
        return WARN, "Gmail & Calendar", "not signed in", "Run: jarvis.bat --connect-google"
    from google.auth.exceptions import RefreshError
    from . import google_tools
    try:
        google_tools._service("gmail", "v1").users().getProfile(userId="me").execute()
        return OK, "Gmail & Calendar", "connected", ""
    except (RefreshError, google_tools.NotConnected):
        return FAIL, "Gmail & Calendar", "the sign-in has expired or was removed", (
            "Run: jarvis.bat --connect-google (if Google says the app is in testing, publish it on the consent screen "
            "so the sign-in stops expiring every 7 days).")


def _check_spotify():
    from . import config
    if not config.SPOTIFY_CLIENT_ID:
        return WARN, "Spotify", "not set up (optional)", "See 'Connect Spotify' in the README."
    if not (config.DATA_DIR / "spotify_token.json").exists():
        return WARN, "Spotify", "not signed in", "Run: jarvis.bat --connect-spotify"
    return OK, "Spotify", "connected", ""


def _check_telegram():
    import re
    from . import config
    token = config.TELEGRAM_TOKEN
    if not token:
        return WARN, "Telegram", "not set up (optional)", "See 'Telegram' in the README to control Jarvis from your phone."
    if not re.fullmatch(r"\d{5,}:[\w-]{30,}", token):
        return FAIL, "Telegram", "the bot token doesn't look right", "Copy it again from @BotFather into .env."
    return OK, "Telegram", "token set (send /pair to your bot if you haven't)", ""


def _check_offline():
    from . import config, local_brain
    if config.BRAIN == "claude":
        return WARN, "Free offline mode", "off (optional)", ("To use Jarvis free when the credit runs out: install "
                                                             "Ollama from https://ollama.com, run 'ollama pull llama3.2:3b', "
                                                             "then set JARVIS_BRAIN=auto in .env.")
    if local_brain.available():
        return OK, "Free offline mode", f"{config.LOCAL_MODEL} ready", ""
    if not shutil.which("ollama") and not Path(os.path.expandvars(r"%LOCALAPPDATA%\Programs\Ollama\ollama.exe")).exists():
        return FAIL, "Free offline mode", "Ollama isn't installed", "Install it from https://ollama.com, then run: ollama pull " + config.LOCAL_MODEL
    return FAIL, "Free offline mode", f"{config.LOCAL_MODEL} isn't ready", (
        f"Open Ollama (it runs in the tray), then run: ollama pull {config.LOCAL_MODEL}")


def _check_tailscale():
    exe = shutil.which("tailscale") or (r"C:\Program Files\Tailscale\tailscale.exe"
                                        if Path(r"C:\Program Files\Tailscale\tailscale.exe").exists() else None)
    if not exe:
        return WARN, "Phone away from home", "Tailscale isn't installed (optional)", (
            "Your phone works on the same Wi-Fi already. For anywhere else, see 'Use it away from home' in the README.")
    try:
        out = subprocess.run([exe, "status"], capture_output=True, text=True, timeout=10,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode == 0:
            return OK, "Phone away from home", "Tailscale connected", ""
    except Exception:
        pass
    return WARN, "Phone away from home", "Tailscale is installed but not connected", "Open Tailscale and sign in."


def _check_port(inside_jarvis):
    from . import config
    if inside_jarvis:
        return None
    try:
        socket.create_connection(("127.0.0.1", config.PORT), timeout=1).close()
        return WARN, "HUD port", f"port {config.PORT} is already in use", (
            "Jarvis is probably already running (check the taskbar). If not, another app uses the port: set "
            "JARVIS_PORT=8766 in .env.")
    except OSError:
        return OK, "HUD port", f"{config.PORT} free", ""


def _check_disk():
    free = shutil.disk_usage(Path.home()).free / 1e9
    if free > 3:
        return OK, "Disk space", f"{free:.0f} GB free", ""
    return WARN, "Disk space", f"only {free:.1f} GB free", "Free up some space: speech and offline models need a few GB."


def run(inside_jarvis=False):
    """All the checks, in order: [(status, name, what we found, how to fix it)]."""
    results = []
    for check in (_check_python, _check_packages, _check_env):
        results.append(check())
    if any(r[0] == FAIL for r in results[1:]):
        return results  # without the components or settings, the rest can't be checked
    checks = [_check_internet, _check_claude, _check_voice, _check_speakers, _check_microphone, _check_camera,
              _check_google, _check_spotify, _check_telegram, _check_offline, _check_tailscale, _check_disk]
    for check in checks:
        try:
            results.append(check())
        except Exception as e:
            results.append((WARN, check.__name__.removeprefix("_check_").title(), f"couldn't check: {e}", ""))
    port = _check_port(inside_jarvis)
    if port:
        results.append(port)
    return results


def spoken_summary():
    """For 'check my setup' inside Jarvis."""
    results = run(inside_jarvis=True)
    fails = [r for r in results if r[0] == FAIL]
    warns = [r for r in results if r[0] == WARN and "optional" not in r[2]]
    fine = sum(r[0] == OK for r in results)
    if not fails and not warns:
        return f"All {fine} checks passed, sir. Everything's in order."
    parts = [f"{r[1]}: {r[2]}. {r[3]}" for r in fails + warns]
    return (f"{fine} checks passed, {len(fails) + len(warns)} need{'s' if len(fails) + len(warns) == 1 else ''} "
            "attention. " + " ".join(parts))


def main():
    os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
    os.system("")  # turn on colours in the Windows console
    colour = {OK: "\033[92m", WARN: "\033[93m", FAIL: "\033[91m"}
    mark = {OK: "OK  ", WARN: "NOTE", FAIL: "FIX "}
    print("\n  JARVIS setup doctor: checking everything Jarvis needs...\n")
    print(f"  Windows {platform.release()}, folder: {ROOT}\n")
    results = run()
    for status, name, found, fix in results:
        print(f"  {colour[status]}[{mark[status]}]\033[0m {name}: {found}")
        if fix and status != OK:
            print(f"         -> {fix}")
    fails = sum(r[0] == FAIL for r in results)
    print()
    if fails:
        print(f"  {colour[FAIL]}{fails} thing{'s' if fails != 1 else ''} to fix\033[0m. Do the steps marked FIX, then run "
              "this again.")
    else:
        print(f"  {colour[OK]}All set.\033[0m Things marked NOTE are optional. Start Jarvis with jarvis.bat.")
    print()


if __name__ == "__main__":
    main()
