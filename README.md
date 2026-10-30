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
- **Quick buttons** under the reactor: **BRIEFING, EMAILS, AGENDA, WEATHER, NEWS, SCREEN**. One click each.
- **Ctrl+Alt+J** in any app brings up Jarvis and starts listening. Press it again to send straight away.
- **THEME** switches between **MARK** (the suit's red and gold, with a blue arc reactor) and **JARVIS** (the blue hologram look).
- Risky actions open an **Authorization Required** pop-up: running commands, sending emails, overwriting files, closing apps, deleting events, shutting down.

The HUD also shows a **live news ticker**, a **weather radar** with a 4-day forecast, and your **agenda** for today and tomorrow (once Google Calendar is connected). The ticker mixes 12 outlets so no single viewpoint dominates: Reuters, AP, BBC, DW, PBS NewsHour, Euronews and The Hill, plus Ars Technica, The Verge, TechCrunch, Wired and MIT Technology Review for tech. Opinion pieces and live blogs are left out.

`jarvis.bat` opens the HUD in its own Edge window, because voice input only works in Edge and Chrome. If you close that window, run `jarvis.bat` again to reopen it. Jarvis keeps running in the console window until you close it.

## JARVIS on your phone (installable app)

Jarvis runs on your PC, and your phone connects to it privately through **Tailscale**, a free app that links your own devices. This works anywhere (home, the office, mobile data), even on routers that block devices from reaching each other. Over Tailscale, Jarvis gets a secure address, so the phone version **installs as a real app** and **the microphone works**.

### One-time setup

1. **Install Tailscale on the PC** from https://tailscale.com/download and sign in (Google is easiest).
2. **Install Tailscale on your phone** (App Store / Google Play) and sign in with the **same account**.
3. **Turn on HTTPS:** go to https://login.tailscale.com/admin/dns, scroll to **HTTPS Certificates**, and click **Enable HTTPS**.
4. **Let the phone through the PC's firewall:** open **PowerShell as administrator** (Start → type PowerShell → right-click → Run as administrator) and paste this line. It only opens Jarvis's port, and only over Tailscale:
   ```
   New-NetFirewallRule -DisplayName "JARVIS HUD (Tailscale only)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765 -InterfaceAlias "Tailscale"
   ```
5. **Restart Jarvis.** He sets up the secure address himself.

### Install the app

1. Turn **Tailscale on** on your phone.
2. In the HUD on the PC, click **PHONE**. It should say **TAILSCALE · SECURE**.
3. Scan the QR code with your phone's camera and open it in **Chrome**.
4. Tap **⋮ → Install app**, and choose **Install** (not "Create shortcut").
5. Open **JARVIS** from your home screen. The first time you tap 🎤, allow the microphone.

### Using it

- Tailscale only needs to be **on while you use Jarvis**. Turn it on or off from the Tailscale app's switch, its notification, or a Quick Settings tile. With it off, the app shows OFFLINE.
- Jarvis must be **running on the PC**.
- On the phone, the panels become tabs: COMMS, AGENDA, WEATHER, SYSTEM and LOG.
- **Without Tailscale**, the PHONE code uses your Wi-Fi address instead. The phone must then be on the same Wi-Fi, and the code changes when the PC changes network. Jarvis notices within seconds, the PHONE button blinks, and a new code appears in the HUD and the console.
- The link contains a secret key, so only you can control your PC. Keep it private. To reset it, delete `data/access_key.txt` and reinstall the app.

## Connect Gmail & Calendar (once, about 10 minutes)

Jarvis talks to Google directly, so he needs his own key from Google:

1. Go to https://console.cloud.google.com, sign in, and create a project called **Jarvis**.
2. Under **APIs & Services → Library**, enable **Gmail API** and **Google Calendar API**.
3. Under **Google Auth Platform**, set up the consent screen: choose **External**, give it the name "Jarvis" and your email, and save. Then under **Audience → Test users**, click **+ Add users** and add your own Gmail address. (While the app is in "Testing", Google signs Jarvis out about once a week. When that happens, just run step 6 again.)
4. Under **APIs & Services → Credentials**, click **Create credentials → OAuth client ID → Desktop app**, then **Download JSON**.
5. Rename that file to `google_credentials.json` and put it in this project's `data` folder.
6. Run `jarvis.bat --connect-google`. Sign in, and if Google says the app isn't verified, click **Continue** (or **Advanced → Go to Jarvis**). That warning only means it's your own private app.

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
- `jarvis/server.py` + `web/`: the HUD and phone app. `web/make_icons.py` redraws the app icons.
- `jarvis/network.py`: the phone link (Wi-Fi or Tailscale) and QR codes. `jarvis/hotkey.py`: the Ctrl+Alt+J shortcut.
- `jarvis/voice.py`: microphone and speech.
- `data/`: long-term memory, notes, conversation log and the HUD access key.

## Tuning (`.env`)

- `JARVIS_OWNER` / `JARVIS_USER_NAME`: who he works for, and what he calls you ("sir", "Jake"...).
- `JARVIS_EFFORT`: `low` is fastest; `medium` or `high` gives smarter, slower answers.
- `JARVIS_VOICE`, `JARVIS_VOICE_RATE`, `JARVIS_VOICE_PITCH`: his voice, speed and depth.
- `JARVIS_LOCATION`: your town, for the weather. If blank, it's detected from your internet connection.
- `JARVIS_NEWS_FEEDS`: your own news sources as `Name=RSS-url`, comma-separated. Leave blank for the built-in balanced mix.
- `JARVIS_HOTKEY`: the shortcut that summons Jarvis (default `ctrl+alt+j`).
- `JARVIS_THINKING_PHRASE`: what he says when he starts on a command.
- `JARVIS_WHISPER_MODEL` (terminal voice mode): `small.en` if he mishears you, `tiny.en` if he's slow.
