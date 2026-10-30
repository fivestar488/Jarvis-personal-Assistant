"""Alerts: Jarvis says it out loud on the PC and sends it to your phone as a notification.

Phone notifications use standard web push: your phone's JARVIS app subscribes once (the ALERTS button),
and alerts are delivered through Google's push service, so they arrive even when Tailscale is off or the
app is closed. Tapping one opens JARVIS (which needs Tailscale on).
"""
import base64
import json
import threading

from . import config

VAPID_KEY_FILE = config.DATA_DIR / "push_vapid.pem"
SUBSCRIPTIONS_FILE = config.DATA_DIR / "push_subscriptions.json"
_lock = threading.Lock()

# Set by the server: the phone app's secure address, so notifications can show pictures (security photos).
public_base_url = None


def alert(title, message, image_path=None, speak=True):
    """Tell the user something everywhere: announced in the HUD / voice, and pushed to their phone."""
    from . import tools
    if speak and tools.ui:
        tools.ui.announce(message)
    image_url = None
    if image_path and public_base_url:
        from .server import access_key
        image_url = f"{public_base_url}/api/snapshot/{image_path.name}?key={access_key()}"
    threading.Thread(target=push, args=(title, message, image_url), daemon=True).start()


# ---------------------------------------------------------------- web push

def _private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if not VAPID_KEY_FILE.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        VAPID_KEY_FILE.write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return serialization.load_pem_private_key(VAPID_KEY_FILE.read_bytes(), password=None)


def public_key():
    """The key phones need to subscribe (identifies this Jarvis to the push service)."""
    from cryptography.hazmat.primitives import serialization
    raw = _private_key().public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _load():
    return json.loads(SUBSCRIPTIONS_FILE.read_text()) if SUBSCRIPTIONS_FILE.exists() else []


def subscribe(subscription):
    with _lock:
        subs = [s for s in _load() if s.get("endpoint") != subscription.get("endpoint")]
        SUBSCRIPTIONS_FILE.write_text(json.dumps(subs + [subscription], indent=2))


def unsubscribe(endpoint):
    with _lock:
        SUBSCRIPTIONS_FILE.write_text(json.dumps([s for s in _load() if s.get("endpoint") != endpoint], indent=2))


def push(title, message, image_url=None):
    from pywebpush import WebPushException, webpush
    _private_key()  # make sure the key exists
    payload = json.dumps({"title": title, "body": message, "image": image_url})
    for sub in _load():
        try:
            webpush(subscription_info=sub, data=payload, vapid_private_key=str(VAPID_KEY_FILE),
                    vapid_claims={"sub": "mailto:jarvis@example.com"}, ttl=3600)
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                unsubscribe(sub.get("endpoint"))  # the phone uninstalled the app or turned alerts off
        except Exception:
            pass
