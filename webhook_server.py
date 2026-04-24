"""
Montana Premium House Care — Webhook Server
=============================================
Receives inbound leads from Angi (and future webhook-based platforms).
Runs alongside bot.py on a separate port.

Run:  python3 webhook_server.py
Port: 5050 (configurable via WEBHOOK_PORT env var)
"""

import os
import hmac
import hashlib
import json
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

ANGI_WEBHOOK_SECRET = os.getenv("ANGI_WEBHOOK_SECRET", "")
WEBHOOK_PORT        = int(os.getenv("WEBHOOK_PORT", "5050"))

# Import the lead monitor's ingest function
try:
    from lead_monitor import ingest_angi_lead, post_lead_to_slack
except ImportError:
    def ingest_angi_lead(payload):
        return payload, True
    def post_lead_to_slack(lead, channel=None):
        pass


def verify_angi_signature(payload_body: bytes, signature: str) -> bool:
    """Verify Angi webhook signature if secret is configured."""
    if not ANGI_WEBHOOK_SECRET:
        return True  # No secret = accept all (for testing)
    expected = hmac.new(
        ANGI_WEBHOOK_SECRET.encode(), payload_body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "service": "Montana Premium House Care Webhook Server"})


@app.route("/webhooks/angi", methods=["POST"])
def angi_webhook():
    """Receive leads from Angi's JSON lead feed."""
    # Verify signature if configured
    sig = request.headers.get("X-Angi-Signature", request.headers.get("X-Signature", ""))
    if ANGI_WEBHOOK_SECRET and not verify_angi_signature(request.data, sig):
        return jsonify({"error": "Invalid signature"}), 403

    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    lead, is_new = ingest_angi_lead(payload)

    if is_new:
        post_lead_to_slack(lead)
        print(f"🏠 New Angi lead: {lead.get('name', 'Unknown')} — {lead.get('service', 'Cleaning')}")

    return jsonify({"status": "received", "new": is_new, "lead_id": lead.get("id", "")}), 200


@app.route("/webhooks/thumbtack", methods=["POST"])
def thumbtack_webhook():
    """Receive leads from Thumbtack webhook (Zapier integration)."""
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    lead = {
        "platform":  "Thumbtack",
        "id":        str(payload.get("leadID", payload.get("id", ""))),
        "name":      payload.get("customerName", payload.get("name", "Thumbtack Lead")),
        "email":     payload.get("email", "N/A"),
        "phone":     payload.get("phone", "N/A"),
        "service":   payload.get("service", payload.get("category", "Cleaning")),
        "message":   payload.get("description", payload.get("request", "")),
        "timestamp": payload.get("createdAt", "")[:10] if payload.get("createdAt") else "",
        "source":    "Thumbtack Webhook",
        "icon":      "🔨",
    }

    from lead_monitor import _store_lead
    is_new = _store_lead(lead)
    if is_new:
        post_lead_to_slack(lead)
        print(f"🔨 New Thumbtack lead: {lead.get('name', 'Unknown')}")

    return jsonify({"status": "received", "new": is_new}), 200


@app.route("/webhooks/google", methods=["POST"])
def google_webhook():
    """Receive leads from Google Local Services Ads webhook."""
    try:
        payload = request.get_json(force=True)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400

    lead = {
        "platform":  "Google LSA",
        "id":        str(payload.get("leadId", payload.get("id", ""))),
        "name":      payload.get("consumerName", payload.get("name", "Google Lead")),
        "email":     payload.get("email", "N/A"),
        "phone":     payload.get("phoneNumber", payload.get("phone", "N/A")),
        "service":   payload.get("categoryId", payload.get("service", "Cleaning")),
        "message":   payload.get("note", payload.get("message", "")),
        "timestamp": payload.get("leadCreationTimestamp", "")[:10] if payload.get("leadCreationTimestamp") else "",
        "type":      payload.get("leadType", "CALL"),
        "source":    "Google LSA Webhook",
        "icon":      "🔍",
    }

    from lead_monitor import _store_lead
    is_new = _store_lead(lead)
    if is_new:
        post_lead_to_slack(lead)
        print(f"🔍 New Google LSA lead: {lead.get('name', 'Unknown')}")

    return jsonify({"status": "received", "new": is_new}), 200


if __name__ == "__main__":
    print(f"🌐 Webhook server starting on port {WEBHOOK_PORT}...")
    print(f"🏠 Angi webhook:     POST /webhooks/angi")
    print(f"🔨 Thumbtack webhook: POST /webhooks/thumbtack")
    print(f"🔍 Google webhook:    POST /webhooks/google")
    print(f"❤️  Health check:     GET  /health")
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False)
