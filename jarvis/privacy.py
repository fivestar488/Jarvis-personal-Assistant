"""Hides secrets before they leave the PC or get saved: card numbers, passwords, API keys, tokens and private keys
are blanked out of tool results (files, clipboard, emails, web pages), long-term memory, the saved conversation
and the background jobs' email checks. What you say to Jarvis yourself still goes through as you said it.
JARVIS_REDACT=off in .env turns it off."""
import re

from . import config


def _luhn(digits):
    """Card numbers pass the Luhn checksum; most other long numbers (orders, tracking) don't."""
    total, odd = 0, False
    for d in reversed(digits):
        n = int(d)
        if odd:
            n = n * 2 - 9 if n > 4 else n * 2
        total, odd = total + n, not odd
    return total % 10 == 0


def _card(m):
    digits = re.sub(r"\D", "", m.group(0))
    return "[card number hidden]" if 13 <= len(digits) <= 19 and _luhn(digits) else m.group(0)


def _labelled(m):
    """'password: hunter2' -> 'password: [hidden]'. Plain words after the label ('password is required') stay."""
    value = m.group(3)
    if value.startswith("["):  # already hidden by a more specific pattern
        return m.group(0)
    looks_secret = re.search(r"[\d\W_]", value) or re.search(r"[A-Z]", value[1:]) or len(value) >= 12
    return m.group(1) + m.group(2) + "[hidden]" if looks_secret else m.group(0)


PATTERNS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----"), "[private key hidden]"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}"), "[API key hidden]"),
    (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_\-]{20,}"), "[API key hidden]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[API key hidden]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"), "[token hidden]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[token hidden]"),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), "[API key hidden]"),
    (re.compile(r"\b\d{8,10}:AA[0-9A-Za-z_\-]{30,}\b"), "[bot token hidden]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[token hidden]"),  # JWTs
    (re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])"), _card),
    (re.compile(r"(?i)\b(password|passcode|passwd|pwd|pin code|pin|secret|api[ _-]?key|access token|token)"
                r"(\s*(?:is|=|:)\s*)(\S+)"), _labelled),
]


def redact(text):
    if not isinstance(text, str) or not config.REDACT or not text:
        return text
    for pattern, repl in PATTERNS:
        text = pattern.sub(repl, text)
    return text


def redact_content(content):
    """A tool result: plain text, or a list of blocks (text and images); only the text is changed."""
    if isinstance(content, str):
        return redact(content)
    if isinstance(content, list):
        return [{**b, "text": redact(b["text"])} if isinstance(b, dict) and b.get("type") == "text" else b
                for b in content]
    return content
