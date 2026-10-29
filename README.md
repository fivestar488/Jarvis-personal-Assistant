# J.A.R.V.I.S.

Jake Young's personal AI assistant for Windows. You can talk to it, give it commands, and have it do tasks on your PC. It has an Iron Man-style HUD that also works on your phone.

It's built on the same pipeline as the best Jarvis projects on GitHub: **wake word → speech-to-text → Claude with tools → neural voice**.

## Setup (once)

1. Double-click **`setup.bat`**.
2. Get an API key at https://console.anthropic.com/settings/keys.
3. Open **`.env`** and paste the key after `ANTHROPIC_API_KEY=`.

## Run

| Launcher | What it does |
|---|---|
| `jarvis.bat` | **The HUD.** Opens in your browser, with the arc reactor, live diagnostics, voice and hands-free mode |
| `jarvis.bat --text` | Type to Jarvis in the terminal (`--text --speak` to hear him) |
| `jarvis-voice.bat` | Hands-free in the terminal using local Whisper: say **"Jarvis, …"** |

### Using the HUD

- **Mic button**: push to talk. Use Chrome or Edge.
- **HANDS-FREE**: always listening. Say "Jarvis, open Spotify". After he answers, you have a few seconds to ask a follow-up without saying "Jarvis" again.
- **VOICE**: turns his spoken replies on or off for that device.
- **Tap the reactor** to interrupt him while he's speaking.
- **NEW SESSION** clears the conversation. Long-term memories are kept.
- Risky actions open an **Authorization Required** pop-up: running commands, overwriting files, closing apps, shutting down.

### On your phone

When the HUD starts, the console shows a **QR code**. Scan it with your phone's camera while on the same Wi-Fi. Then use **Share → Add to Home Screen** to get a JARVIS app icon.

- The first time, Windows Firewall may ask about Python. Allow it on **Private networks**.
- To talk on your phone, tap the microphone on your keyboard. Phone browsers block the in-page mic on home networks.
- The link contains a secret key, so only you can control your PC. Keep it private. To reset it, delete `data/access_key.txt`.
- Your PC must be on with Jarvis running.

## Things to try

- "Introduce yourself"
- "Open Spotify" / "Close Chrome"
- "Play Thunderstruck on YouTube"
- "What's the weather in London tomorrow?" / "What's the latest news on SpaceX?"
- "What's on my screen?" / "Help me with this error"
- "Remind me in 10 minutes to take the pizza out"
- "Turn the volume down" / "Skip this song"
- "How's my PC doing?"
- "Find all PDFs in my Downloads"
- "Remember that my favourite team is Arsenal"
- "Write a shopping list to my desktop"
- "Lock my computer"

## Files

- `jarvis/tools.py`: everything Jarvis can do. To add a skill, write a function with `@tool` above it.
- `jarvis/brain.py`: his personality and the Claude loop.
- `jarvis/server.py` + `web/`: the HUD.
- `jarvis/voice.py`: microphone and speech.
- `data/`: long-term memory, notes, conversation log and the phone access key.

## Tuning (`.env`)

- `JARVIS_OWNER` / `JARVIS_USER_NAME`: who he works for, and what he calls you ("sir", "Jake"...).
- `JARVIS_EFFORT`: `low` is fastest; `medium` or `high` gives smarter, slower answers.
- `JARVIS_VOICE`: any Edge voice, e.g. `en-GB-ThomasNeural`.
- `JARVIS_THINKING_PHRASE`: what he says when he starts on a command.
- `JARVIS_WHISPER_MODEL` (terminal voice mode): `small.en` if he mishears you, `tiny.en` if he's slow.
