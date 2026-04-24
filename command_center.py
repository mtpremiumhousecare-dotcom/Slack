"""
Montana Premium House Care — Command Center
=============================================
Carolyn's single pane of glass. This module powers:

  1. Unified Feed (/feed) — One chronological stream of everything happening
  2. Smart Alerts — Proactive pings when something needs attention
  3. HCP Message Monitor — Pulls customer texts from HousecallPro scheduling line
  4. EOD Summary — Auto-posts end-of-day wrap-up at 5pm
  5. Quick Reply — Reply to HCP messages or texts from Slack

The goal: Carolyn never has to open another app. Everything comes to her in Slack.
"""

import os
import json
import time
import datetime
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN   = os.getenv("SLACK_BOT_TOKEN", "")
HCP_API_KEY       = os.getenv("HOUSECALLPRO_API_KEY", "")
HCP_BASE          = "https://api.housecallpro.com"
BUSINESS_NAME     = os.getenv("BUSINESS_NAME", "Montana Premium House Care")
CAROLYN_CHANNEL   = os.getenv("SLACK_CAROLYN_CHANNEL", "#carolyn")
ALERTS_CHANNEL    = os.getenv("SLACK_ALERTS_CHANNEL", "#alerts")

# ── Unified Event Log ────────────────────────────────────────────────────────
# Every event across all systems gets logged here for the /feed command
_event_log = []  # List of event dicts, newest first
_MAX_EVENTS = 200

def log_event(event_type: str, source: str, title: str, detail: str = "", icon: str = "📋", data: dict = None):
    """Log an event to the unified feed."""
    event = {
        "type":      event_type,   # lead, text, hcp_message, job, alert, system
        "source":    source,       # HCP, Twilio, Mailchimp, Bot, etc.
        "title":     title,
        "detail":    detail[:300],
        "icon":      icon,
        "data":      data or {},
        "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "read":      False,
    }
    _event_log.insert(0, event)
    if len(_event_log) > _MAX_EVENTS:
        _event_log.pop()
    return event

def get_feed(limit=15, event_type=None):
    """Get the unified feed, optionally filtered by type."""
    events = _event_log
    if event_type:
        events = [e for e in events if e["type"] == event_type]
    return events[:limit]

def get_unread_count():
    """Count unread events."""
    return sum(1 for e in _event_log if not e["read"])

def mark_all_read():
    """Mark all events as read."""
    for e in _event_log:
        e["read"] = True


# ─────────────────────────────────────────────────────────────────────────────
# HCP MESSAGE MONITOR — Customer texts from the scheduling line
# ─────────────────────────────────────────────────────────────────────────────

_hcp_last_message_check = None
_hcp_messages = []  # Store HCP messages for inbox view

def _hcp_headers():
    return {"Authorization": f"Token {HCP_API_KEY}", "Content-Type": "application/json"}

def fetch_hcp_messages():
    """
    Pull recent customer messages/conversations from HousecallPro.
    These are texts that come through HCP's scheduling line.
    """
    global _hcp_last_message_check
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return [], "HCP not configured"

    try:
        # HCP conversations endpoint
        r = requests.get(
            f"{HCP_BASE}/conversations",
            headers=_hcp_headers(),
            params={"page_size": 30},
            timeout=15,
        )
        if r.status_code != 200:
            return [], f"HCP messages error {r.status_code}"

        conversations = r.json().get("conversations", [])
        new_messages = []

        for conv in conversations:
            customer = conv.get("customer", {})
            last_msg = conv.get("last_message", {})
            msg_time = last_msg.get("created_at", "")

            # Only process messages newer than our last check
            if _hcp_last_message_check and msg_time and msg_time <= _hcp_last_message_check:
                continue

            # Only alert on incoming (customer-sent) messages
            if last_msg.get("direction", "").lower() in ("inbound", "incoming", "received"):
                msg = {
                    "source":         "HCP Scheduling",
                    "customer_name":  f"{customer.get('first_name','')} {customer.get('last_name','')}".strip() or "Customer",
                    "customer_phone": customer.get("mobile_number") or customer.get("home_number", "N/A"),
                    "customer_id":    str(customer.get("id", "")),
                    "body":           last_msg.get("body", last_msg.get("text", "")),
                    "conversation_id": str(conv.get("id", "")),
                    "timestamp":      msg_time[:16] if msg_time else "",
                    "read":           conv.get("read", False),
                }
                new_messages.append(msg)
                _hcp_messages.insert(0, msg)

        # Update last check time
        _hcp_last_message_check = datetime.datetime.utcnow().isoformat()

        # Keep store manageable
        if len(_hcp_messages) > 200:
            _hcp_messages[200:] = []

        return new_messages, None

    except Exception as e:
        return [], f"HCP messages error: {str(e)}"


def get_hcp_messages(limit=15, unread_only=False):
    """Get stored HCP messages."""
    msgs = _hcp_messages
    if unread_only:
        msgs = [m for m in msgs if not m.get("read", False)]
    return msgs[:limit]


def _post_hcp_message_to_slack(msg: dict):
    """Post an HCP customer message to Slack."""
    if not SLACK_BOT_TOKEN:
        return

    name = msg.get("customer_name", "Customer")
    phone = msg.get("customer_phone", "N/A")
    body = msg.get("body", "")
    timestamp = msg.get("timestamp", "")

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "💬 HCP Customer Message"}},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": f"_From {name} ({phone}) via HCP Scheduling • {timestamp}_"}
        ]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{name}:*\n>{body}"}},
        {"type": "actions", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "💬 Reply in HCP"},
                "style": "primary",
                "value": msg.get("conversation_id", ""),
                "action_id": "reply_hcp_message",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📞 Call"},
                "value": phone,
                "action_id": "call_customer",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Handled"},
                "value": msg.get("conversation_id", ""),
                "action_id": "mark_hcp_handled",
            },
        ]},
    ]

    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": CAROLYN_CHANNEL, "blocks": blocks},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# SMART ALERTS ENGINE — Proactive pings for Carolyn
# ─────────────────────────────────────────────────────────────────────────────

def check_smart_alerts():
    """
    Run all alert checks and return a list of alerts that need attention.
    Called by the background loop every 10 minutes.
    """
    alerts = []

    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return alerts

    # 1. Unresponded leads (sitting > 30 min)
    try:
        r = requests.get(
            f"{HCP_BASE}/leads",
            headers=_hcp_headers(),
            params={"page_size": 20},
            timeout=15,
        )
        if r.status_code == 200:
            for lead in r.json().get("leads", []):
                created = lead.get("created_at", "")
                stage = lead.get("lead_stage", {}).get("name", "").lower()
                if stage in ("new", "uncontacted", ""):
                    if created:
                        try:
                            created_dt = datetime.datetime.fromisoformat(created.replace("Z", "+00:00"))
                            age_min = (datetime.datetime.now(datetime.timezone.utc) - created_dt).total_seconds() / 60
                            if age_min > 30:
                                customer = lead.get("customer", {})
                                name = f"{customer.get('first_name','')} {customer.get('last_name','')}".strip()
                                source = lead.get("source", "Unknown")
                                alerts.append({
                                    "type":    "stale_lead",
                                    "icon":    "🚨",
                                    "title":   f"Lead waiting {int(age_min)} min — {name}",
                                    "detail":  f"From {source}. No response yet. Consider calling or texting now.",
                                    "action":  f"Phone: {customer.get('mobile_number', 'N/A')}",
                                    "urgency": "high",
                                })
                        except Exception:
                            pass
    except Exception:
        pass

    # 2. Estimates about to expire (within 48 hours)
    try:
        r = requests.get(
            f"{HCP_BASE}/estimates",
            headers=_hcp_headers(),
            params={"page_size": 30},
            timeout=15,
        )
        if r.status_code == 200:
            for est in r.json().get("estimates", []):
                if est.get("status") not in ("pending", "sent"):
                    continue
                expires = est.get("expiration_date") or est.get("valid_until", "")
                if expires:
                    try:
                        exp_dt = datetime.datetime.fromisoformat(expires.replace("Z", "+00:00"))
                        hours_left = (exp_dt - datetime.datetime.now(datetime.timezone.utc)).total_seconds() / 3600
                        if 0 < hours_left < 48:
                            customer = est.get("customer", {})
                            name = f"{customer.get('first_name','')} {customer.get('last_name','')}".strip()
                            alerts.append({
                                "type":    "expiring_estimate",
                                "icon":    "⏰",
                                "title":   f"Estimate expiring in {int(hours_left)}h — {name}",
                                "detail":  f"${est.get('total_amount', '?')} estimate. Follow up before it expires.",
                                "action":  f"Phone: {customer.get('mobile_number', 'N/A')}",
                                "urgency": "medium",
                            })
                    except Exception:
                        pass
    except Exception:
        pass

    # 3. Tomorrow's jobs not confirmed
    try:
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        r = requests.get(
            f"{HCP_BASE}/jobs",
            headers=_hcp_headers(),
            params={"page_size": 30, "scheduled_start_min": tomorrow + "T00:00:00Z", "scheduled_start_max": tomorrow + "T23:59:59Z"},
            timeout=15,
        )
        if r.status_code == 200:
            for job in r.json().get("jobs", []):
                if job.get("work_status", "").lower() not in ("confirmed",):
                    customer = job.get("customer", {})
                    name = f"{customer.get('first_name','')} {customer.get('last_name','')}".strip()
                    sched = job.get("schedule", {})
                    start_time = sched.get("scheduled_start", "")[:16] if sched.get("scheduled_start") else "TBD"
                    alerts.append({
                        "type":    "unconfirmed_job",
                        "icon":    "📋",
                        "title":   f"Tomorrow's job not confirmed — {name}",
                        "detail":  f"Scheduled {start_time}. Confirm with customer.",
                        "action":  f"Phone: {customer.get('mobile_number', 'N/A')}",
                        "urgency": "medium",
                    })
    except Exception:
        pass

    return alerts


def _post_alert_to_slack(alert: dict):
    """Post a smart alert to Carolyn's channel."""
    if not SLACK_BOT_TOKEN:
        return

    urgency_color = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(alert.get("urgency", "medium"), "🟡")

    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"{alert['icon']} {urgency_color} *{alert['title']}*\n{alert['detail']}"}},
    ]
    if alert.get("action"):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{alert['action']}_"}]})

    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": CAROLYN_CHANNEL, "blocks": blocks, "text": alert["title"]},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# EOD SUMMARY — Auto-posts at 5pm
# ─────────────────────────────────────────────────────────────────────────────

def build_eod_summary() -> dict:
    """Build end-of-day summary data from HCP."""
    summary = {
        "jobs_completed": 0,
        "jobs_scheduled_tomorrow": 0,
        "new_leads_today": 0,
        "open_estimates": 0,
        "texts_received": 0,
        "unresolved_items": [],
    }

    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return summary

    today = datetime.date.today().isoformat()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()

    # Jobs completed today
    try:
        r = requests.get(
            f"{HCP_BASE}/jobs",
            headers=_hcp_headers(),
            params={"page_size": 50, "work_status": "completed"},
            timeout=15,
        )
        if r.status_code == 200:
            jobs = r.json().get("jobs", [])
            summary["jobs_completed"] = sum(
                1 for j in jobs
                if (j.get("completed_at") or j.get("updated_at") or "")[:10] == today
            )
    except Exception:
        pass

    # Jobs scheduled tomorrow
    try:
        r = requests.get(
            f"{HCP_BASE}/jobs",
            headers=_hcp_headers(),
            params={"page_size": 50, "scheduled_start_min": tomorrow + "T00:00:00Z", "scheduled_start_max": tomorrow + "T23:59:59Z"},
            timeout=15,
        )
        if r.status_code == 200:
            summary["jobs_scheduled_tomorrow"] = len(r.json().get("jobs", []))
    except Exception:
        pass

    # New leads today
    try:
        r = requests.get(
            f"{HCP_BASE}/leads",
            headers=_hcp_headers(),
            params={"page_size": 50},
            timeout=15,
        )
        if r.status_code == 200:
            summary["new_leads_today"] = sum(
                1 for l in r.json().get("leads", [])
                if (l.get("created_at") or "")[:10] == today
            )
    except Exception:
        pass

    # Open estimates
    try:
        r = requests.get(
            f"{HCP_BASE}/estimates",
            headers=_hcp_headers(),
            params={"page_size": 50},
            timeout=15,
        )
        if r.status_code == 200:
            summary["open_estimates"] = sum(
                1 for e in r.json().get("estimates", [])
                if e.get("status") in ("pending", "sent")
            )
    except Exception:
        pass

    # Texts received today (from our store)
    summary["texts_received"] = sum(
        1 for e in _event_log
        if e["type"] in ("text", "hcp_message") and e["timestamp"][:10] == today
    )

    # Unresolved items
    unresolved = [e for e in _event_log if not e["read"] and e["type"] in ("lead", "text", "hcp_message", "alert")]
    summary["unresolved_items"] = unresolved[:5]

    return summary


def post_eod_to_slack():
    """Post the end-of-day summary to Carolyn's channel."""
    if not SLACK_BOT_TOKEN:
        return

    s = build_eod_summary()
    tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A, %B %d")

    unresolved_text = ""
    if s["unresolved_items"]:
        items = [f"  • {e['icon']} {e['title']}" for e in s["unresolved_items"]]
        unresolved_text = "\n*Still needs attention:*\n" + "\n".join(items)
    else:
        unresolved_text = "\n✅ *Everything handled today — great work, Carolyn!*"

    text = f"""🌅 *End-of-Day Summary — {datetime.date.today().strftime('%A, %B %d')}*

📊 *Today's Numbers:*
  • Jobs completed: *{s['jobs_completed']}*
  • New leads: *{s['new_leads_today']}*
  • Texts/messages received: *{s['texts_received']}*
  • Open estimates: *{s['open_estimates']}*

📅 *Tomorrow ({tomorrow}):*
  • Jobs scheduled: *{s['jobs_scheduled_tomorrow']}*
{unresolved_text}

_Have a great evening! 🧹_"""

    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": CAROLYN_CHANNEL, "text": text},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND LOOP — Runs smart alerts, HCP messages, and EOD check
# ─────────────────────────────────────────────────────────────────────────────

_monitor_active = False
_last_eod_date = None  # Track if we've already posted EOD today
_alerted_keys = {}  # Deduplication: {alert_key: timestamp}
_ALERT_COOLDOWN = 3600  # Don't re-alert same item for 1 hour

def _monitor_loop(alert_interval=600, message_interval=300):
    """
    Background thread that runs:
      - Smart alerts check every 10 minutes
      - HCP message check every 5 minutes
      - EOD summary at 5pm local time
    """
    global _monitor_active, _last_eod_date
    _monitor_active = True
    last_alert_check = 0
    last_message_check = 0

    print("🧠 Command Center monitor started")
    print(f"   Smart alerts: every {alert_interval//60} min")
    print(f"   HCP messages: every {message_interval//60} min")
    print(f"   EOD summary:  5:00 PM daily")

    while _monitor_active:
        now = time.time()
        current_time = datetime.datetime.now()

        # Check HCP messages every 5 minutes
        if now - last_message_check >= message_interval:
            try:
                new_msgs, err = fetch_hcp_messages()
                if not err and new_msgs:
                    for msg in new_msgs:
                        _post_hcp_message_to_slack(msg)
                        log_event("hcp_message", "HCP Scheduling",
                                  f"Text from {msg['customer_name']}",
                                  msg.get("body", "")[:200],
                                  "💬", msg)
                    print(f"  💬 {len(new_msgs)} new HCP message(s)")
            except Exception as e:
                print(f"  ⚠️ HCP message check error: {e}")
            last_message_check = now

        # Check smart alerts every 10 minutes (with deduplication)
        if now - last_alert_check >= alert_interval:
            try:
                alerts = check_smart_alerts()
                new_alerts = []
                for alert in alerts:
                    alert_key = f"{alert['type']}_{alert['title'][:50]}"
                    last_alerted = _alerted_keys.get(alert_key, 0)
                    if now - last_alerted >= _ALERT_COOLDOWN:
                        _post_alert_to_slack(alert)
                        log_event("alert", "Smart Alerts", alert["title"], alert["detail"], alert["icon"])
                        _alerted_keys[alert_key] = now
                        new_alerts.append(alert)
                # Clean up old keys (older than 24 hours)
                cutoff = now - 86400
                _alerted_keys = {k: v for k, v in _alerted_keys.items() if v > cutoff}
                if new_alerts:
                    print(f"  🚨 {len(new_alerts)} new alert(s) ({len(alerts) - len(new_alerts)} suppressed)")
            except Exception as e:
                print(f"  ⚠️ Smart alerts error: {e}")
            last_alert_check = now

        # EOD summary at 5pm (17:00)
        if current_time.hour == 17 and current_time.minute < 10:
            today = datetime.date.today()
            if _last_eod_date != today:
                try:
                    post_eod_to_slack()
                    _last_eod_date = today
                    log_event("system", "Bot", "EOD Summary posted", "", "🌅")
                    print("  🌅 EOD summary posted")
                except Exception as e:
                    print(f"  ⚠️ EOD summary error: {e}")

        time.sleep(60)  # Check every minute for timing accuracy


def start_monitor():
    """Start the command center background monitor."""
    t = threading.Thread(target=_monitor_loop, daemon=True)
    t.start()
    return t

def stop_monitor():
    global _monitor_active
    _monitor_active = False


# ─────────────────────────────────────────────────────────────────────────────
# QUICK REPLY — Reply to HCP conversations from Slack
# ─────────────────────────────────────────────────────────────────────────────

def reply_hcp_message(conversation_id: str, message_body: str) -> dict:
    """Send a reply to an HCP conversation from Slack."""
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return {"success": False, "error": "HCP not configured"}

    try:
        r = requests.post(
            f"{HCP_BASE}/conversations/{conversation_id}/messages",
            headers=_hcp_headers(),
            json={"body": message_body},
            timeout=15,
        )
        if r.status_code in (200, 201):
            return {"success": True, "error": ""}
        else:
            return {"success": False, "error": f"HCP error {r.status_code}: {r.text[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
