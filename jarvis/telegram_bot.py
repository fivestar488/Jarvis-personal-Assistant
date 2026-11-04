"""Telegram: talk to Jarvis from anywhere through your own private Telegram bot, and get his alerts there too.

Setup: create a bot with @BotFather, put its token in .env as JARVIS_TELEGRAM_TOKEN and restart Jarvis. The console
shows a pairing code: send "/pair <code>" to your bot. From then on the bot only answers you (it remembers your
Telegram user id) and ignores everyone else. Approval pop-ups arrive as Allow / Deny buttons.
"""
import json
import secrets
import threading
import time

import requests

from . import config

API = "https://api.telegram.org/bot{token}/{method}"
OWNER_FILE = config.DATA_DIR / "telegram_owner.json"
MAX_PAIRING_TRIES = 5  # wrong codes before pairing locks until Jarvis restarts

pairing_code = None
_tries = 0
_on_message = None   # fn(text) -> reply, set by the server
_on_answer = None    # fn(confirm_id, allowed), set by the server
_confirm_messages = {}  # confirm id -> Telegram message id, so the buttons can be removed once it's answered
_thread = None


def enabled():
    return bool(config.TELEGRAM_TOKEN)


def owner():
    try:
        return json.loads(OWNER_FILE.read_text())["user_id"]
    except (FileNotFoundError, ValueError, KeyError):
        return None


def _call(method, timeout=15, files=None, **params):
    url = API.format(token=config.TELEGRAM_TOKEN, method=method)
    if files:
        r = requests.post(url, data=params, files=files, timeout=timeout)
    else:
        r = requests.post(url, json=params, timeout=timeout)
    return r.json()


def send(text, chat_id=None):
    """A message to you (split to fit Telegram's 4096-character limit)."""
    chat_id = chat_id or owner()
    if not (enabled() and chat_id):
        return
    for i in range(0, max(len(text), 1), 4000):
        _call("sendMessage", chat_id=chat_id, text=text[i:i + 4000] or "(empty)")


def alert(title, message, image_path=None):
    """Called by notify.alert: reminders, important emails, meeting briefs and security alerts, with the photo."""
    chat_id = owner()
    if not (enabled() and chat_id):
        return
    try:
        if image_path:
            with open(image_path, "rb") as f:
                _call("sendPhoto", timeout=60, files={"photo": f}, chat_id=chat_id, caption=f"{title}: {message}"[:1000])
        else:
            send(f"🔔 {title}\n{message}", chat_id)
    except Exception:
        pass


def ask_confirm(confirm_id, question):
    """An approval request with Allow / Deny buttons."""
    chat_id = owner()
    if not (enabled() and chat_id):
        return
    try:
        r = _call("sendMessage", chat_id=chat_id, text=f"⚠️ Authorization required\n{question}",
                  reply_markup={"inline_keyboard": [[{"text": "✅ Allow", "callback_data": f"ok:{confirm_id}"},
                                                     {"text": "❌ Deny", "callback_data": f"no:{confirm_id}"}]]})
        _confirm_messages[confirm_id] = r["result"]["message_id"]
    except Exception:
        pass


def confirm_done(confirm_id):
    """The request was answered (here, on the PC, or it timed out): remove its buttons."""
    message_id = _confirm_messages.pop(confirm_id, None)
    if message_id and owner():
        try:
            _call("editMessageReplyMarkup", chat_id=owner(), message_id=message_id, reply_markup={"inline_keyboard": []})
        except Exception:
            pass


HELP = ("I'm J.A.R.V.I.S. Send me anything you'd say to me on the PC, for example \"what's on my calendar today?\", "
        "\"any important emails?\" or \"remind me at 6pm to call mum\". Alerts and approval requests come here too.")


def _handle(update):
    global _tries, pairing_code
    me = owner()
    if "callback_query" in update:  # an Allow / Deny button
        q = update["callback_query"]
        if me and q["from"]["id"] == me and q.get("data", "")[:3] in ("ok:", "no:"):
            allowed = q["data"].startswith("ok:")
            _on_answer and _on_answer(q["data"][3:], allowed)
            _call("answerCallbackQuery", callback_query_id=q["id"], text="Allowed" if allowed else "Denied")
        return
    m = update.get("message") or {}
    chat, user, text = m.get("chat", {}), m.get("from", {}), (m.get("text") or "").strip()
    if chat.get("type") != "private":
        return  # never answer in groups
    if not me:
        if pairing_code and text in (f"/pair {pairing_code}", f"/start {pairing_code}"):
            OWNER_FILE.write_text(json.dumps({"user_id": user["id"], "name": user.get("first_name", "")}))
            pairing_code = None
            send("Paired. This bot now answers only you. " + HELP, chat["id"])
            print(f"\n  Telegram paired with {user.get('first_name', 'you')}.")
        elif text.startswith(("/pair", "/start")) and pairing_code:
            _tries += 1
            if _tries >= MAX_PAIRING_TRIES:
                pairing_code = None
                print("\n  Telegram: too many wrong pairing codes, pairing is locked until Jarvis restarts.")
            send("That code isn't right. Send /pair followed by the code shown in Jarvis's console window.", chat["id"])
        return
    if user.get("id") != me:
        return  # someone else found the bot: ignore them
    if text in ("/start", "/help"):
        send(HELP)
    elif text:
        def reply():
            _call("sendChatAction", chat_id=me, action="typing")
            try:
                send(_on_message(text))
            except Exception as e:
                send(f"Something went wrong: {e}")
        threading.Thread(target=reply, daemon=True).start()
    else:
        send("I can only read text messages for now.")


def _poll():
    offset = None
    while True:
        try:
            r = _call("getUpdates", timeout=60, offset=offset, allowed_updates=["message", "callback_query"])
            if not r.get("ok"):
                if r.get("error_code") == 401:
                    print("\n  Telegram: the bot token in .env (JARVIS_TELEGRAM_TOKEN) was rejected.")
                    return
                time.sleep(10)
                continue
            for update in r["result"]:
                offset = update["update_id"] + 1
                try:
                    _handle(update)
                except Exception:
                    pass
        except Exception:
            time.sleep(10)  # no internet: try again


def start(on_message, on_answer):
    """Start listening for your messages. on_message(text) -> reply runs a command, on_answer(id, allowed) answers
    an approval request."""
    global _thread, _on_message, _on_answer, pairing_code
    if _thread or not enabled():
        return
    _on_message, _on_answer = on_message, on_answer
    if not owner():
        pairing_code = f"{secrets.randbelow(1_000_000):06d}"
        print(f"\n  Telegram: send  /pair {pairing_code}  to your bot to connect it to Jarvis.")
    _thread = threading.Thread(target=_poll, daemon=True)
    _thread.start()
