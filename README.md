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
| `jarvis.bat` | **The HUD.** Opens in its own window, with the arc reactor, live diagnostics, voice and hands-free mode |
| `jarvis.bat --text` | Type to Jarvis in the terminal (`--text --speak` to hear him) |
| `jarvis-voice.bat` | Hands-free in the terminal using local Whisper: say **"Jarvis, …"** |

### Using the HUD

- **Mic button**: push to talk. Use Chrome or Edge.
- **HANDS-FREE**: always listening. Say "Jarvis, open Spotify". After he answers, you have a few seconds to ask a follow-up without saying "Jarvis" again.
- **Interrupting**: in hands-free mode, say **"Jarvis…"** or **"stop"** while he's talking to cut him off. You can also tap the reactor.
- **VOICE**: turns his spoken replies on or off for that device.
- **FILTER**: the "suit filter" gives his voice the polished, slightly digital sound from the films.
- **NEW SESSION** clears the conversation. Long-term memories are kept.
- Risky actions open an **Authorization Required** pop-up: running commands, sending emails, overwriting files, closing apps, deleting events, shutting down.

The HUD also shows a **live news ticker**, a **weather radar** with a 4-day forecast, and your **agenda** for today and tomorrow (once Google Calendar is connected).

`jarvis.bat` opens the HUD in its own Edge window, because voice input only works in Edge and Chrome. If you close that window, run `jarvis.bat` again to reopen it. Jarvis keeps running in the console window until you close it.

### On your phone

Click **PHONE** in the HUD (or look in the console window) and scan the QR code with your phone's camera. Then use **Share → Add to Home Screen** to get a JARVIS app icon. On the phone, the panels become tabs.

- **The code follows your PC between networks.** Jarvis checks every few seconds. When the PC moves (office to home, a new Wi-Fi), the PHONE button blinks and a new code appears in the HUD and the console. Scan it again.
- Without Tailscale, the phone must be on the **same Wi-Fi** as the PC, and some routers (including HOT's) block devices from reaching each other.
- **With Tailscale, it works everywhere:** on any Wi-Fi, mobile data, or a router that blocks devices. Install Tailscale on the PC and your phone, sign in to both with the same account, and the code switches to the Tailscale link automatically.
- To talk on your phone, tap your keyboard's microphone.
- The link contains a secret key, so only you can control your PC. Keep it private. To reset it, delete `data/access_key.txt`.

## Connect Gmail & Calendar (once, about 10 minutes)

Jarvis talks to Google directly, so he needs his own key from Google:

1. Go to https://console.cloud.google.com, sign in, and create a project called **Jarvis**.
2. Under **APIs & Services → Library**, enable **Gmail API** and **Google Calendar API**.
3. Under **APIs & Services → OAuth consent screen**, choose **External**, give it the name "Jarvis" and your email, and save. Then click **Publish app**, so you don't have to sign in again every week.
4. Under **APIs & Services → Credentials**, click **Create credentials → OAuth client ID → Desktop app**, then **Download JSON**.
5. Rename that file to `google_credentials.json` and put it in this project's `data` folder.
6. Run `jarvis.bat --connect-google`. Sign in, and when Google says the app isn't verified, click **Advanced → Go to Jarvis**. That warning only means it's your own private app.

You can then say "What's on my calendar today?", "Any important emails?", "Draft a reply to Sarah saying I'll be late", or "Give me my morning briefing".

## Things to try

- "Introduce yourself"
- "Open Spotify" / "Close Chrome"
- "Play Thunderstruck on YouTube"
- "What's the weather in London tomorrow?" / "What's the latest news on SpaceX?"
- "What's on my screen?" / "Help me with this error"
- "Good morning Jarvis, give me my briefing"
- "What am I holding?" / "How do I look?" (uses the webcam)
- "Remind me at 6pm to call mum". Reminders are saved, so they survive restarts, and he tells you about any he missed while he was off.
- "What reminders do I have?" / "Cancel the mum reminder"
- "What's on my calendar tomorrow?" / "Add dentist on Friday at 3pm"
- "Read my latest email from Amazon"
- "Turn the volume down" / "Skip this song"
- "How's my PC doing?"
- "Find all PDFs in my Downloads"
- "Remember that my favourite team is Arsenal"
- "Write a shopping list to my desktop"
- "Lock my computer"

## Files

- `jarvis/tools.py`: everything Jarvis can do. To add a skill, write a function with `@tool` above it.
- `jarvis/google_tools.py`: Gmail and Calendar. `jarvis/feeds.py`: weather and news.
- `jarvis/brain.py`: his personality and the Claude loop.
- `jarvis/server.py` + `web/`: the HUD.
- `jarvis/voice.py`: microphone and speech.
- `data/`: long-term memory, notes, conversation log and the HUD access key.

## Tuning (`.env`)

- `JARVIS_OWNER` / `JARVIS_USER_NAME`: who he works for, and what he calls you ("sir", "Jake"...).
- `JARVIS_EFFORT`: `low` is fastest; `medium` or `high` gives smarter, slower answers.
- `JARVIS_VOICE`, `JARVIS_VOICE_RATE`, `JARVIS_VOICE_PITCH`: his voice, speed and depth.
- `JARVIS_LOCATION`: your town, for the weather. If blank, it's detected from your internet connection.
- `JARVIS_NEWS_FEEDS`: the news ticker's sources (any RSS feeds).
- `JARVIS_THINKING_PHRASE`: what he says when he starts on a command.
- `JARVIS_WHISPER_MODEL` (terminal voice mode): `small.en` if he mishears you, `tiny.en` if he's slow.
