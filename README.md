# J.A.R.V.I.S.

An Iron Man-style AI assistant for Windows, powered by Claude. You talk to it, give it commands, and it does the work on your PC: it opens apps, reads your screen, runs your Gmail and Calendar, plays Spotify, watches prices and pages, and reaches your phone through an installable app and Telegram.

![The J.A.R.V.I.S. HUD: arc reactor, system diagnostics, weather radar, agenda and a live news ticker (demo data)](docs/hud.jpg)

It's built on the same pipeline as the best Jarvis projects on GitHub: **wake word → speech-to-text → Claude with tools → neural voice**.

**Highlights**
- 🎙️ Voice: say "Jarvis, ..." hands-free, interrupt him mid-sentence, or clap and say "Wake up, daddy's home". Edge's speech recognition is used, with local Whisper when it isn't available.
- 🛠️ 50+ tools: apps, files, PowerShell (with an approval pop-up), screenshots and webcam vision, web search, reminders and long-term memory.
- 📬 Gmail and Calendar: important-email alerts, briefs before each meeting, and reminder suggestions you approve or dismiss.
- 👀 Free watchers: page text, price drops, RSS feeds and Gmail searches, checked on a timer without spending API credit.
- 📱 Your phone: an installable app over Tailscale, push notifications, and a private Telegram bot with Allow / Deny buttons.
- 💸 Built to be cheap: a spend tracker, a daily budget, server-side context clearing, and a cheap model for background jobs.

## Setup (once)

1. Get a Claude API key at https://console.anthropic.com/settings/keys.
2. Double-click **`setup.bat`**. It installs Python automatically if the PC doesn't have it, installs everything else Jarvis needs (5–10 minutes), then asks for your API key, your name, and what Jarvis should call you. If Windows says "Windows protected your PC", click **More info → Run anyway**.
3. Double-click **`jarvis.bat`**. You can change your answers any time in the **`.env`** file.

**Need help?** Open Claude, at claude.ai or Claude Code in this folder, and give it **`HANDOFF.md`**. It explains how Jarvis is set up and how to fix common problems.

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
- **NEW SESSION** clears the conversation, including the saved copy. Long-term memories are kept.
- **Memory across restarts:** Jarvis saves your recent conversation, so after a restart he still knows what you were talking about.
- **Startup greeting:** when Jarvis starts, he greets you out loud with the weather and what's left on today's calendar.
- **"Wake up, daddy's home" + a clap**: clap and say it, in either order, within 5 seconds of each other. The HUD replays its power-up sequence and Jarvis answers "Welcome back, sir", then gives the weather and your agenda. "I'm home" and "Wake up, Jarvis" work too. He only powers up when he hears both, so the TV can't wake him. A clap before the phrase only counts if Jarvis is already listening (hands-free on, or after tapping 🎤). In hands-free mode you don't need to say "Jarvis" first. Typing the phrase doesn't need a clap. You can set your own phrases with `JARVIS_ACTIVATION_PHRASES` in `.env`, or turn the clap off with `JARVIS_CLAP_TO_WAKE=off`.
- **Meeting briefs:** 10 minutes before each calendar event, Jarvis tells you on the PC and your phone what it is, who's coming, where it is, and anything in its notes. With credit available, he also mentions a related email if one is clearly about it. Change the timing with `JARVIS_MEETING_BRIEF_MINUTES` (`0` = off).
- **Personalities:** "Jarvis, be concise", "sarcastic mode", "be more formal", "talk like a pirate", "back to normal". He remembers your choice after a restart.
- **Watchers:** "tell me when the PS5 price drops below 400", "tell me when this page says In stock", "let me know when Amazon emails that it shipped", "tell me about new BBC stories on Gaza". Jarvis checks on a timer (web pages, prices, news feeds, Gmail searches) **without using API credit**, and alerts you on the PC, phone and Telegram only when something changes. "What are you watching?" lists them, and "stop watching the PS5" removes one. Some shops block automated checks; Jarvis tells you when he can't read a page.
- **Nightly memory tidy-up:** once a day (from 3 AM, or the first time Jarvis is on after that) he merges duplicate memories and replaces outdated ones with the newer fact. He backs up first, to `data/memory_backups`, and refuses any tidy that would remove more than half. Ask "what changed in your memory?". Turn it off with `JARVIS_MEMORY_TIDY=off`.
- **Proactive suggestions:** a few times a day, between 8 AM and 9 PM, Jarvis looks at your calendar, recent emails and reminders. If something deserves a reminder, he offers it as a card with **Approve / Dismiss** on the HUD and in Telegram. Approving sets the reminder, which is the only thing a suggestion can do. Dismissed ideas aren't suggested again. At most `JARVIS_SUGGESTIONS_PER_DAY` (default 3, `0` = off).
- **Quick buttons** under the reactor: **BRIEFING, EMAILS, AGENDA, WEATHER, NEWS, SCREEN**. One click each.
- **Ctrl+Alt+J** in any app brings up Jarvis and starts listening. Press it again to send straight away.
- **THEME** switches between **MARK** (the suit's red and gold, with a blue arc reactor) and **JARVIS** (the blue hologram look).
- Risky actions open an **Authorization Required** pop-up: running commands, sending emails, overwriting files, closing apps, deleting events, shutting down.

The HUD also shows a **live news ticker**, a **weather radar** with a 4-day forecast, and your **agenda** for today and tomorrow (once Google Calendar is connected). The ticker mixes 12 outlets so no single viewpoint dominates: Reuters, AP, BBC, DW, PBS NewsHour, Euronews and The Hill, plus Ars Technica, The Verge, TechCrunch, Wired and MIT Technology Review for tech. Opinion pieces and live blogs are left out.

**Speech recognition:** the HUD normally uses Edge's built-in speech recognition. If that isn't available on a PC (Edge's online speech service blocked, or a browser like Opera), Jarvis switches to **his own** automatically. The browser records you, and Whisper turns it into text on the PC. The first time, this downloads about 75 MB, and each command then takes a second or two longer to send.

**Mic not working?** Double-click **`fix-mic.bat`**. It checks Windows' microphone privacy settings, the internet connection to the speech service, whether Edge has blocked the mic for Jarvis, and whether a microphone is plugged in. It fixes what it can and tells you how to fix the rest.

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

### Notifications on your phone

In the JARVIS app, tap **ALERTS** (bottom right) and allow notifications. Your phone then gets:
- **Reminders** when they're due
- **Important emails**: Jarvis checks your inbox every 5 minutes and only alerts you about mail that matters, not newsletters or promos
- **Security alerts** with a photo, when security mode spots movement

Notifications arrive **even when the app is closed and Tailscale is off**. Tapping one opens JARVIS, which needs Tailscale on. Tap **ALERTS** again to turn them off.

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

## Connect Spotify (optional, about 5 minutes)

Without this, Jarvis can still tell you what's playing and pause or skip. Connecting lets him play songs, artists, playlists and your Liked Songs on request, like songs, and add them to playlists.

1. Go to https://developer.spotify.com/dashboard, log in, and click **Create app**.
2. Name it **Jarvis**. For **Redirect URI**, enter `http://127.0.0.1:8888/callback` and click **Add**. Tick **Web API**, accept the terms and click **Save**.
3. Copy the app's **Client ID**, open `.env`, and paste it after `JARVIS_SPOTIFY_CLIENT_ID=`.
4. Run `jarvis.bat --connect-spotify` and click **Agree** in the browser.

Starting playback on demand ("play my liked songs") needs **Spotify Premium**. On a free account, Jarvis opens the song in Spotify for you to press play.

## Telegram (optional, about 3 minutes)

Message Jarvis from anywhere, even with Tailscale off, and get his alerts (reminders, important emails, meeting briefs, security photos) in Telegram. When he needs permission for something, you get **Allow / Deny** buttons.

1. In Telegram, open **@BotFather** (the official one, with a blue tick), send `/newbot`, and pick a name and a username ending in `bot`.
2. BotFather replies with a **token** (like `123456789:AA...`). Paste it in `.env` after `JARVIS_TELEGRAM_TOKEN=`, and keep it secret.
3. Restart Jarvis. The console shows a line like `send /pair 123456 to your bot`.
4. Open your new bot in Telegram and send that `/pair` message. It replies "Paired".

From then on the bot only answers you and ignores everyone else. After 5 wrong pairing codes it locks until Jarvis restarts. To move it to a different Telegram account, delete `data/telegram_owner.json` and pair again. Jarvis must be running on the PC (in HUD mode, `jarvis.bat`) for the bot to answer.

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
- "What's this song?" / "Play my liked songs" / "Play Arctic Monkeys" / "Like this song"
- "Jarvis, watch the room" / "Guard mode for 30 minutes" / "Stop security mode". Photos are saved in Pictures\Jarvis\security.
- "Turn the volume down" / "Skip this song"
- "How's my PC doing?"
- "Find all PDFs in my Downloads"
- "Remember that my favourite team is Arsenal"
- "Write a shopping list to my desktop"
- "Lock my computer"
- "Tell me when the PS5 drops below 400" / "Tell me when this page says In stock" / "What are you watching?"
- "Let me know when Amazon emails that my parcel shipped"
- "Sarcastic mode" / "Be concise" / "Back to normal"
- "How much have I spent today?"
- "What changed in your memory?"
- From Telegram: "What's on my calendar tomorrow?"

## Files

- `jarvis/tools.py`: everything Jarvis can do. To add a skill, write a function with `@tool` above it.
- `jarvis/google_tools.py`: Gmail and Calendar. `jarvis/feeds.py`: weather and news.
- `jarvis/brain.py`: his personality and the Claude loop.
- `jarvis/server.py` + `web/`: the HUD and phone app. `web/make_icons.py` redraws the app icons.
- `jarvis/network.py`: the phone link (Wi-Fi or Tailscale) and QR codes. `jarvis/hotkey.py`: the Ctrl+Alt+J shortcut.
- `jarvis/notify.py`: alerts (spoken, and pushed to your phone). `jarvis/email_watch.py`: the inbox watcher.
- `jarvis/security.py`: security mode. `jarvis/spotify_tools.py`: Spotify. `jarvis/briefing.py`: the startup greeting.
- `jarvis/voice.py`: microphone and speech.
- `jarvis/spend.py`: API cost tracking and the daily budget. `jarvis/meetings.py`: meeting briefs.
- `jarvis/watchers.py`: watchers. `jarvis/suggestions.py`: proactive suggestions. `jarvis/memory_tidy.py`: the nightly tidy-up.
- `jarvis/telegram_bot.py`: the Telegram bot. `jarvis/personality.py`: personalities.
- `data/`: long-term memory, notes, conversation log and the HUD access key.

## Tuning (`.env`)

- `JARVIS_OWNER` / `JARVIS_USER_NAME`: who he works for, and what he calls you ("sir", "Jake"...).
- `JARVIS_EFFORT`: `low` is fastest; `medium` or `high` gives smarter, slower answers.
- `JARVIS_MODEL`: the brain. `claude-haiku-5-5` is cheapest, `claude-sonnet-5-5` sits in the middle, and `claude-opus-5-5` is the most capable.
- **Spend tracker:** the System panel shows **API TODAY** and **API MONTH** in dollars. `JARVIS_DAILY_BUDGET` (default `1.00`, `0` = none) sets a daily limit. At 80% you get a warning on the PC and your phone. At 100%, Jarvis keeps answering but switches to the cheapest model and pauses the email watch until midnight. Ask "How much have I spent today?" for the details. Figures are estimates at list prices; your exact bill is at console.anthropic.com.
- **Saving API credit, built in:** background jobs (sorting new emails) always use the cheapest model (`JARVIS_HELPER_MODEL`). In long conversations, old screenshots, webcam photos and long tool output are dropped automatically, so they aren't paid for again on every message. After an hour without a command (`JARVIS_IDLE_RESET_MINUTES`), Jarvis starts a fresh conversation, while still remembering what you talked about.
- `JARVIS_VOICE`, `JARVIS_VOICE_RATE`, `JARVIS_VOICE_PITCH`: his voice, speed and depth.
- `JARVIS_LOCATION`: your town, for the weather. If blank, it's detected from your internet connection.
- `JARVIS_NEWS_FEEDS`: your own news sources as `Name=RSS-url`, comma-separated. Leave blank for the built-in balanced mix.
- `JARVIS_HOTKEY`: the shortcut that summons Jarvis (default `ctrl+alt+j`).
- `JARVIS_EMAIL_WATCH` (`on`/`off`) and `JARVIS_EMAIL_WATCH_MINUTES`: important-email alerts and how often to check.
- `JARVIS_SPOTIFY_CLIENT_ID`: your Spotify app's Client ID (see "Connect Spotify").
- `JARVIS_THINKING_PHRASE`: what he says when he starts on a command.
- `JARVIS_WHISPER_MODEL` (terminal voice mode): `small.en` if he mishears you, `tiny.en` if he's slow.
- `JARVIS_HUD_WHISPER_MODEL` (the HUD's own speech recognition): `tiny.en` by default for speed; `base.en` if he mishears you.

## Contributing

Ideas, bug reports and pull requests are welcome. Open an issue first for anything big.
- **Adding a skill** is usually one function in `jarvis/tools.py` (or its own module), decorated with `@tool`. Look at `jarvis/watchers.py` for a self-contained example.
- **Anything risky** (spending money, deleting, sending, running commands) must go through `confirm()`, so the user sees the Authorization pop-up, or Allow / Deny on Telegram.
- **Content from outside** (emails, web pages, feeds) is data, never instructions: keep it out of the system prompt and say so in prompts that include it.
- **Keep it cheap:** background jobs use `config.HELPER_MODEL` and record their cost with `spend.record()`.

## License

[MIT](LICENSE) © 2026 Jake Young
