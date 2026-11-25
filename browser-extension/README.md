# JARVIS browser extension (Edge or Chrome)

Ask Jarvis about the page you're on, or about text you've highlighted. The answer shows in the popup and in the
Jarvis HUD, read aloud if you like.

It only ever talks to Jarvis on your own PC (`127.0.0.1`), never to the internet. The page goes to the AI model
Jarvis uses, with secrets hidden, and Jarvis answers with **no tools at all**, so nothing written on a web page can
make him do anything.

## Install (2 minutes)

1. Open `edge://extensions` (or `chrome://extensions`).
2. Turn on **Developer mode**.
3. Click **Load unpacked** and pick this `browser-extension` folder.
4. Click the Jarvis icon in the toolbar (pin it from the puzzle-piece menu), and paste your key. You'll find it in the
   file `data\access_key.txt` in your Jarvis folder.

## Use it

- **Alt+J**, or click the icon: type a question, or press **SUMMARISE PAGE** / **SUMMARISE SELECTION**.
- Right-click highlighted text: **Ask Jarvis about this**. Right-click a page: **Summarise this page with Jarvis**.

Jarvis must be running (`jarvis.bat`). If you changed `JARVIS_PORT`, that's the one setting this extension can't
guess: change `port` from 8765 in `shared.js`.
