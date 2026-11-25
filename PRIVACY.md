# Privacy Policy for J.A.R.V.I.S.

*Effective 25 November 2026*

J.A.R.V.I.S. ("Jarvis") is a personal assistant app that you run on your own Windows PC. It is open source: all of its code is public in this repository, so you can check everything this policy says.

Jarvis has no company, servers or accounts of its own behind it. **Nobody but you receives your data from Jarvis.** The developer never sees it. The only exceptions are the third-party services listed below, which Jarvis uses to do what you ask.

## Google user data (Gmail and Google Calendar)

When you connect your Google account, Jarvis asks for these permissions:

| Permission | What Jarvis uses it for |
|---|---|
| Gmail (`gmail.modify`) | Search and read your emails when you ask; save drafts; send an email **only after you approve it** in a pop-up; mark emails as read; tell you about important new emails |
| Google Calendar (`calendar`) | Read your events for your agenda and briefings; add events or time blocks you ask for; delete an event **only after you approve it** |

How Jarvis handles this data:

- **It is processed on your PC.** Your Google sign-in token is stored only in the `data` folder on your own computer. It never goes to the developer or anywhere else.
- **To answer your requests,** the parts of an email or event that a request needs are sent to the AI model you've chosen:
  - Anthropic's Claude API (the default), under [Anthropic's privacy policy](https://www.anthropic.com/legal/privacy) and commercial terms;
  - or a model running entirely on your own PC (the optional offline mode through Ollama), in which case nothing leaves your computer.
- **Secrets are hidden first.** Card numbers, passwords, API keys and similar secrets found in emails are blanked out before anything is sent to the AI.
- **No selling, advertising or sharing.** Your Google data is never sold, never used for advertising, never used to train AI models by Jarvis, and never shared with anyone except as described above.
- **No humans read it.** No person reads your Google data, unless you read it yourself.

Jarvis's use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including the Limited Use requirements.

## Other data Jarvis handles

- **Your voice:**
  - If your browser's built-in speech recognition is used (for example, Microsoft Edge), your voice commands go to that browser maker's speech service.
  - Otherwise, speech is turned into text on your PC with Whisper.
  - Dictation (Ctrl+Alt+D) always runs on your PC.
- **Jarvis's spoken replies:** the text of each reply is sent to Microsoft's Edge text-to-speech service to create the voice.
- **Camera:** only used when you ask:
  - "look through the camera", "scan this", "log this meal";
  - security mode;
  - hand-gesture control.

  Hand tracking runs inside your browser, and the video never leaves your PC. Photos for a scan or a question are sent to the AI model, as above.
- **Screen:** a screenshot is taken only when you ask about your screen, and is sent to the AI model to answer.
- **Memory, notes, reminders, meal log, meeting notes and conversation history:** saved only in the `data` folder on your PC.
- **Your documents (Ask my files):** Jarvis builds a search index of the folders you choose (Documents and Desktop by default), stored only in the `data` folder on your PC. When you ask a question, only the few most relevant passages, with secrets hidden, are sent to the AI model to answer it.
- **Activity journal:** off unless you turn it on. Once a minute it notes the name and title of the window you're using, on your PC only. Never screenshots.
- **Clipboard history:** what you copy is kept in memory only while Jarvis runs, never saved to disk. Anything containing a secret is not kept at all.
- **Trip mode:** when you ask, Jarvis reads the subject lines and previews of travel emails (flights, hotels), with secrets hidden, so the AI model can find your trip dates. The trips are saved only on your PC.
- **Offline wake word:** off unless you turn it on. It listens to your microphone for "Hey Jarvis" entirely on your PC; no audio is saved or sent anywhere.
- **Point and ask:** a screenshot is taken only when you ask "what's this?", and it goes to the AI model to answer, like any screen question.
- **Parcels and subscriptions:** Jarvis looks at the subject lines and previews of order, shipping, receipt and billing emails. Only ones he hasn't seen before go to the AI model, with secrets hidden, so it can list parcels and recurring payments. The lists are saved only on your PC. Turn each off with `JARVIS_PACKAGE_WATCH=off` / `JARVIS_SUBSCRIPTION_WATCH=off`.
- **"Leave now" nudges:** for calendar events that have an address, the address (and your home address, if you set one) is sent to OpenStreetMap's Nominatim service to find it on the map. The two map points are sent to a public routing service (OSRM) to work out the travel time. Nothing else from the event is sent. Turn it off with `JARVIS_LEAVE_NUDGES=off`.
- **Browser extension (optional):** when you ask about a page, its title, address and text (or the part you highlighted) go from your browser to Jarvis on your PC, then to the AI model with secrets hidden, to answer you. It only talks to Jarvis on your own PC.
- **Daily notes:** saved as Markdown files in a folder on your PC (`Documents\Jarvis Daily Notes` by default).
- **Setup doctor:** to check your API key and credit, it sends Anthropic one tiny request (the word "Hi"). Everything else it checks stays on your PC.
- **Perimeter alerts:**
  - Jarvis reads Windows' own record of failed sign-ins.
  - It keeps a list of the devices your PC has seen on your Wi-Fi, without scanning the network.
  - Both stay on your PC.
  - After three failed sign-ins in 10 minutes, it takes a webcam photo, saved on your PC and sent only to your own phone.
- **Optional services:** only if you set them up yourself:
  - Spotify, to control your music;
  - Telegram, as your private bot;
  - weather from Open-Meteo, plus a rough location from your internet address;
  - news feeds.

  Each receives only what it needs for its feature.

## Keeping and deleting your data

Everything Jarvis stores is in the `data` folder on your PC, and you can delete it at any time.

To disconnect Google completely:
1. Remove Jarvis at [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
2. Delete `data/google_token.json`.

## Children

Jarvis is not meant for children under 13.

## Changes

If this policy changes, the new version will be published here with a new effective date. The full history of changes is in this repository's commit log.

## Contact

Questions about this policy: open an issue at [github.com/fivestar488/Jarvis-personal-Assistant/issues](https://github.com/fivestar488/Jarvis-personal-Assistant/issues).
