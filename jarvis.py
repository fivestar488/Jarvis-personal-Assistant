"""JARVIS - your personal AI assistant.

    python jarvis.py            Iron Man HUD in your browser (also works on your phone)
    python jarvis.py --text     type to Jarvis in the terminal (add --speak to hear him)
    python jarvis.py --voice    hands-free in the terminal: say "Jarvis, ..." to give a command
"""
import argparse
import datetime as dt
import os
import re
import socket
import subprocess
import sys
import threading
import webbrowser

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from jarvis import config, tools
from jarvis.brain import Brain

console = Console()

EXIT_PHRASES = {"exit", "quit", "goodbye", "bye", "goodbye jarvis", "power down", "go offline", "shut yourself down"}
RESET_PHRASES = {"reset", "new conversation", "new session", "start over", "clear", "forget this conversation"}
END_FOLLOW_UP = {"thanks", "thank you", "cheers", "never mind", "nevermind", "that's all", "thats all", "stop", "cancel", "no", "nothing"}
YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "do it", "go ahead", "affirmative", "confirm", "please do", "correct"}

BANNER = r"""[bold cyan]
     ██╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗
     ██║██╔══██╗██╔══██╗██║   ██║██║██╔════╝
     ██║███████║██████╔╝██║   ██║██║███████╗
██   ██║██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║
╚█████╔╝██║  ██║██║  ██║ ╚████╔╝ ██║███████║
 ╚════╝ ╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝[/bold cyan]"""


def normalize(text):
    return re.sub(r"[^\w\s']", "", text.lower()).strip()


def log(who, text):
    with open(config.LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {who}: {text}\n")


def greeting():
    hour = dt.datetime.now().hour
    part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
    return f"Good {part}, {config.USER_NAME}. Jarvis online. How can I help?"


class Interface:
    """What tools use to ask permission and to speak up (reminders), in the terminal modes."""

    def __init__(self, mouth=None, ears=None):
        self.mouth, self.ears = mouth, ears

    def show(self, text):
        console.print(Panel(Markdown(text), title="[bold cyan]JARVIS", title_align="left", border_style="cyan"))
        log("JARVIS", text)
        if self.mouth:
            self.mouth.say(text)

    def announce(self, text):
        console.print()
        self.show(text)

    def confirm(self, question):
        console.print(f"[bold yellow]⚠ {question}[/]")
        if self.ears:
            self.mouth.say(question.splitlines()[0] + " Yes or no?")
            answer = self.ears.listen(timeout=8, phrase_limit=4) or ""
            console.print(f"[dim]heard: {answer or '(nothing)'}[/]")
            said = f" {normalize(answer)} "
            return any(f" {w} " in said for w in YES_WORDS) and " no " not in said
        return console.input("[yellow]Allow? (y/n) [/]").strip().lower() in ("y", "yes")


def think(brain, ui, text):
    """Ask the brain, show the reply. Returns False if the program should exit."""
    command = normalize(text)
    if command in EXIT_PHRASES:
        ui.show(f"Goodbye, {config.USER_NAME}.")
        return False
    if command in RESET_PHRASES:
        brain.reset()
        ui.show("Fresh start. What can I do for you?")
        return True

    log("YOU", text)
    console.print(f"[cyan]{config.THINKING_PHRASE}[/]")
    if ui.mouth:  # say it in the background so the request starts straight away
        threading.Thread(target=ui.mouth.say, args=(config.THINKING_PHRASE,), daemon=True).start()
    with console.status("[cyan]Working...", spinner="dots"):
        reply = brain.respond(text)
    ui.show(reply)
    return True


def strip_wake_word(text):
    """Returns the command spoken with the wake word, '' if only the wake word was said, or None if it wasn't said."""
    words = "|".join(map(re.escape, config.WAKE_WORDS))
    if not re.search(rf"\b({words})\b", text, re.IGNORECASE):
        return None
    command = re.sub(rf"\b(hey|okay|ok|hi|yo)?\s*\b({words})\b[\s,.!?]*", " ", text, flags=re.IGNORECASE)
    return command.strip(" ,.!?")


def text_mode(speak):
    mouth = None
    if speak:
        from jarvis.voice import Mouth
        mouth = Mouth()
    ui = Interface(mouth=mouth)
    tools.ui = ui
    tools.start_reminders()
    brain = Brain(mode="voice" if speak else "text", on_status=lambda s: console.print(f"  [dim]⚙ {s}[/]"))
    ui.show(greeting())
    console.print("[dim]Type a command. 'reset' starts a new conversation, 'exit' quits.[/]\n")
    while True:
        try:
            text = console.input("[bold green]You ›[/] ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if text and not think(brain, ui, text):
            break


def voice_mode():
    from jarvis.voice import Ears, Mouth
    mouth = Mouth()
    with console.status("[cyan]Calibrating microphone and loading speech model (first run downloads it)...", spinner="dots"):
        ears = Ears()
    ui = Interface(mouth=mouth, ears=ears)
    tools.ui = ui
    tools.start_reminders()
    brain = Brain(mode="voice", on_status=lambda s: console.print(f"  [dim]⚙ {s}[/]"))
    ui.show(greeting())
    console.print(f"[dim]Say \"{config.WAKE_WORDS[0].title()}, ...\" to give a command. Say \"goodbye\" to quit. Ctrl+C also quits.[/]\n")

    while True:
        console.print("[dim]🎙 listening for wake word...[/]")
        heard = ears.listen(phrase_limit=12)
        if not heard:
            continue
        command = strip_wake_word(heard)
        if command is None:
            continue
        console.print(f"[bold green]You ›[/] {heard}")
        if not command:
            mouth.say("Yes?")
            command = ears.listen(timeout=6)
            if not command:
                continue
            console.print(f"[bold green]You ›[/] {command}")

        # Conversation: after each answer, keep listening briefly for a follow-up without the wake word.
        while command:
            if not think(brain, ui, command):
                return
            console.print("[dim]🎙 listening for follow-up...[/]")
            command = ears.listen(timeout=config.FOLLOW_UP_SECONDS)
            if command:
                console.print(f"[bold green]You ›[/] {command}")
                if normalize(command) in END_FOLLOW_UP:
                    mouth.say("Very good.")
                    command = None


def open_hud(url):
    """Open the HUD as its own app window in Edge or Chrome (their voice recognition works; Opera's and Firefox's don't).
    Falls back to the default browser."""
    for path in (
        r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
        r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
        r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    ):
        exe = os.path.expandvars(path)
        if os.path.exists(exe):
            subprocess.Popen([exe, f"--app={url}", "--window-size=1600,900"])
            return
    webbrowser.open(url)


def hud_mode(port, open_browser):
    import qrcode
    import uvicorn
    from jarvis import server

    key = server.access_key()
    local_url = f"http://localhost:{port}/?key={key}"
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", port)) == 0:  # Jarvis is already running: just bring the window back
            console.print("[cyan]Jarvis is already running. Reopening the HUD window...[/]")
            open_hud(local_url)
            return
    phone_url = f"http://{server.lan_ip()}:{port}/?key={key}"
    console.print(f"\n[bold cyan]HUD online[/]  →  {local_url}")
    console.print(f"[bold cyan]Phone, same Wi-Fi[/]  →  {phone_url}")
    ts_ip = server.tailscale_ip()
    if ts_ip:
        phone_url = f"http://{ts_ip}:{port}/?key={key}"
        console.print(f"[bold cyan]Phone, anywhere (Tailscale)[/]  →  {phone_url}")
    console.print("[dim]Scan this with your phone's camera. Then use 'Add to Home Screen' to get a JARVIS app icon.[/]")
    qr = qrcode.QRCode(border=1)
    qr.add_data(phone_url)
    qr.print_ascii(invert=True)
    console.print("[dim]If Windows Firewall asks about Python, allow it on Private networks so your phone can connect.\n"
                  "Keep the access link private: anyone with it can control this PC. Ctrl+C to shut down.[/]\n")
    if open_browser:
        threading.Timer(1.5, open_hud, args=(local_url,)).start()
    uvicorn.run(server.app, host="0.0.0.0", port=port, log_level="warning")


def main():
    parser = argparse.ArgumentParser(description="JARVIS personal assistant")
    parser.add_argument("--text", action="store_true", help="type to Jarvis in the terminal")
    parser.add_argument("--speak", action="store_true", help="with --text: Jarvis speaks his replies")
    parser.add_argument("--voice", action="store_true", help="hands-free voice mode in the terminal")
    parser.add_argument("--port", type=int, default=8765, help="HUD port (default 8765)")
    parser.add_argument("--no-browser", action="store_true", help="don't open the HUD automatically")
    parser.add_argument("--connect-google", action="store_true", help="sign in to Gmail & Google Calendar")
    args = parser.parse_args()

    console.print(BANNER)
    if args.connect_google:
        from jarvis import google_tools
        console.print("[cyan]Opening Google sign-in in your browser...[/]")
        google_tools.connect()
        console.print("[bold green]Gmail and Google Calendar connected.[/]")
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        console.print("[bold red]No ANTHROPIC_API_KEY found.[/] Open the .env file and paste your key in "
                      "(get one at https://console.anthropic.com/settings/keys).")
        sys.exit(1)
    try:
        if args.voice:
            voice_mode()
        elif args.text or args.speak:
            text_mode(args.speak)
        else:
            hud_mode(args.port, not args.no_browser)
    except KeyboardInterrupt:
        pass
    console.print("[cyan]JARVIS offline.[/]")


if __name__ == "__main__":
    main()
