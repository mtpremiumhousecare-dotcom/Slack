"""
Montana Premium House Care — Lead Monitor (v2)
===============================================
Pulls leads from:
  - HousecallPro (includes Thumbtack, Angi, Google leads that feed into HCP)
  - Mailchimp (email signups / quote requests)

All leads are unified into a single store and posted to Slack #leads channel.
Thumbtack, Angi, and Google leads are NOT polled separately — they all flow
through HousecallPro's pipeline, so we pull them from HCP.

Run standalone:  python3 lead_monitor.py
Or imported by:  bot.py
"""

import os
import json
import time
import hashlib
import datetime
import threading
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ───────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN   = os.getenv("SLACK_BOT_TOKEN", "")
LEADS_CHANNEL     = os.getenv("SLACK_LEAD_CHANNEL", "#leads")

HCP_API_KEY       = os.getenv("HOUSECALLPRO_API_KEY", "")
HCP_BASE          = "https://api.housecallpro.com"

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY", "")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID", "")

BUSINESS_NAME         = os.getenv("BUSINESS_NAME",  "Montana Premium House Care")
OFFICE_ASSISTANT_NAME = "Carolyn Donaldson"

# ── In-memory lead store ─────────────────────────────────────────────────────
_lead_store = {}   # { hash: lead_dict }
_last_hcp_poll = None  # Track last poll time for incremental fetching

def _lead_hash(platform, lead_id):
    return hashlib.md5(f"{platform}:{lead_id}".encode()).hexdigest()

def _store_lead(lead):
    """Store a lead if not already seen. Returns True if new."""
    h = _lead_hash(lead["platform"], lead["id"])
    if h not in _lead_store:
        lead["hash"]      = h
        lead["reviewed"]  = False
        lead["stored_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        _lead_store[h]    = lead
        return True
    return False

def get_all_leads(platform=None, unreviewed_only=False):
    leads = list(_lead_store.values())
    if platform:
        leads = [l for l in leads if l["platform"].lower() == platform.lower()]
    if unreviewed_only:
        leads = [l for l in leads if not l["reviewed"]]
    return sorted(leads, key=lambda x: x.get("stored_at", ""), reverse=True)

def mark_lead_reviewed(lead_hash):
    if lead_hash in _lead_store:
        _lead_store[lead_hash]["reviewed"] = True
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1 — HOUSECALLPRO (Thumbtack, Angi, Google all feed in here)
# ─────────────────────────────────────────────────────────────────────────────

def _hcp_headers():
    return {"Authorization": f"Token {HCP_API_KEY}", "Content-Type": "application/json"}

def fetch_hcp_leads():
    """
    Fetch leads from HousecallPro pipeline.
    HCP aggregates leads from Thumbtack, Angi, Google LSA, website, and phone.
    Each lead has a source field that tells us where it originated.
    """
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return [], "HousecallPro API key not configured."

    all_leads = []

    # 1. Pull from /leads endpoint (pipeline leads)
    try:
        r = requests.get(
            f"{HCP_BASE}/leads",
            headers=_hcp_headers(),
            params={"page_size": 50},
            timeout=15,
        )
        if r.status_code == 200:
            for l in r.json().get("leads", []):
                customer = l.get("customer", {})
                source = l.get("source", l.get("lead_source", "HousecallPro"))
                # Map HCP source names to friendly platform names
                platform = _map_hcp_source(source)
                icon = _source_icon(platform)

                lead = {
                    "platform":  platform,
                    "id":        str(l.get("id", "")),
                    "name":      f"{customer.get('first_name','')} {customer.get('last_name','')}".strip() or "HCP Lead",
                    "email":     customer.get("email", "N/A"),
                    "phone":     customer.get("mobile_number") or customer.get("home_number", "N/A"),
                    "service":   l.get("job_type", {}).get("name", "") or l.get("tags", "Cleaning"),
                    "source":    source,
                    "status":    l.get("lead_stage", {}).get("name", "New"),
                    "timestamp": (l.get("created_at") or "")[:10],
                    "icon":      icon,
                    "hcp_id":    str(l.get("id", "")),
                }
                all_leads.append(lead)
    except Exception as e:
        return [], f"HCP leads error: {str(e)}"

    # 2. Pull recent estimates (often from Thumbtack/Angi/Google)
    try:
        r = requests.get(
            f"{HCP_BASE}/estimates",
            headers=_hcp_headers(),
            params={"page_size": 50},
            timeout=15,
        )
        if r.status_code == 200:
            for e in r.json().get("estimates", []):
                if e.get("status") in ("approved", "converted_to_job"):
                    continue  # Already converted — not a lead anymore
                customer = e.get("customer", {})
                source = e.get("source", "Estimate")
                platform = _map_hcp_source(source)
                icon = _source_icon(platform)

                lead = {
                    "platform":  platform,
                    "id":        f"est-{e.get('id','')}",
                    "name":      f"{customer.get('first_name','')} {customer.get('last_name','')}".strip() or "Estimate Lead",
                    "email":     customer.get("email", "N/A"),
                    "phone":     customer.get("mobile_number") or customer.get("home_number", "N/A"),
                    "service":   e.get("line_items", [{}])[0].get("name", "Cleaning") if e.get("line_items") else "Cleaning",
                    "source":    source,
                    "status":    e.get("status", "pending"),
                    "amount":    e.get("total_amount", ""),
                    "timestamp": (e.get("created_at") or "")[:10],
                    "icon":      icon,
                    "hcp_id":    str(e.get("id", "")),
                }
                all_leads.append(lead)
    except Exception:
        pass  # Estimates are supplementary — don't fail the whole fetch

    return all_leads, None


def _map_hcp_source(source):
    """Map HousecallPro source strings to friendly platform names."""
    if not source:
        return "HousecallPro"
    s = source.lower()
    if "thumbtack" in s:
        return "Thumbtack"
    elif "angi" in s or "angie" in s or "homeadvisor" in s:
        return "Angi"
    elif "google" in s or "lsa" in s or "local service" in s:
        return "Google"
    elif "yelp" in s:
        return "Yelp"
    elif "facebook" in s or "fb" in s:
        return "Facebook"
    elif "website" in s or "web" in s:
        return "Website"
    elif "referral" in s:
        return "Referral"
    elif "phone" in s or "call" in s:
        return "Phone Call"
    else:
        return "HousecallPro"


def _source_icon(platform):
    """Return an icon for each lead source."""
    icons = {
        "Thumbtack":     "🔨",
        "Angi":          "🏠",
        "Google":        "🔍",
        "Yelp":          "⭐",
        "Facebook":      "📘",
        "Website":       "🌐",
        "Referral":      "🤝",
        "Phone Call":    "📞",
        "Mailchimp":     "📧",
        "HousecallPro":  "📋",
    }
    return icons.get(platform, "📋")


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 2 — MAILCHIMP (email signups)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_mailchimp_leads():
    """Fetch recent subscribers from Mailchimp audience."""
    if not MAILCHIMP_API_KEY or not MAILCHIMP_LIST_ID:
        return [], "Mailchimp not configured."

    dc = MAILCHIMP_API_KEY.split("-")[-1] if "-" in MAILCHIMP_API_KEY else "us1"
    base = f"https://{dc}.api.mailchimp.com/3.0"
    since = (datetime.datetime.utcnow() - datetime.timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+00:00")

    try:
        r = requests.get(
            f"{base}/lists/{MAILCHIMP_LIST_ID}/members",
            auth=("anystring", MAILCHIMP_API_KEY),
            params={"since_timestamp_opt": since, "count": 50, "status": "subscribed"},
            timeout=15,
        )
        if r.status_code != 200:
            return [], f"Mailchimp error {r.status_code}"

        leads = []
        for m in r.json().get("members", []):
            merge = m.get("merge_fields", {})
            lead = {
                "platform":  "Mailchimp",
                "id":        m.get("id", m.get("email_address")),
                "name":      f"{merge.get('FNAME','')} {merge.get('LNAME','')}".strip() or "New Subscriber",
                "email":     m.get("email_address", "N/A"),
                "phone":     merge.get("PHONE", merge.get("MPHONE", "N/A")),
                "source":    m.get("source", "Mailchimp Form"),
                "timestamp": (m.get("timestamp_opt") or "")[:10],
                "tags":      ", ".join([t["name"] for t in m.get("tags", [])]),
                "icon":      "📧",
            }
            leads.append(lead)
        return leads, None
    except Exception as e:
        return [], f"Mailchimp error: {str(e)}"


# ─────────────────────────────────────────────────────────────────────────────
# UNIFIED FETCHER
# ─────────────────────────────────────────────────────────────────────────────

PLATFORM_FETCHERS = {
    "HousecallPro": fetch_hcp_leads,
    "Mailchimp":    fetch_mailchimp_leads,
}

def fetch_all_leads():
    """Poll all sources and store new leads. Returns { source: (new_count, error) }."""
    results = {}
    for name, fetcher in PLATFORM_FETCHERS.items():
        try:
            leads, err = fetcher()
            if err:
                results[name] = (0, err)
                continue
            new_count = sum(1 for l in leads if _store_lead(l))
            results[name] = (new_count, None)
        except Exception as e:
            results[name] = (0, str(e))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# SLACK ALERT POSTER
# ─────────────────────────────────────────────────────────────────────────────

def post_lead_to_slack(lead: dict, channel: str = None):
    """Post a new lead alert to the Slack #leads channel."""
    if not SLACK_BOT_TOKEN:
        return

    ch = channel or LEADS_CHANNEL
    icon = lead.get("icon", "📋")
    platform = lead.get("platform", "Unknown")
    name = lead.get("name", "Unknown")
    email = lead.get("email", "N/A")
    phone = lead.get("phone", "N/A")
    service = lead.get("service", lead.get("tags", ""))
    message = (lead.get("message") or "")[:200]
    timestamp = lead.get("timestamp", "")
    source = lead.get("source", "")
    amount = lead.get("amount", "")

    fields = [
        {"type": "mrkdwn", "text": f"*Source:*\n{icon} {platform}" + (f" ({source})" if source and source != platform else "")},
        {"type": "mrkdwn", "text": f"*Name:*\n{name}"},
        {"type": "mrkdwn", "text": f"*Phone:*\n{phone}"},
        {"type": "mrkdwn", "text": f"*Email:*\n{email}"},
    ]
    if service:
        fields.append({"type": "mrkdwn", "text": f"*Service:*\n{service}"})
    if amount:
        fields.append({"type": "mrkdwn", "text": f"*Estimate:*\n${amount}"})

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"{icon} New Lead — {platform}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Received {timestamp} • For review by {OFFICE_ASSISTANT_NAME}_"}]},
        {"type": "divider"},
        {"type": "section", "fields": fields[:6]},
    ]
    if message:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*Message:*\n_{message}_"}})
    blocks.append({
        "type": "actions",
        "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Mark Reviewed"}, "style": "primary",
             "value": lead.get("hash", ""), "action_id": "mark_lead_reviewed"},
            {"type": "button", "text": {"type": "plain_text", "text": "📞 Call Now"},
             "value": phone, "action_id": "call_lead"},
            {"type": "button", "text": {"type": "plain_text", "text": "✉️ Draft Email"},
             "value": f"reengagement|{name.split()[0] if name else 'there'}", "action_id": "draft_lead_email"},
        ],
    })

    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json={"channel": ch, "blocks": blocks},
            timeout=10,
        )
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND POLLER
# ─────────────────────────────────────────────────────────────────────────────

_polling_active = False

def _poll_loop(interval_seconds=900):
    """Background thread: polls all sources every 15 minutes."""
    global _polling_active
    _polling_active = True
    print(f"🔄 Lead monitor polling started (every {interval_seconds//60} min)")
    while _polling_active:
        try:
            results = fetch_all_leads()
            for source, (new_count, err) in results.items():
                if err:
                    print(f"  ⚠️  {source}: {err}")
                elif new_count > 0:
                    print(f"  ✅ {source}: {new_count} new lead(s)")
                    new_leads = [l for l in get_all_leads(platform=None, unreviewed_only=True)][:new_count]
                    for lead in new_leads:
                        post_lead_to_slack(lead)
        except Exception as e:
            print(f"  ❌ Poll error: {e}")
        time.sleep(interval_seconds)

def start_polling(interval_seconds=900):
    t = threading.Thread(target=_poll_loop, args=(interval_seconds,), daemon=True)
    t.start()
    return t

def stop_polling():
    global _polling_active
    _polling_active = False


# ─────────────────────────────────────────────────────────────────────────────
# SUMMARY BUILDER
# ─────────────────────────────────────────────────────────────────────────────

def build_lead_summary():
    """Build a summary dict for the /leads summary command."""
    all_leads = get_all_leads()
    # Dynamically detect all platforms present
    platforms = list(set(l["platform"] for l in all_leads)) or ["HousecallPro", "Mailchimp"]
    summary = {
        "total":      len(all_leads),
        "unreviewed": len([l for l in all_leads if not l["reviewed"]]),
        "by_platform": {},
        "recent":     all_leads[:5],
    }
    for p in platforms:
        p_leads = [l for l in all_leads if l["platform"] == p]
        summary["by_platform"][p] = {
            "total":      len(p_leads),
            "unreviewed": len([l for l in p_leads if not l["reviewed"]]),
            "icon":       _source_icon(p),
        }
    return summary


if __name__ == "__main__":
    print(f"🔍 {BUSINESS_NAME} — Lead Monitor (v2)")
    print(f"📋 HousecallPro: {'✅' if HCP_API_KEY and HCP_API_KEY != 'your_housecallpro_api_key_here' else '⚠️  Not configured'}")
    print(f"📧 Mailchimp:    {'✅' if MAILCHIMP_API_KEY else '⚠️  Not configured'}")
    print(f"\n  Thumbtack, Angi, and Google leads are pulled through HousecallPro.")
    print("\nStarting polling loop (Ctrl+C to stop)...")
    start_polling(interval_seconds=900)
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        stop_polling()
        print("Stopped.")
