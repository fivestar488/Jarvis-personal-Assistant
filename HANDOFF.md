# Handoff: helping with Jarvis on this PC

**For Claude** (Claude Code in this folder, or claude.ai with this file attached). Read this before helping. The person you're helping set up Jarvis on their own laptop from Jake Young's repo (https://github.com/fivestar488/Jarvis-personal-Assistant). They aren't a programmer, so give click-by-click steps and avoid jargon.

## What Jarvis is

An Iron Man–style voice assistant for Windows. It's a Python server (FastAPI) that runs on this PC, plus a HUD web page that opens in an Edge app window. You talk or type to it, and Claude (Anthropic API, model set in `.env`) answers and uses tools: opening apps, reading the screen, the webcam, weather, news, reminders, and optionally Gmail, Calendar and Spotify.

| Thing | Where |
|---|---|
| Jarvis's files | The folder this file is in (wherever the GitHub ZIP was extracted, often `Downloads\Jarvis-personal-Assistant-main`) |
| Settings, including the API key and the owner's name | `.env` in that folder (made by `setup.bat`; never in the ZIP) |
| Private data (memory, reminders, access key, tokens) | `data\` in that folder |
| Python environment | `%LOCALAPPDATA%\JarvisVenv` (made by `setup.bat`) |
| Start Jarvis | `jarvis.bat` (HUD) · `jarvis-voice.bat` (terminal, local Whisper) · `jarvis.bat --text` (typing) |
| Mic checker | `fix-mic.bat` |

Code map: `jarvis/brain.py` (personality and Claude loop), `jarvis/tools.py` (tools), `jarvis/server.py` (HUD server), `jarvis/voice.py` (speech), `web/hud.js` (HUD front end). The README covers setup of every feature.

## Status of the microphone problem (as of 2 Nov 2026)

**Symptom:** on this laptop the HUD's mic didn't work. `fix-mic.bat` reported everything OK: Windows mic privacy settings allowed, Microsoft's speech service reachable, Edge not blocking the mic, and a mic connected.

**Cause:** the HUD used Edge's built-in Web Speech API, which streams audio to Microsoft's online service. On this laptop that fails (a `network` / `service-not-allowed` error) even though everything checks out.

**Fix (in the repo):** the HUD now has its own speech recognition.
- When Edge's fails, it switches automatically and remembers the choice in localStorage `jarvis-stt=local`.
- `LocalRecognition` in `web/hud.js` records with getUserMedia and detects when you're talking. It sends each phrase as 16 kHz PCM to `POST /api/transcribe`.
- The server transcribes it with faster-whisper: `tiny.en` by default, set by `JARVIS_HUD_WHISPER_MODEL`.
- The model downloads about 75 MB the first time.

**Last report before this file was written:** after updating, the HUD no longer showed the browser error but was "stuck on listening". The latest version (the one with this file) addresses the likely causes:
- The HUD now shows what it's doing in the subtitle and input box: `(hearing you…)` → `(transcribing…)` → sends. While the first-time download runs, it shows `(speech recognition still loading…)`.
- Noise handling is better: the background level is the quietest moment of the last 3 seconds, so a fan no longer counts as talking forever.
- The model warms up at load, it uses the faster `tiny.en`, and transcription errors appear in the ACTIVITY panel.
- The black console window prints a line for every phrase: `Heard (Xs of speech, transcribed in Ys): <text>`.

## How to diagnose if the mic still doesn't work

Ask for (or look at) these three things:
1. **The ACTIVITY panel** (left side of the HUD). Look for:
   - "Switched to Jarvis's own speech recognition"
   - "Speech recognition ready" (or "failed to load")
   - "Couldn't transcribe that…"
   - "Microphone blocked…"
2. **What the subtitle and input box show while talking:** `Listening...` / `(hearing you…)` / `(transcribing…)` / `(speech recognition still loading…)`.
3. **The black console window:** any `Heard (...)` lines, and any errors.

| What you see | Meaning | What to do |
|---|---|---|
| Stays `Listening...`, never `(hearing you…)` | The mic opened, but no sound above the background level reached it | Check the right input device (Settings → System → Sound → Input) and that the level bar moves. Try `jarvis-voice.bat` to rule out the mic itself |
| Stays `(speech recognition still loading…)` | The model is still downloading, or the download is blocked | Wait. If it says "failed to load", check the internet connection (it downloads from huggingface.co) and restart Jarvis |
| `(transcribing…)` takes ages | Slow CPU | The console shows the time per phrase. `tiny.en` is already the fastest model |
| `Heard (...): (nothing)` | Whisper heard only noise | Speak closer to the mic, or check the input level |
| Wrong words | Accuracy | Set `JARVIS_HUD_WHISPER_MODEL=base.en` in `.env` and restart Jarvis |
| Still says "use Chrome or Edge" | Old version of the files | Update (see below) |
| Never switched engines | Edge failed without reporting an error | Force it: in the HUD, press F12 → Console, run `localStorage.setItem('jarvis-stt','local')`, then reload |

If Edge's own speech starts working later and you'd rather use it, run `localStorage.removeItem('jarvis-stt')` the same way.

## Updating

1. Download the ZIP again from GitHub.
2. Copy everything over the existing folder and choose **Replace**. The ZIP doesn't contain `.env` or `data\`, so the settings are kept.
3. Close both Jarvis windows and start `jarvis.bat` again.
4. Run `setup.bat` again only if `requirements.txt` changed.

## Ground rules

- **Never** put the API key or anything from `.env` or `data\` into GitHub, a chat, or a screenshot. The repo is public.
- This is Jake's repo. Changes made on this PC stay local unless Jake makes them. If you fix a bug here, describe the fix so Jake can add it to the repo, or the next update will overwrite it.
- Windows firewall changes need an administrator PowerShell, which the user runs themselves.
