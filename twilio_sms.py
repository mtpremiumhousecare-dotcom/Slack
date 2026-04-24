"""
Montana Premium House Care — Twilio SMS Module
================================================
Handles all SMS communication through the business line (406-599-2699)
via Twilio, so Carolyn can send and receive texts entirely from Slack.

Features:
  - Receive incoming texts → post to Slack with reply button
  - Send outgoing texts from Slack via /text send command
  - Inbox view of recent conversations
  - Webhook endpoint for real-time incoming SMS (runs on Flask)

Architecture:
  - Incoming: Twilio webhook → Flask endpoint → Slack alert
  - Outgoing: Slack /text command → Twilio API → customer phone
  - All messages logged in-memory for /text inbox
"""

import os
import json
import datetime
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER  = os.getenv("TWILIO_PHONE_NUMBER", "")  # +14065992699 format

SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_SMS_CHANNEL   = os.getenv("SLACK_SMS_CHANNEL", "#customers")

BUSINESS_NAME       = os.getenv("BUSINESS_NAME", "Montana Premium House Care")
OFFICE_ASSISTANT    = "Carolyn Donaldson"

# ── Message Store ─────────────────────────────────────────────────────────────
_message_store = []  # List of message dicts, newest first
_conversations = {}  # { phone_number: [messages] } for threaded view

def _store_message(msg):
    """Store a message and index by phone number."""
    msg["timestamp"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    _message_store.insert(0, msg)
    # Keep last 500 messages in memory
    if len(_message_store) > 500:
        _message_store.pop()
    # Index by phone
    phone = msg.get("customer_phone", "unknown")
    if phone not in _conversations:
        _conversations[phone] = []
    _conversations[phone].insert(0, msg)


# ─────────────────────────────────────────────────────────────────────────────
# SEND SMS (Outgoing — Carolyn sends from Slack)
# ─────────────────────────────────────────────────────────────────────────────

def send_sms(to_number: str, message_body: str) -> dict:
    """
    Send an SMS via Twilio from the business number.
    Returns: {"success": bool, "sid": str, "error": str}
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_PHONE_NUMBER:
        return {"success": False, "sid": "", "error": "Twilio not configured. Add TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_PHONE_NUMBER to .env"}

    # Normalize phone number
    to_clean = to_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not to_clean.startswith("+"):
        if not to_clean.startswith("1"):
            to_clean = "1" + to_clean
        to_clean = "+" + to_clean

    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "To": to_clean,
                "From": TWILIO_PHONE_NUMBER,
                "Body": message_body,
            },
            timeout=15,
        )
        data = r.json()
        if r.status_code in (200, 201):
            # Store outgoing message
            _store_message({
                "direction":      "outgoing",
                "customer_phone": to_clean,
                "body":           message_body,
                "sid":            data.get("sid", ""),
                "status":         data.get("status", "sent"),
            })
            return {"success": True, "sid": data.get("sid", ""), "error": ""}
        else:
            return {"success": False, "sid": "", "error": data.get("message", f"Twilio error {r.status_code}")}
    except Exception as e:
        return {"success": False, "sid": "", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# RECEIVE SMS (Incoming — Twilio webhook posts here)
# ─────────────────────────────────────────────────────────────────────────────

def handle_incoming_sms(form_data: dict) -> dict:
    """
    Process an incoming SMS from Twilio webhook.
    Called by the webhook server when Twilio POSTs to /sms.
    Returns the stored message dict.
    """
    from_number = form_data.get("From", "Unknown")
    body = form_data.get("Body", "")
    sms_sid = form_data.get("MessageSid", "")

    msg = {
        "direction":      "incoming",
        "customer_phone": from_number,
        "body":           body,
        "sid":            sms_sid,
        "status":         "received",
    }
    _store_message(msg)

    # Post to Slack immediately
    _post_sms_to_slack(msg)

    return msg


def _post_sms_to_slack(msg: dict):
    """Post an incoming text message to Slack with reply button."""
    if not SLACK_BOT_TOKEN:
        return

    phone = msg.get("customer_phone", "Unknown")
    body = msg.get("body", "")
    timestamp = msg.get("timestamp", "")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📱 Incoming Text Message"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"_From {phone} • {timestamp} • For {OFFICE_ASSISTANT}_"}
        ]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*From:* {phone}\n\n>{body}"}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "💬 Reply"},
                "style": "primary",
                "value": phone,
                "action_id": "reply_sms",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📞 Call Back"},
                "value": phone,
                "action_id": "call_customer",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Handled"},
                "value": msg.get("sid", ""),
                "action_id": "mark_sms_handled",
            },
        ]},
    ]

    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": SLACK_SMS_CHANNEL, "blocks": blocks},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# INBOX & CONVERSATION VIEW
# ─────────────────────────────────────────────────────────────────────────────

def get_inbox(limit=15):
    """Get the most recent messages (both directions)."""
    return _message_store[:limit]

def get_conversation(phone_number: str, limit=10):
    """Get the conversation thread with a specific number."""
    clean = phone_number.strip().replace("-", "").replace("(", "").replace(")", "").replace(" ", "")
    if not clean.startswith("+"):
        if not clean.startswith("1"):
            clean = "1" + clean
        clean = "+" + clean
    return _conversations.get(clean, [])[:limit]

def get_unread_count():
    """Count incoming messages that haven't been replied to."""
    # Group by phone, check if last message is incoming (no reply yet)
    unread = 0
    for phone, msgs in _conversations.items():
        if msgs and msgs[0].get("direction") == "incoming":
            unread += 1
    return unread


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK SERVER (Flask — receives Twilio POST for incoming SMS)
# ─────────────────────────────────────────────────────────────────────────────

def start_webhook_server(port=5050):
    """Start a lightweight Flask server to receive Twilio SMS webhooks."""
    try:
        from flask import Flask, request as flask_request
    except ImportError:
        print("⚠️  Flask not installed — Twilio webhook server disabled. Run: pip install flask")
        return None

    app = Flask(__name__)

    @app.route("/sms", methods=["POST"])
    def sms_webhook():
        """Twilio sends incoming SMS here."""
        handle_incoming_sms(flask_request.form.to_dict())
        # Return TwiML empty response (don't auto-reply — Carolyn decides)
        return '<?xml version="1.0" encoding="UTF-8"?><Response></Response>', 200, {"Content-Type": "text/xml"}

    @app.route("/sms/status", methods=["POST"])
    def sms_status():
        """Twilio sends delivery status updates here."""
        # Optional: track delivery status
        return "", 200

    @app.route("/health", methods=["GET"])
    def health():
        return json.dumps({"status": "ok", "service": "twilio-sms-webhook"}), 200

    def _run():
        app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    print(f"📱 Twilio SMS webhook server running on port {port}")
    return t


# ─────────────────────────────────────────────────────────────────────────────
# STATUS CHECK
# ─────────────────────────────────────────────────────────────────────────────

def get_twilio_status():
    """Return Twilio configuration status."""
    configured = bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER)
    return {
        "configured":   configured,
        "phone_number": TWILIO_PHONE_NUMBER if configured else "Not configured",
        "messages_stored": len(_message_store),
        "active_conversations": len(_conversations),
        "unread": get_unread_count(),
    }
