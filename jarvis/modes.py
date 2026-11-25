"""Switches for how Jarvis runs: Low Power Mode, pausing the microphone, and live captions.

Low Power Mode is for a laptop on battery or a slow moment: the HUD stops always-on listening, hand tracking and
its animations, and the desk scanner's watch mode stops. Typing, the mic button and the hotkey still work.
"""
from . import captions, tools
from .tools import tool


def _hud(event):
    return bool(tools.ui and hasattr(tools.ui, "hud") and tools.ui.hud(event))


def low_power(on):
    if on:
        from . import scanner
        if scanner.watching():
            scanner.stop_watching()
    if not _hud({"type": "power", "low": on}) and on:
        return "Low Power Mode is a HUD setting. Open the HUD with jarvis.bat."
    return ("Low Power Mode on. I've paused always-on listening, hand tracking and the animations. "
            "Press the mic button or the hotkey when you need me." if on else "Low Power Mode off. Back to full power.")


def pause_listening(paused):
    _hud({"type": "listening", "paused": paused})
    return ("Listening paused. I won't hear the room until you tap the mic or press the hotkey and say "
            "'resume listening'." if paused else "Listening again.")


@tool("Turn Low Power Mode on or off: pauses always-on listening, hand tracking, the desk scanner and the HUD's "
      "animations to save battery and CPU. Use for 'low power mode', 'save battery', 'go quiet on the CPU'.",
      {"on": {"type": "boolean"}}, ["on"])
def set_low_power(on):
    return low_power(on)


@tool("Pause or resume the HUD's always-on listening (for calls or meetings he doesn't want heard). "
      "'pause listening', 'stop listening', 'resume listening'.",
      {"paused": {"type": "boolean"}}, ["paused"])
def set_listening_paused(paused):
    return pause_listening(paused)


@tool("Turn live captions on or off: what Jarvis says shown at the bottom of the screen, over every app.",
      {"on": {"type": "boolean"}}, ["on"])
def set_captions(on):
    return captions.set_enabled(on)
