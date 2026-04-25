"""
Montana Premium House Care — Slack Bot (Full Edition v4)
=========================================================
Carolyn's single pane of glass. Everything in Slack, nothing else needed.

CONSOLIDATED COMMANDS (10 total — under Slack's 25 limit):

  /leads      — find | status | inbox | summary
  /job        — assign | list | checkin | checkout
  /customer   — new | followup | complete
  /hcp        — jobs | customers | leads | analysis
  /ai         — draft | complaint | recommend | status
  /service    — script | standards | qa | wow
  /office     — brief | priorities | feed | eod
  /carolyn    — meet | answer | profile | update | mood
  /announce   — Team broadcast
  /cleanhelp  — Full command reference

  NEW IN V4:
  - Unified feed: /office feed — one stream of everything happening
  - Smart proactive alerts — bot pings Carolyn when things need attention
  - HCP message monitor — customer texts from scheduling line appear in Slack
  - Twilio SMS — send/receive texts from business line in Slack
  - EOD summary — auto-posts at 5pm
  - Quick reply — reply to texts and HCP messages from Slack

Run:  python3 bot.py
"""

import os
import csv
import io
import json
import random
import datetime
import threading
import time
import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

# ── App init ──────────────────────────────────────────────────────────────────
app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)

BUSINESS_NAME  = os.getenv("BUSINESS_NAME",  "Montana Premium House Care")
OWNER_NAME     = os.getenv("OWNER_NAME",     "Chris Johnson")
BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "406-599-2699")
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "mtpremiumhousecare@gmail.com")
SERVICE_AREA   = os.getenv("SERVICE_AREA",   "Bozeman, Gallatin County, Livingston, Belgrade, Big Sky, Kalispell, Whitefish")
HCP_API_KEY    = os.getenv("HOUSECALLPRO_API_KEY", "")
HCP_BASE       = "https://api.housecallpro.com"

# ── Import sub-modules ────────────────────────────────────────────────────────
from ai_engine import (
    ai_draft_email, ai_score_lead, ai_handle_complaint,
    ai_summarize, ai_recommend, ai_morning_brief, get_ai_status,
)
from customer_service import (
    get_script, get_wow_moment, get_qa_checklist,
    format_recovery_protocol_for_slack, format_standards_for_slack,
    SCRIPTS, QA_CHECKLIST, WOW_MOMENTS,
)
from carolyn_profile import (
    load_profile, save_profile, update_preference, log_mood,
    get_current_question, process_interview_answer,
    format_profile_for_slack,
)
from lead_monitor import (
    fetch_all_leads as lm_fetch_all, get_all_leads as lm_get_all,
    mark_lead_reviewed, build_lead_summary, start_polling,
    post_lead_to_slack,
)
from command_center import (
    log_event, get_feed, get_unread_count as cc_unread_count,
    mark_all_read, fetch_hcp_messages, get_hcp_messages,
    check_smart_alerts, build_eod_summary, post_eod_to_slack,
    start_monitor as start_command_center, reply_hcp_message,
)
from twilio_sms import (
    send_sms, get_inbox as sms_inbox, get_conversation,
    get_unread_count as sms_unread_count, get_twilio_status,
    start_webhook_server,
)
from employee_profitability import (
    build_profitability_report, format_profitability_for_slack,
    set_pay_rate, get_pay_rate, get_all_pay_rates,
)
from proactive_scheduler import (
    start_proactive_scheduler, get_scheduler_status,
    run_morning_brief, run_eod_summary, run_email_drafts,
)
from email_automation import (
    queue_email, approve_email as ea_approve_email, skip_email as ea_skip_email,
    get_email_stats, send_via_mailchimp, get_email_prompt,
)
from bot_memory import (
    learn as mem_learn, forget as mem_forget, recall as mem_recall,
    get_context_for_ai, get_customer_context, should_skip_alert,
    get_memory_stats, format_memories_for_slack, CATEGORIES as MEM_CATEGORIES,
)
from chat_handler import build_chat_response, detect_intent
from ai_engine import _route_call as ai_route_call

# ── In-memory stores ─────────────────────────────────────────────────────────
jobs      = {}
customers = {}
leads_log = []

OFFICE_ASSISTANT_NAME = "Carolyn Donaldson"

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def next_id(prefix, store):
    return f"{prefix}-{len(store)+1:04d}"

def today():
    return datetime.date.today().strftime("%B %d, %Y")

def now_ts():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

def hcp_headers():
    return {"Authorization": f"Token {HCP_API_KEY}", "Content-Type": "application/json"}

def hcp_get(path, params=None):
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return None, "HousecallPro API key not configured. Add it to your .env file."
    try:
        r = requests.get(f"{HCP_BASE}{path}", headers=hcp_headers(), params=params, timeout=15)
        if r.status_code == 200:
            return r.json(), None
        return None, f"HCP API error {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return None, f"Connection error: {str(e)}"

def parse_sub(text):
    """Parse subcommand and remaining args from command text."""
    parts = text.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1] if len(parts) > 1 else ""
    return sub, rest


# ─────────────────────────────────────────────────────────────────────────────
# LEAD DATABASE — Multi-city, all service types
# ─────────────────────────────────────────────────────────────────────────────

LEADS_DB = {
    "residential": [
        {"name": "Haymaker Apartments",              "address": "1624 W Babcock St, Bozeman, MT 59715",        "phone": "(406) 219-3190",  "city": "Bozeman",    "type": "Apartment Complex"},
        {"name": "Highmark Bozeman Apartments",      "address": "2115 S. 17th Ave., Bozeman, MT 59715",        "phone": "(406) 587-2115",  "city": "Bozeman",    "type": "Apartment Complex"},
        {"name": "Mountain View Apartments",         "address": "603 Emily Drive, Bozeman, MT 59718",          "phone": "(406) 587-7788",  "city": "Bozeman",    "type": "Apartment Complex"},
        {"name": "Stadium View Living",              "address": "2119 S 11th Ave, Bozeman, MT 59715",          "phone": "(877) 361-8220",  "city": "Bozeman",    "type": "Apartment Complex"},
        {"name": "Alliance Property Management",     "address": "2621 W. College St., Bozeman, MT 59718",      "phone": "(406) 585-0880",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Platinum Property Management",     "address": "2149 Durston, Ste. 34, Bozeman, MT 59718",    "phone": "(406) 577-1477",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Luna Properties, LLC",             "address": "605 W. Peach St., Ste. 201, Bozeman, MT",     "phone": "(406) 582-7490",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Birchwood at Hillcrest",           "address": "1201 Highland Blvd., Bozeman, MT 59715",      "phone": "(406) 414-2008",  "city": "Bozeman",    "type": "Senior Living"},
        {"name": "Highgate Senior Living",           "address": "2219 W. Oak St., Bozeman, MT 59718",          "phone": "(406) 587-5100",  "city": "Bozeman",    "type": "Senior Living"},
        {"name": "The Springs Living at Bozeman",    "address": "2632 Catron St., Bozeman, MT 59718",          "phone": "(406) 556-8000",  "city": "Bozeman",    "type": "Senior Living"},
        {"name": "Brookdale Springmeadows",          "address": "3175 Graf Street, Bozeman, MT 59715",         "phone": "(406) 587-4570",  "city": "Bozeman",    "type": "Senior Living"},
        {"name": "Belgrade Property Management",     "address": "Belgrade, MT 59714",                          "phone": "(406) 388-0000",  "city": "Belgrade",   "type": "Property Manager"},
        {"name": "Bridger View Apartments",          "address": "Belgrade, MT 59714",                          "phone": "(406) 388-1234",  "city": "Belgrade",   "type": "Apartment Complex"},
        {"name": "Livingston Property Rentals",      "address": "Livingston, MT 59047",                        "phone": "(406) 222-0000",  "city": "Livingston", "type": "Property Manager"},
        {"name": "Murray Hotel Residences",          "address": "201 W Park St, Livingston, MT 59047",         "phone": "(406) 222-1350",  "city": "Livingston", "type": "Hotel/Residential"},
        {"name": "Big Sky Resort Rentals",           "address": "Big Sky, MT 59716",                           "phone": "(406) 995-5000",  "city": "Big Sky",    "type": "STR/Vacation Rental"},
        {"name": "Lone Mountain Ranch",              "address": "750 Lone Mountain Ranch Rd, Big Sky, MT",     "phone": "(406) 995-4644",  "city": "Big Sky",    "type": "Resort/Residential"},
        {"name": "Big Sky Sotheby's Rentals",        "address": "Big Sky, MT 59716",                           "phone": "(406) 995-2211",  "city": "Big Sky",    "type": "Property Manager"},
        {"name": "Kalispell Property Management",    "address": "Kalispell, MT 59901",                         "phone": "(406) 752-0000",  "city": "Kalispell",  "type": "Property Manager"},
        {"name": "Glacier Apartments Kalispell",     "address": "Kalispell, MT 59901",                         "phone": "(406) 755-0000",  "city": "Kalispell",  "type": "Apartment Complex"},
        {"name": "Summit Senior Living Kalispell",   "address": "Kalispell, MT 59901",                         "phone": "(406) 752-5000",  "city": "Kalispell",  "type": "Senior Living"},
        {"name": "Whitefish Property Management",    "address": "Whitefish, MT 59937",                         "phone": "(406) 862-0000",  "city": "Whitefish",  "type": "Property Manager"},
        {"name": "Whitefish Lake Vacation Rentals",  "address": "Whitefish, MT 59937",                         "phone": "(406) 862-1234",  "city": "Whitefish",  "type": "STR/Vacation Rental"},
    ],
    "airbnb": [
        {"name": "Platinum Property Mgmt (STR)",     "address": "2149 Durston, Ste. 34, Bozeman, MT",          "phone": "(406) 577-1477",  "city": "Bozeman",    "type": "STR Manager"},
        {"name": "Stay Montana",                     "address": "122 Donjo Ave., Unit 4, Belgrade, MT",         "phone": "(888) 871-7856",  "city": "Belgrade",   "type": "STR Manager"},
        {"name": "Mountain Home Vacation Rentals",   "address": "Bozeman, MT",                                  "phone": "mountain-home.com","city": "Bozeman",   "type": "STR Manager"},
        {"name": "The Arrival Co.",                  "address": "Bozeman, MT",                                  "phone": "thearrivalco.com", "city": "Bozeman",   "type": "STR Manager"},
        {"name": "Big Sky Vacation Rentals",         "address": "Big Sky, MT 59716",                            "phone": "(406) 995-2000",  "city": "Big Sky",    "type": "STR Manager"},
        {"name": "Whitefish Mountain Rentals",       "address": "Whitefish, MT 59937",                          "phone": "(406) 862-5000",  "city": "Whitefish",  "type": "STR Manager"},
        {"name": "Glacier Country Rentals",          "address": "Kalispell, MT 59901",                          "phone": "(406) 756-0000",  "city": "Kalispell",  "type": "STR Manager"},
        {"name": "Livingston Vacation Rentals",      "address": "Livingston, MT 59047",                         "phone": "(406) 222-5000",  "city": "Livingston", "type": "STR Manager"},
    ],
    "commercial": [
        {"name": "Marriott Residence Inn Bozeman",   "address": "6195 E Valley Center Rd, Bozeman, MT 59718",  "phone": "(406) 582-8880",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Hilton Garden Inn Bozeman",        "address": "2023 Commerce Way, Bozeman, MT 59715",        "phone": "(406) 582-9900",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Hampton Inn Bozeman",              "address": "75 Baxter Lane, Bozeman, MT 59718",           "phone": "(406) 522-8000",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Holiday Inn Express Bozeman",      "address": "2305 Catron St., Bozeman, MT 59718",          "phone": "(406) 587-2222",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Hampton Inn Kalispell",            "address": "1140 US-2, Kalispell, MT 59901",              "phone": "(406) 755-7900",  "city": "Kalispell",  "type": "Hotel"},
        {"name": "Hilton Garden Inn Kalispell",      "address": "1840 US-93 S, Kalispell, MT 59901",           "phone": "(406) 756-4500",  "city": "Kalispell",  "type": "Hotel"},
        {"name": "Grouse Mountain Lodge Whitefish",  "address": "2 Fairway Dr, Whitefish, MT 59937",           "phone": "(406) 862-3000",  "city": "Whitefish",  "type": "Hotel"},
        {"name": "The Lodge at Whitefish Lake",      "address": "1380 Wisconsin Ave, Whitefish, MT 59937",     "phone": "(406) 863-4000",  "city": "Whitefish",  "type": "Hotel"},
        {"name": "Stockman Bank Bozeman",            "address": "1400 S. 3rd Ave., Bozeman, MT 59715",         "phone": "(406) 522-6100",  "city": "Bozeman",    "type": "Small Office"},
        {"name": "Glacier Bank Bozeman",             "address": "1400 N. 19th Ave., Bozeman, MT 59718",        "phone": "(406) 556-6700",  "city": "Bozeman",    "type": "Small Office"},
        {"name": "Bozeman Health Urgent Care",       "address": "1006 W. Main St., Bozeman, MT 59715",         "phone": "(406) 414-5900",  "city": "Bozeman",    "type": "Small Office"},
        {"name": "First Security Bank Livingston",   "address": "109 W Park St, Livingston, MT 59047",         "phone": "(406) 222-1900",  "city": "Livingston", "type": "Small Office"},
        {"name": "Glacier Bank Kalispell",           "address": "202 Main St, Kalispell, MT 59901",            "phone": "(406) 756-4200",  "city": "Kalispell",  "type": "Small Office"},
        {"name": "Whitefish Credit Union",           "address": "305 Spokane Ave, Whitefish, MT 59937",        "phone": "(406) 862-3525",  "city": "Whitefish",  "type": "Small Office"},
    ],
    "post_construction": [
        {"name": "Bozeman Builders Group",           "address": "Bozeman, MT 59715",                           "phone": "(406) 586-0000",  "city": "Bozeman",    "type": "General Contractor"},
        {"name": "Bridger Builders",                 "address": "Bozeman, MT 59715",                           "phone": "(406) 587-1234",  "city": "Bozeman",    "type": "General Contractor"},
        {"name": "Highline Partners",                "address": "Bozeman, MT 59718",                           "phone": "(406) 585-0000",  "city": "Bozeman",    "type": "General Contractor"},
        {"name": "Big Sky Build",                    "address": "Big Sky, MT 59716",                           "phone": "(406) 995-3000",  "city": "Big Sky",    "type": "General Contractor"},
        {"name": "Kalispell Construction Co.",       "address": "Kalispell, MT 59901",                         "phone": "(406) 752-1234",  "city": "Kalispell",  "type": "General Contractor"},
        {"name": "Flathead Builders",                "address": "Kalispell, MT 59901",                         "phone": "(406) 755-5678",  "city": "Kalispell",  "type": "General Contractor"},
        {"name": "Whitefish Custom Homes",           "address": "Whitefish, MT 59937",                         "phone": "(406) 862-3456",  "city": "Whitefish",  "type": "Custom Builder"},
        {"name": "Belgrade Homes LLC",               "address": "Belgrade, MT 59714",                          "phone": "(406) 388-5678",  "city": "Belgrade",   "type": "General Contractor"},
    ],
    "move_in_out": [
        {"name": "Alliance Property Management",     "address": "2621 W. College St., Bozeman, MT 59718",      "phone": "(406) 585-0880",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Platinum Property Management",     "address": "2149 Durston, Ste. 34, Bozeman, MT 59718",    "phone": "(406) 577-1477",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Luna Properties, LLC",             "address": "605 W. Peach St., Ste. 201, Bozeman, MT",     "phone": "(406) 582-7490",  "city": "Bozeman",    "type": "Property Manager"},
        {"name": "Big Sky Sotheby's Rentals",        "address": "Big Sky, MT 59716",                           "phone": "(406) 995-2211",  "city": "Big Sky",    "type": "Property Manager"},
        {"name": "Kalispell Property Management",    "address": "Kalispell, MT 59901",                         "phone": "(406) 752-0000",  "city": "Kalispell",  "type": "Property Manager"},
        {"name": "Whitefish Property Management",    "address": "Whitefish, MT 59937",                         "phone": "(406) 862-0000",  "city": "Whitefish",  "type": "Property Manager"},
    ],
    "carpet_window": [
        {"name": "Haymaker Apartments",              "address": "1624 W Babcock St, Bozeman, MT 59715",        "phone": "(406) 219-3190",  "city": "Bozeman",    "type": "Apartment Complex"},
        {"name": "Birchwood at Hillcrest",           "address": "1201 Highland Blvd., Bozeman, MT 59715",      "phone": "(406) 414-2008",  "city": "Bozeman",    "type": "Senior Living"},
        {"name": "Marriott Residence Inn Bozeman",   "address": "6195 E Valley Center Rd, Bozeman, MT 59718",  "phone": "(406) 582-8880",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Hilton Garden Inn Bozeman",        "address": "2023 Commerce Way, Bozeman, MT 59715",        "phone": "(406) 582-9900",  "city": "Bozeman",    "type": "Hotel"},
        {"name": "Grouse Mountain Lodge Whitefish",  "address": "2 Fairway Dr, Whitefish, MT 59937",           "phone": "(406) 862-3000",  "city": "Whitefish",  "type": "Hotel"},
        {"name": "The Lodge at Whitefish Lake",      "address": "1380 Wisconsin Ave, Whitefish, MT 59937",     "phone": "(406) 863-4000",  "city": "Whitefish",  "type": "Hotel"},
    ],
}

SERVICES = [
    "Standard Clean", "Deep Clean", "Move-In Clean", "Move-Out Clean",
    "Airbnb Turnover", "Post-Construction Clean", "Carpet Shampooing",
    "Window Cleaning", "Recurring Weekly", "Recurring Biweekly",
]


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 1 — /leads  (find | status | inbox | summary)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/leads")
def leads_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /leads find [category] [city] ──
    if sub == "find":
        parts = rest.strip().lower().split()
        category = parts[0] if parts else "residential"
        city_filter = " ".join(parts[1:]) if len(parts) > 1 else "all"
        if category not in LEADS_DB:
            cats = " | ".join(LEADS_DB.keys())
            respond(f"⚠️ Unknown category. Available: `{cats}`\nUsage: `/leads find [category] [city]`")
            return
        db = LEADS_DB[category]
        if city_filter != "all":
            db = [l for l in db if city_filter in l.get("city", "").lower()]
        if not db:
            respond(f"No leads found for `{category}` in `{city_filter}`. Try `/leads find {category} all`.")
            return
        lines = [f"• *{l['name']}* ({l['type']})\n  📍 {l['address']}\n  📞 {l['phone']}" for l in db[:20]]
        respond(f"*🔍 {category.replace('_',' ').title()} Leads — {city_filter.title()} ({len(db)} found):*\n\n" + "\n\n".join(lines))

    # ── /leads status ──
    elif sub == "status":
        if not leads_log:
            respond("No leads have been contacted yet.")
            return
        lines = [f"• {l['name']} — {l.get('status','contacted')} — {l.get('date','')}" for l in leads_log[-15:]]
        respond(f"*📋 Contacted Leads ({len(leads_log)} total):*\n\n" + "\n".join(lines))

    # ── /leads inbox [platform] ──
    elif sub == "inbox":
        platform = rest.strip() or None
        unreviewed = lm_get_all(platform=platform, unreviewed_only=True)
        if not unreviewed:
            respond(f"📬 No unreviewed leads{f' from {platform}' if platform else ''}. All caught up!")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📬 Lead Inbox — {len(unreviewed)} Unreviewed"}},
            {"type": "divider"},
        ]
        for lead in unreviewed[:15]:
            blocks.append({"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*{lead.get('icon','')} {lead['platform']}*\n{lead.get('name','Unknown')}"},
                {"type": "mrkdwn", "text": f"*Phone:* {lead.get('phone','N/A')}\n*Email:* {lead.get('email','N/A')}"},
            ]})
            if lead.get("service"):
                blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"Service: {lead.get('service','')} | {lead.get('timestamp','')}"}]})
            blocks.append({"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✅ Reviewed"}, "action_id": "mark_lead_reviewed", "value": lead.get("hash","")},
                {"type": "button", "text": {"type": "plain_text", "text": "✉️ Draft Email"}, "action_id": "draft_lead_email", "value": f"reengagement|{lead.get('name','').split()[0] if lead.get('name') else 'there'}"},
            ]})
            blocks.append({"type": "divider"})
        respond(blocks=blocks)

    # ── /leads summary ──
    elif sub == "summary":
        summary = build_lead_summary()
        platform_lines = []
        for p, data in summary.get("by_platform", {}).items():
            icon = data.get("icon", "📋")
            platform_lines.append(f"{icon} *{p}:* {data['total']} total, {data['unreviewed']} unreviewed")
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": "📊 Lead Summary — All Platforms"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{today()} • For {OFFICE_ASSISTANT_NAME}_"}]},
            {"type": "divider"},
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Total Leads:*\n{summary['total']}"},
                {"type": "mrkdwn", "text": f"*Unreviewed:*\n📬 {summary['unreviewed']}"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": "*By Platform:*\n" + "\n".join(platform_lines)}},
        ]
        respond(blocks=blocks)

    else:
        respond(
            "*🔍 /leads — Lead Tools*\n\n"
            "`/leads find [category] [city]` — Find leads by type and city\n"
            "  Categories: `residential` `airbnb` `commercial` `post_construction` `move_in_out` `carpet_window`\n"
            "`/leads status` — View contacted leads\n"
            "`/leads inbox [platform]` — View unreviewed leads from all platforms\n"
            "`/leads summary` — Lead summary across all platforms"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 2 — /job  (assign | list | checkin | checkout)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/job")
def job_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /job assign @emp | addr | service | time ──
    if sub == "assign":
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 4:
            respond("Usage: `/job assign @employee | address | service | date/time`")
            return
        jid = next_id("JOB", jobs)
        jobs[jid] = {"employee": parts[0], "address": parts[1], "service": parts[2], "time": parts[3], "status": "assigned", "assigned_at": now_ts()}
        respond(f"✅ *Job Assigned:* `{jid}`\n👷 {parts[0]}\n📍 {parts[1]}\n🧹 {parts[2]}\n📅 {parts[3]}")

    # ── /job list [status] ──
    elif sub == "list":
        status_filter = rest.strip().lower() or "all"
        filtered = {k: v for k, v in jobs.items() if status_filter == "all" or v.get("status") == status_filter}
        if not filtered:
            respond(f"No jobs found with status: `{status_filter}`")
            return
        lines = [f"• `{k}` — {v['service']} @ {v['address']}\n  👷 {v['employee']} | 📅 {v['time']} | Status: *{v['status']}*" for k, v in filtered.items()]
        respond(f"*📋 Jobs ({len(filtered)}):*\n\n" + "\n\n".join(lines))

    # ── /job checkin JOB-XXXX ──
    elif sub == "checkin":
        jid = rest.strip().upper()
        if jid not in jobs:
            respond(f"⚠️ Job `{jid}` not found.")
            return
        jobs[jid]["status"] = "in_progress"
        jobs[jid]["checkin_time"] = now_ts()
        respond(f"✅ *Checked in* to `{jid}` at {now_ts()}\n📍 {jobs[jid]['address']}")

    # ── /job checkout JOB-XXXX ──
    elif sub == "checkout":
        jid = rest.strip().upper()
        if jid not in jobs:
            respond(f"⚠️ Job `{jid}` not found.")
            return
        jobs[jid]["status"] = "complete"
        jobs[jid]["checkout_time"] = now_ts()
        respond(f"✅ *Checked out* of `{jid}` at {now_ts()}\n🧹 {jobs[jid]['service']} — *Complete!*")

    else:
        respond(
            "*👷 /job — Job Management*\n\n"
            "`/job assign @emp | address | service | time` — Assign a job\n"
            "`/job list [status]` — View jobs (all, assigned, in_progress, complete)\n"
            "`/job checkin JOB-XXXX` — Clock in\n"
            "`/job checkout JOB-XXXX` — Clock out"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 3 — /customer  (new | followup | complete)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/customer")
def customer_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /customer new Name | Phone | Email | Addr | Service ──
    if sub == "new":
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 3:
            respond("Usage: `/customer new Name | Phone | Email | Address | Service`")
            return
        cid = next_id("CUST", customers)
        customers[cid] = {"name": parts[0], "phone": parts[1], "email": parts[2] if len(parts) > 2 else "", "address": parts[3] if len(parts) > 3 else "", "service": parts[4] if len(parts) > 4 else "", "created": now_ts()}
        respond(f"✅ *New Customer Added:* `{cid}`\n👤 {parts[0]}\n📞 {parts[1]}")

    # ── /customer followup Name | Phone | Service ──
    elif sub == "followup":
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 2:
            respond("Usage: `/customer followup Name | Phone | Service`")
            return
        name, phone = parts[0], parts[1]
        service = parts[2] if len(parts) > 2 else "cleaning"
        respond(f"*📞 Follow-Up Draft for {name}:*\n\n_\"Hi {name}, this is {OWNER_NAME} from {BUSINESS_NAME}. I just wanted to check in and see how everything looked after your {service}. Your satisfaction is our top priority, and we'd love to hear your feedback. Is there anything else we can help with? Thank you for choosing us!\"_\n\n📞 {phone}")

    # ── /customer complete Name | Addr | Service | Employee ──
    elif sub == "complete":
        parts = [p.strip() for p in rest.split("|")]
        if len(parts) < 3:
            respond("Usage: `/customer complete Name | Address | Service | Employee`")
            return
        name, addr, svc = parts[0], parts[1], parts[2]
        emp = parts[3] if len(parts) > 3 else "our team"
        respond(f"*✅ Job Complete Notice — Draft:*\n\n_\"Hi {name}, great news! {emp} has just finished your {svc} at {addr}. We hope everything looks wonderful! If there's anything at all that needs attention, please don't hesitate to call us at {BUSINESS_PHONE}. It was our pleasure to take care of your home today. Thank you for choosing {BUSINESS_NAME}!\"_")

    else:
        respond(
            "*👥 /customer — Customer Communications*\n\n"
            "`/customer new Name | Phone | Email | Address | Service` — Add a customer\n"
            "`/customer followup Name | Phone | Service` — Draft follow-up\n"
            "`/customer complete Name | Address | Service | Employee` — Job complete notice"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 4 — /hcp  (jobs | customers | leads | analysis)
# ═════════════════════════════════════════════════════════════════════════════

def build_hcp_analysis():
    """Pull jobs/estimates/customers from HCP and build the analysis blocks.
    Returns (text_summary, blocks). On error, blocks is None and text is the error message."""
    jobs_data, err = hcp_get("/jobs", params={"page_size": 100})
    if err:
        return (f"⚠️ Could not fetch jobs: {err}\n\n_Make sure your HousecallPro API key is set in `.env`._", None)
    all_jobs = jobs_data.get("jobs", [])
    cancelled = [j for j in all_jobs if j.get("work_status") == "cancelled"]
    needs_invoice = [j for j in all_jobs if j.get("invoice_status") == "uninvoiced" and j.get("work_status") == "completed"]
    est_data, est_err = hcp_get("/estimates", params={"page_size": 100})
    unconverted_estimates = []
    if not est_err:
        unconverted_estimates = [e for e in est_data.get("estimates", []) if e.get("status") not in ("approved", "converted_to_job")]
    cust_data, cust_err = hcp_get("/customers", params={"page_size": 100})
    lapsed_customers = []
    if not cust_err:
        today_dt = datetime.date.today()
        for c in cust_data.get("customers", []):
            last_job = c.get("last_job_date") or c.get("updated_at", "")
            if last_job:
                try:
                    last_dt = datetime.date.fromisoformat(last_job[:10])
                    if (today_dt - last_dt).days > 60:
                        lapsed_customers.append({"name": f"{c.get('first_name','')} {c.get('last_name','')}", "phone": c.get("mobile_number") or c.get("home_number","N/A"), "days_since": (today_dt - last_dt).days})
                except Exception:
                    pass
    summary = (f"HCP Analysis — {len(all_jobs)} jobs, "
               f"{len(cancelled)} cancelled, {len(needs_invoice)} uninvoiced, "
               f"{len(unconverted_estimates)} open estimates, {len(lapsed_customers)} lapsed customers.")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "📊 HousecallPro Business Analysis"}},
        {"type": "divider"},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Total Jobs:*\n{len(all_jobs)}"},
            {"type": "mrkdwn", "text": f"*Cancelled:*\n🔴 {len(cancelled)}"},
            {"type": "mrkdwn", "text": f"*Uninvoiced:*\n🟡 {len(needs_invoice)}"},
            {"type": "mrkdwn", "text": f"*Open Estimates:*\n🟠 {len(unconverted_estimates)}"},
            {"type": "mrkdwn", "text": f"*Lapsed (60+ days):*\n🔵 {len(lapsed_customers)}"},
        ]},
        {"type": "divider"},
    ]
    if cancelled:
        lines = "\n".join([f"• {j.get('customer',{}).get('first_name','')} {j.get('customer',{}).get('last_name','')} — {j.get('job_type',{}).get('name','?')}" for j in cancelled[:8]])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🔴 Cancelled Jobs:*\n{lines}"}})
    if unconverted_estimates:
        lines = "\n".join([f"• {e.get('customer',{}).get('first_name','')} {e.get('customer',{}).get('last_name','')} — ${e.get('total_amount','?')} | {e.get('status','?')}" for e in unconverted_estimates[:8]])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🟠 Unconverted Estimates:*\n{lines}"}})
    if lapsed_customers:
        lines = "\n".join([f"• {c['name']} — 📞 {c['phone']} — {c['days_since']} days" for c in sorted(lapsed_customers, key=lambda x: x["days_since"], reverse=True)[:8]])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🔵 Lapsed Customers:*\n{lines}"}})
    if needs_invoice:
        lines = "\n".join([f"• {j.get('customer',{}).get('first_name','')} {j.get('customer',{}).get('last_name','')} — {j.get('job_type',{}).get('name','?')}" for j in needs_invoice[:8]])
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*🟡 Uninvoiced Jobs:*\n{lines}"}})
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Analysis run {now_ts()} • {BUSINESS_NAME}_"}]})
    return (summary, blocks)


def build_lapsed_customers_csv(days_threshold: int = 60):
    """Pull every customer from HCP, filter to those inactive >= days_threshold,
    and return (csv_text, count). On error returns (None, error_message)."""
    today_dt = datetime.date.today()
    rows = []
    page = 1
    while True:
        data, err = hcp_get("/customers", params={"page_size": 200, "page": page})
        if err:
            return (None, err)
        batch = data.get("customers", [])
        if not batch:
            break
        for c in batch:
            last_job = c.get("last_job_date") or c.get("updated_at", "")
            if not last_job:
                continue
            try:
                last_dt = datetime.date.fromisoformat(last_job[:10])
            except Exception:
                continue
            days = (today_dt - last_dt).days
            if days < days_threshold:
                continue
            rows.append({
                "name": f"{c.get('first_name','').strip()} {c.get('last_name','').strip()}".strip(),
                "phone": c.get("mobile_number") or c.get("home_number") or "",
                "email": c.get("email", ""),
                "last_job_date": last_job[:10],
                "days_since_last_job": days,
                "address": ", ".join(filter(None, [
                    (c.get("addresses") or [{}])[0].get("street", "") if c.get("addresses") else "",
                    (c.get("addresses") or [{}])[0].get("city", "") if c.get("addresses") else "",
                    (c.get("addresses") or [{}])[0].get("state", "") if c.get("addresses") else "",
                ])),
                "tags": ", ".join(c.get("tags", []) or []),
                "hcp_customer_id": c.get("id", ""),
            })
        # Stop when we get a partial page (last page).
        if len(batch) < 200:
            break
        page += 1
        if page > 50:  # hard safety stop
            break
    rows.sort(key=lambda r: r["days_since_last_job"], reverse=True)
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=[
        "name", "phone", "email", "last_job_date", "days_since_last_job",
        "address", "tags", "hcp_customer_id",
    ])
    writer.writeheader()
    writer.writerows(rows)
    return (buf.getvalue(), len(rows))


@app.command("/hcp")
def hcp_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /hcp jobs [status] ──
    if sub == "jobs":
        status = rest.strip().lower() or "scheduled"
        params = {"page_size": 25}
        if status != "all":
            params["work_status"] = status
        data, err = hcp_get("/jobs", params=params)
        if err:
            respond(f"⚠️ HousecallPro error: {err}")
            return
        job_list_hcp = data.get("jobs", [])
        if not job_list_hcp:
            respond(f"No jobs found with status: `{status}`")
            return
        def _sched_date(j):
            s = (j.get('schedule') or {}).get('scheduled_start')
            return s[:10] if s else '?'
        lines = [f"• *{j.get('customer',{}).get('first_name','')} {j.get('customer',{}).get('last_name','')}*\n  🏷 {j.get('job_type',{}).get('name','?')} | 📅 {_sched_date(j)} | Status: {j.get('work_status','?')}" for j in job_list_hcp[:15]]
        respond(f"*📋 HousecallPro Jobs — {status.title()} ({len(job_list_hcp)} found):*\n\n" + "\n\n".join(lines))

    # ── /hcp customers [search] ──
    elif sub == "customers":
        query = rest.strip()
        params = {"page_size": 20}
        if query:
            params["q"] = query
        data, err = hcp_get("/customers", params=params)
        if err:
            respond(f"⚠️ HousecallPro error: {err}")
            return
        cust_list = data.get("customers", [])
        if not cust_list:
            respond(f"No customers found{' matching: ' + query if query else ''}.")
            return
        lines = [f"• *{c.get('first_name','')} {c.get('last_name','')}*\n  📞 {c.get('mobile_number') or c.get('home_number','N/A')}\n  📧 {c.get('email','N/A')}" for c in cust_list[:15]]
        respond(f"*👥 HousecallPro Customers ({len(cust_list)} found):*\n\n" + "\n\n".join(lines))

    # ── /hcp leads ──
    elif sub == "leads":
        data, err = hcp_get("/leads", params={"page_size": 25})
        if err:
            respond(f"⚠️ HousecallPro error: {err}")
            return
        lead_list = data.get("leads", [])
        if not lead_list:
            respond("No leads found in your HousecallPro pipeline.")
            return
        lines = [f"• *{l.get('customer',{}).get('first_name','')} {l.get('customer',{}).get('last_name','')}*\n  📞 {l.get('customer',{}).get('mobile_number','N/A')}\n  🏷 Stage: {l.get('lead_stage',{}).get('name','Unknown')}\n  📅 Created: {l.get('created_at','?')[:10]}" for l in lead_list[:15]]
        respond(f"*🔍 HousecallPro Pipeline Leads ({len(lead_list)} found):*\n\n" + "\n\n".join(lines))

    # ── /hcp analysis ──
    elif sub == "analysis":
        respond("⏳ Running HousecallPro analysis... this may take a moment.")
        text, blocks = build_hcp_analysis()
        if blocks:
            respond(blocks=blocks, text=text)
        else:
            respond(text)

    # ── /hcp lost — Full lapsed-customer CSV upload ──
    elif sub in ("lost", "lapsed"):
        # Optional day threshold: `/hcp lost 90`
        try:
            threshold = int(rest.strip()) if rest.strip() else 60
        except ValueError:
            threshold = 60
        respond(f"⏳ Pulling all customers inactive {threshold}+ days... one moment.")
        csv_text, result = build_lapsed_customers_csv(threshold)
        if csv_text is None:
            respond(f"⚠️ Could not pull customers: {result}")
            return
        count = result
        if count == 0:
            respond(f"✅ No customers inactive {threshold}+ days. Pipeline looks healthy.")
            return
        filename = f"lost_customers_{threshold}d_{datetime.date.today().isoformat()}.csv"
        try:
            app.client.files_upload_v2(
                channel=command["channel_id"],
                content=csv_text,
                filename=filename,
                title=f"Lost Customers ({threshold}+ days inactive)",
                initial_comment=f"📎 *Full lost-customer report* — {count} customers inactive {threshold}+ days. Sorted by days since last job (longest first).",
            )
        except Exception as e:
            respond(f"⚠️ Built the report ({count} customers) but couldn't upload: {e}")

    else:
        respond(
            "*📊 /hcp — HousecallPro Integration*\n\n"
            "`/hcp jobs [status]` — Pull jobs (scheduled, completed, cancelled, all)\n"
            "`/hcp customers [search]` — Search customers\n"
            "`/hcp leads` — View pipeline leads\n"
            "`/hcp analysis` — Full gap analysis (missed leads, lost customers, revenue gaps)\n"
            "`/hcp lost [days]` — Full lapsed-customer CSV (default 60 days)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 5 — /ai  (draft | complaint | recommend | status)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/ai")
def ai_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /ai draft [type] [Name] [context] ──
    if sub == "draft":
        parts = rest.strip().split(None, 2)
        email_type = parts[0].lower() if parts else ""
        customer_name = parts[1] if len(parts) > 1 else "there"
        context = parts[2] if len(parts) > 2 else ""
        valid_types = ["estimate_followup", "win_back", "reengagement", "airbnb_pitch", "review_request", "upsell_carpet_window", "post_construction", "complaint_response", "thank_you", "welcome", "reschedule"]
        if email_type not in valid_types:
            respond(f"⚠️ Unknown type. Available:\n`{'` `'.join(valid_types)}`\n\nUsage: `/ai draft [type] [Name] [context]`")
            return
        respond(f"✨ AI is drafting your `{email_type}` email for {customer_name}...")
        try:
            result = ai_draft_email(email_type, customer_name, context)
        except Exception as e:
            respond(f"⚠️ AI error: {str(e)}")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"✉️ AI Email Draft — {email_type.replace('_',' ').title()}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_AI Model: {result.get('model_used','GPT-4.1')} • For review by {OFFICE_ASSISTANT_NAME}_"}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Subject:* {result['subject']}"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Body:*\n```{result['body']}```"}},
            {"type": "divider"},
            {"type": "actions", "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve & Send"}, "style": "primary", "action_id": "email_approved", "value": f"{email_type}|{customer_name}"},
                {"type": "button", "text": {"type": "plain_text", "text": "🔄 Regenerate"}, "action_id": "regenerate_email", "value": f"{email_type}|{customer_name}|{context}"},
                {"type": "button", "text": {"type": "plain_text", "text": "📋 More Templates"}, "action_id": "show_email_menu", "value": "menu"},
            ]},
        ]
        respond(blocks=blocks)

    # ── /ai complaint [Name] [issue] ──
    elif sub == "complaint":
        parts = rest.strip().split(None, 1)
        name = parts[0] if parts else "Customer"
        issue = parts[1] if len(parts) > 1 else "general complaint"
        respond(f"🛡️ Generating Chick-fil-A level response for {name}...")
        try:
            result = ai_handle_complaint(name, issue)
        except Exception as e:
            respond(f"⚠️ AI error: {str(e)}")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"🛡️ Complaint Response — {name}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_AI Model: {result.get('model_used','GPT-4.1')} • Chick-fil-A Standard_"}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Customer Response (send this):*\n```{result['response']}```"}},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*🔒 Internal Notes (for Carolyn only):*\n_{result['internal_notes']}_"}},
        ]
        if result.get("escalate"):
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "⚠️ *ESCALATE TO CHRIS JOHNSON* — This issue requires owner attention."}})
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Send Response"}, "style": "primary", "action_id": "email_approved", "value": f"complaint|{name}"},
            {"type": "button", "text": {"type": "plain_text", "text": "📋 Recovery Protocol"}, "action_id": "show_recovery", "value": "protocol"},
        ]})
        respond(blocks=blocks)

    # ── /ai recommend [topic] ──
    elif sub == "recommend":
        topic = rest.strip() or "growth"
        respond(f"💡 Generating AI recommendation on `{topic}`...")
        try:
            result = ai_recommend(topic)
        except Exception as e:
            respond(f"⚠️ AI error: {str(e)}")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"💡 Business Recommendation — {topic.title()}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_AI-generated for {OFFICE_ASSISTANT_NAME} • {today()}_"}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": result}},
        ]
        respond(blocks=blocks)

    # ── /ai status ──
    elif sub == "status":
        status = get_ai_status()
        model_lines = "\n".join([f"• *{k}:* {v}" for k, v in status["models"].items()])
        routing_lines = "\n".join([f"• {k} → `{v}`" for k, v in status["routing"].items()])
        respond(f"*🤖 AI Engine Status:*\n\n*Models:*\n{model_lines}\n\n*Task Routing:*\n{routing_lines}")

    else:
        respond(
            "*🤖 /ai — AI-Powered Tools*\n\n"
            "`/ai draft [type] [Name] [context]` — AI-written email\n"
            "  Types: `estimate_followup` `win_back` `reengagement` `airbnb_pitch` `review_request` `upsell_carpet_window` `post_construction` `complaint_response` `thank_you` `welcome` `reschedule`\n"
            "`/ai complaint [Name] [issue]` — AI complaint response (Chick-fil-A standard)\n"
            "`/ai recommend [topic]` — AI business recommendations\n"
            "`/ai status` — AI model status and routing"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 6 — /service  (script | standards | qa | wow)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/service")
def service_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /service script [scenario] ──
    if sub == "script":
        scenario = rest.strip().lower().replace(" ", "_") or "new_inquiry"
        available = list(SCRIPTS.keys())
        script = get_script(scenario, agent_name="Carolyn", area="Bozeman")
        if not script:
            respond(f"⚠️ Unknown scenario. Available:\n`{'` `'.join(available)}`")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📞 Service Script — {script['title']}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Scenario: {script['scenario']}_"}]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": script["script"]}},
        ]
        respond(blocks=blocks)

    # ── /service standards ──
    elif sub == "standards":
        respond(blocks=format_standards_for_slack())

    # ── /service qa [job_type] ──
    elif sub == "qa":
        job_type = rest.strip().lower().replace(" ", "_") or "standard_clean"
        available = list(QA_CHECKLIST.keys())
        checklist = get_qa_checklist(job_type)
        items = "\n".join([f"☐ {item}" for item in checklist])
        respond(f"*✅ Quality Assurance Checklist — {job_type.replace('_',' ').title()}:*\n\n{items}\n\n_Available types: `{'` `'.join(available)}`_")

    # ── /service wow [Name] ──
    elif sub == "wow":
        name = rest.strip() or "your customer"
        idea = get_wow_moment(name)
        respond(f"✨ *Wow Moment Idea for {name}:*\n\n💡 _{idea}_\n\n_Type `/service wow {name}` again for another idea!_")

    else:
        respond(
            "*🛡️ /service — Customer Service (Chick-fil-A Standard)*\n\n"
            "`/service script [scenario]` — Get a response script\n"
            "`/service standards` — View service standards\n"
            "`/service qa [job_type]` — Post-job QA checklist\n"
            "`/service wow [Name]` — Generate a wow moment idea"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 7 — /office  (brief | priorities)
# ═════════════════════════════════════════════════════════════════════════════

def build_priority_list(hcp_data=None):
    items = []
    if hcp_data:
        if hcp_data.get("needs_invoice"):
            items.append({"priority": 1, "category": "Revenue", "icon": "🔴", "title": f"Invoice {len(hcp_data['needs_invoice'])} uninvoiced jobs", "detail": "Money already earned — collect it today.", "action": "Open HousecallPro → Jobs → Completed, Uninvoiced → Send invoices."})
        if hcp_data.get("unconverted_estimates"):
            items.append({"priority": 2, "category": "Sales", "icon": "🟠", "title": f"Follow up on {len(hcp_data['unconverted_estimates'])} unconverted estimates", "detail": "A personal call converts ~40% of these.", "action": "Use /ai draft estimate_followup [Name] for AI-written follow-ups."})
        if hcp_data.get("cancelled"):
            items.append({"priority": 3, "category": "Retention", "icon": "🔴", "title": f"Review {len(hcp_data['cancelled'])} cancelled jobs", "detail": "Identify patterns — pricing, scheduling, or service issues.", "action": "Use /ai draft win_back [Name] to re-engage."})
        if hcp_data.get("lapsed_customers"):
            items.append({"priority": 4, "category": "Retention", "icon": "🔵", "title": f"Re-engage {len(hcp_data['lapsed_customers'])} lapsed customers", "detail": "Re-engagement costs 5x less than new acquisition.", "action": "Use /ai draft reengagement [Name] for personalized messages."})
    standing = [
        {"priority": 5, "category": "Growth", "icon": "🟢", "title": "Launch Airbnb/STR outreach — Big Sky & Whitefish", "detail": "Peak summer season approaching. Lock in turnover contracts now.", "action": "/leads find airbnb big sky → /ai draft airbnb_pitch [Name]"},
        {"priority": 6, "category": "Growth", "icon": "🟢", "title": "Target post-construction in Kalispell & Whitefish", "detail": "Premium-priced jobs in fast-growing construction markets.", "action": "/leads find post_construction kalispell"},
        {"priority": 7, "category": "Operations", "icon": "🟡", "title": "Audit recurring job schedule through end of quarter", "detail": "Ensure no recurring customer falls through the cracks.", "action": "Review in HousecallPro → Recurring Jobs."},
        {"priority": 8, "category": "Marketing", "icon": "🟡", "title": "Request Google reviews from recent customers", "detail": "Reviews are #1 driver of new residential customers.", "action": "/ai draft review_request [Name]"},
        {"priority": 9, "category": "Operations", "icon": "🟡", "title": "Onboard all 10 employees to Slack", "detail": "Consistent check-in/out data improves payroll accuracy.", "action": "/announce [onboarding instructions]"},
        {"priority": 10, "category": "Growth", "icon": "🟢", "title": "Upsell carpet shampooing & window cleaning", "detail": "High-margin add-ons to existing customers.", "action": "/ai draft upsell_carpet_window [Name]"},
    ]
    items.extend(standing)
    return sorted(items, key=lambda x: x["priority"])


@app.command("/office")
def office_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /office brief ──
    if sub == "brief":
        hcp_summary = {}
        jobs_data, err = hcp_get("/jobs", params={"page_size": 100})
        if not err:
            all_j = jobs_data.get("jobs", [])
            hcp_summary["needs_invoice"] = [j for j in all_j if j.get("invoice_status") == "uninvoiced" and j.get("work_status") == "completed"]
            hcp_summary["cancelled"] = [j for j in all_j if j.get("work_status") == "cancelled"]
            hcp_summary["scheduled_today"] = [j for j in all_j if (j.get("schedule") or {}).get("scheduled_start") and j["schedule"]["scheduled_start"][:10] == datetime.date.today().isoformat()]
        est_data, est_err = hcp_get("/estimates", params={"page_size": 100})
        if not est_err:
            hcp_summary["unconverted_estimates"] = [e for e in est_data.get("estimates", []) if e.get("status") not in ("approved", "converted_to_job")]
        cust_data, cust_err = hcp_get("/customers", params={"page_size": 100})
        if not cust_err:
            today_dt = datetime.date.today()
            hcp_summary["lapsed_customers"] = [c for c in cust_data.get("customers", []) if c.get("last_job_date") and (today_dt - datetime.date.fromisoformat(c["last_job_date"][:10])).days > 60]

        jobs_today = len(hcp_summary.get("scheduled_today", []))
        uninvoiced = len(hcp_summary.get("needs_invoice", []))
        open_ests = len(hcp_summary.get("unconverted_estimates", []))
        lapsed = len(hcp_summary.get("lapsed_customers", []))
        lead_summary = build_lead_summary()
        new_leads = lead_summary.get("unreviewed", 0)

        try:
            ai_narrative = ai_morning_brief(jobs_today, uninvoiced, open_ests, lapsed, new_leads)
        except Exception:
            ai_narrative = ""

        priorities = build_priority_list(hcp_summary)
        top3_text = "\n".join([f"{i+1}. {item['icon']} *[{item['category']}]* {item['title']}" for i, item in enumerate(priorities[:3])])

        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"☀️ Good Morning, {OFFICE_ASSISTANT_NAME} — Daily Brief"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{today()} • {BUSINESS_NAME}_"}]},
            {"type": "divider"},
        ]
        if ai_narrative:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": ai_narrative}})
            blocks.append({"type": "divider"})
        blocks += [
            {"type": "section", "fields": [
                {"type": "mrkdwn", "text": f"*Jobs Today:*\n📅 {jobs_today}"},
                {"type": "mrkdwn", "text": f"*Uninvoiced:*\n🟡 {uninvoiced}"},
                {"type": "mrkdwn", "text": f"*Open Estimates:*\n🟠 {open_ests}"},
                {"type": "mrkdwn", "text": f"*Lapsed Customers:*\n🔵 {lapsed}"},
                {"type": "mrkdwn", "text": f"*New Leads (All Platforms):*\n📬 {new_leads}"},
                {"type": "mrkdwn", "text": f"*Active Slack Jobs:*\n🟢 {len([j for j in jobs.values() if j.get('status') == 'assigned'])}"},
            ]},
            {"type": "divider"},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*🎯 Top 3 Priorities:*\n{top3_text}"}},
        ]
        respond(blocks=blocks)

    # ── /office priorities ──
    elif sub == "priorities":
        priorities = build_priority_list()
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📋 Priority Action List — {OFFICE_ASSISTANT_NAME}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{today()} • {BUSINESS_NAME}_"}]},
            {"type": "divider"},
        ]
        for item in priorities:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{item['priority']}. {item['icon']} *[{item['category']}]* {item['title']}\n   _{item['detail']}_\n   👉 _{item['action']}_"}})
            blocks.append({"type": "divider"})
        respond(blocks=blocks)

    # ── /office feed [filter] — Unified event feed ──
    elif sub == "feed":
        filter_type = rest.strip().lower() or None
        valid_filters = ["lead", "text", "hcp_message", "job", "alert", "system"]
        if filter_type and filter_type not in valid_filters:
            respond(f"⚠️ Unknown filter. Available: `{'` `'.join(valid_filters)}` or leave blank for all.")
            return
        events = get_feed(limit=15, event_type=filter_type)
        unread = cc_unread_count()
        sms_unread = sms_unread_count()
        if not events:
            respond(f"📋 *Unified Feed* — No events yet.\n\n_The feed populates as leads come in, texts arrive, jobs update, and alerts fire. Check back soon!_")
            return
        blocks = [
            {"type": "header", "text": {"type": "plain_text", "text": f"📋 Unified Feed — {OFFICE_ASSISTANT_NAME}"}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{unread} unread events • {sms_unread} unread texts • Showing last 15 • {now_ts()}_"}]},
            {"type": "divider"},
        ]
        for e in events:
            read_marker = "" if e.get("read") else " 🔵"
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{e['icon']}{read_marker} *{e['title']}*\n_{e['source']} • {e['timestamp']}_\n{e['detail'][:200]}"}})
        blocks.append({"type": "divider"})
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Mark All Read"}, "action_id": "mark_all_feed_read", "value": "all"},
            {"type": "button", "text": {"type": "plain_text", "text": "🔄 Refresh"}, "action_id": "refresh_feed", "value": filter_type or "all"},
        ]})
        respond(blocks=blocks)

    # ── /office eod — Trigger end-of-day summary manually ──
    elif sub == "eod":
        s = build_eod_summary()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).strftime("%A, %B %d")
        unresolved_text = ""
        if s["unresolved_items"]:
            items = [f"  • {e['icon']} {e['title']}" for e in s["unresolved_items"]]
            unresolved_text = "\n*Still needs attention:*\n" + "\n".join(items)
        else:
            unresolved_text = "\n✅ *Everything handled today — great work, Carolyn!*"
        text = (f"🌅 *End-of-Day Summary — {datetime.date.today().strftime('%A, %B %d')}*\n\n"
                f"📊 *Today's Numbers:*\n"
                f"  • Jobs completed: *{s['jobs_completed']}*\n"
                f"  • New leads: *{s['new_leads_today']}*\n"
                f"  • Texts/messages received: *{s['texts_received']}*\n"
                f"  • Open estimates: *{s['open_estimates']}*\n\n"
                f"📅 *Tomorrow ({tomorrow}):*\n"
                f"  • Jobs scheduled: *{s['jobs_scheduled_tomorrow']}*\n"
                f"{unresolved_text}\n\n_Have a great evening! 🧹_")
        respond(text)

    # ── /office text [send|inbox|convo] — Twilio SMS from Slack ──
    elif sub == "text":
        text_sub, text_rest = parse_sub(rest)

        # /office text send [number] [message]
        if text_sub == "send":
            parts = text_rest.strip().split(None, 1)
            if len(parts) < 2:
                respond("Usage: `/office text send [phone number] [message]`\nExample: `/office text send 406-555-1234 Hi! This is Carolyn from Montana Premium House Care.`")
                return
            phone, body = parts[0], parts[1]
            result = send_sms(phone, body)
            if result["success"]:
                log_event("text", "Twilio", f"Text sent to {phone}", body[:200], "📤")
                respond(f"✅ *Text sent to {phone}*\n\n>{body}\n\n_Sent from {BUSINESS_PHONE} via Twilio_")
            else:
                respond(f"⚠️ Failed to send: {result['error']}")

        # /office text inbox
        elif text_sub == "inbox":
            messages = sms_inbox(limit=15)
            twilio_status = get_twilio_status()
            if not twilio_status["configured"]:
                respond("⚠️ Twilio not configured yet. Add `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_PHONE_NUMBER` to your `.env` file.")
                return
            if not messages:
                respond(f"📱 *Text Inbox* — No messages yet.\n_Unread conversations: {twilio_status['unread']}_")
                return
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": "📱 Text Message Inbox"}},
                {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{twilio_status['unread']} unread • {twilio_status['active_conversations']} conversations • {twilio_status['messages_stored']} total messages_"}]},
                {"type": "divider"},
            ]
            for msg in messages:
                direction = "📥" if msg["direction"] == "incoming" else "📤"
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"{direction} *{msg['customer_phone']}* — {msg['timestamp']}\n>{msg['body'][:200]}"}})
            respond(blocks=blocks)

        # /office text convo [number]
        elif text_sub == "convo":
            phone = text_rest.strip()
            if not phone:
                respond("Usage: `/office text convo [phone number]`")
                return
            msgs = get_conversation(phone, limit=10)
            if not msgs:
                respond(f"No conversation found with {phone}.")
                return
            blocks = [
                {"type": "header", "text": {"type": "plain_text", "text": f"💬 Conversation with {phone}"}},
                {"type": "divider"},
            ]
            for msg in reversed(msgs):  # Oldest first
                direction = "📥 Them" if msg["direction"] == "incoming" else "📤 You"
                blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": f"*{direction}* — {msg['timestamp']}\n>{msg['body'][:200]}"}})
            respond(blocks=blocks)

        else:
            respond(
                "*📱 /office text — SMS from Slack*\n\n"
                "`/office text send [number] [message]` — Send a text from the business line\n"
                "`/office text inbox` — View recent texts\n"
                "`/office text convo [number]` — View conversation with a number"
            )

    # ── /office reply [hcp|sms] [id/number] [message] — Quick reply ──
    elif sub == "reply":
        reply_sub, reply_rest = parse_sub(rest)

        # /office reply hcp [conversation_id] [message]
        if reply_sub == "hcp":
            parts = reply_rest.strip().split(None, 1)
            if len(parts) < 2:
                respond("Usage: `/office reply hcp [conversation_id] [message]`")
                return
            conv_id, body = parts[0], parts[1]
            result = reply_hcp_message(conv_id, body)
            if result["success"]:
                log_event("hcp_message", "HCP", f"Reply sent (conv {conv_id})", body[:200], "💬")
                respond(f"✅ *Reply sent via HCP*\n\n>{body}")
            else:
                respond(f"⚠️ Failed: {result['error']}")

        # /office reply sms [number] [message]
        elif reply_sub == "sms":
            parts = reply_rest.strip().split(None, 1)
            if len(parts) < 2:
                respond("Usage: `/office reply sms [phone number] [message]`")
                return
            phone, body = parts[0], parts[1]
            result = send_sms(phone, body)
            if result["success"]:
                log_event("text", "Twilio", f"Reply sent to {phone}", body[:200], "📤")
                respond(f"✅ *Reply sent to {phone}*\n\n>{body}")
            else:
                respond(f"⚠️ Failed: {result['error']}")

        else:
            respond(
                "*💬 /office reply — Quick Reply*\n\n"
                "`/office reply sms [number] [message]` — Reply to a text\n"
                "`/office reply hcp [conversation_id] [message]` — Reply to HCP message"
            )

    # ── /office profitability — Employee profit margins ──
    elif sub in ("profitability", "profit", "margins"):
        weeks_ago = 0
        if rest.strip():
            try:
                if rest.strip().lower() == "last":
                    weeks_ago = 1
                else:
                    weeks_ago = int(rest.strip())
            except ValueError:
                pass
        respond("📊 Pulling employee profitability data from HousecallPro... one moment.")
        report = build_profitability_report(weeks_ago)
        blocks = format_profitability_for_slack(report)
        try:
            app.client.chat_postMessage(
                channel=command.get("channel_id", CHANNEL_ANALYTICS),
                blocks=blocks,
                text=f"Employee Profitability Report — {report.get('week_label', 'This Week')}",
            )
        except Exception as e:
            respond(f"⚠️ Error posting report: {e}")

    # ── /office payrate — View or set employee hourly rates ──
    elif sub == "payrate":
        parts = rest.strip().split(" ", 1) if rest.strip() else []
        if not parts or parts[0].lower() == "list":
            rates = get_all_pay_rates()
            if rates:
                lines = [f"  • *{name.title()}:* ${rate:.2f}/hr" for name, rate in sorted(rates.items())]
                respond(f"*💵 Employee Pay Rates:*\n" + "\n".join(lines) + "\n\n_Use `/office payrate [name] [rate]` to update._")
            else:
                respond("No custom pay rates set. Using default rate. Set rates with `/office payrate [name] [rate]`")
        elif len(parts) == 2:
            try:
                emp_name = parts[0]
                rate = float(parts[1].replace("$", ""))
                set_pay_rate(emp_name, rate)
                respond(f"✅ Set *{emp_name.title()}*'s hourly rate to *${rate:.2f}/hr*")
            except ValueError:
                respond("⚠️ Usage: `/office payrate [employee_first_name] [hourly_rate]`\nExample: `/office payrate Sarah 19.50`")
        else:
            respond("⚠️ Usage:\n`/office payrate` — View all rates\n`/office payrate [name] [rate]` — Set a rate\nExample: `/office payrate Sarah 19.50`")

    # ── /office status — System status overview ──
    elif sub == "status":
        ai = get_ai_status()
        twilio = get_twilio_status()
        lead_sum = build_lead_summary()
        model_lines = "\n".join([f"  • {k}: {v}" for k, v in ai["models"].items()])
        respond(
            f"*⚙️ System Status — {BUSINESS_NAME}*\n\n"
            f"*AI Models:*\n{model_lines}\n\n"
            f"*Twilio SMS:* {'✅ Active' if twilio['configured'] else '⚠️ Not configured'} — {twilio['phone_number']}\n"
            f"  Unread texts: {twilio['unread']} | Conversations: {twilio['active_conversations']}\n\n"
            f"*Lead Monitor:* ✅ Active\n"
            f"  Total leads: {lead_sum.get('total', 0)} | Unreviewed: {lead_sum.get('unreviewed', 0)}\n\n"
            f"*Command Center:* ✅ Active\n"
            f"  Feed events: {len(get_feed(limit=200))} | Unread: {cc_unread_count()}\n\n"
            f"*HousecallPro:* {'✅ Connected' if HCP_API_KEY and HCP_API_KEY != 'your_housecallpro_api_key_here' else '⚠️ Not configured'}"
        )

    # ── /office emails — View email queue stats ──
    elif sub == "emails":
        stats = get_email_stats()
        respond(
            f"*Email Queue Status:*\n\n"
            f"  Pending review: *{stats['pending']}*\n"
            f"  Sent: *{stats['sent']}*\n"
            f"  Skipped: *{stats['skipped']}*\n\n"
            f"_Emails are auto-drafted on Mondays (win-backs) and Wednesdays (cold leads)._\n"
            f"_Review and approve them in #carolyn._"
        )

    # ── /office scheduler — View scheduler status ──
    elif sub == "scheduler":
        s = get_scheduler_status()
        respond(
            f"*Proactive Scheduler Status:*\n\n"
            f"  Running: {'✅ Yes' if s['running'] else '❌ No'}\n"
            f"  Morning Brief: *{s['morning_brief_time']}* daily\n"
            f"  EOD Summary: *{s['eod_summary_time']}* daily\n"
            f"  Friday Report: *{s['friday_report_time']}* Fridays\n"
            f"  Carolyn Phone: {s['carolyn_phone']}\n"
            f"  Twilio: {'✅ Configured' if s['twilio_configured'] else '⚠️ Not configured'}\n"
            f"  Tasks sent today: {len(s['tasks_sent_today'])}\n\n"
            f"_The bot automatically texts Carolyn briefs, drafts emails, and posts reports._"
        )

    else:
        respond(
            "*🏢 /office — Carolyn's Command Center*\n\n"
            "`/office brief` — AI-powered daily briefing\n"
            "`/office priorities` — Full prioritized action list\n"
            "`/office feed [filter]` — Unified event feed (all, lead, text, hcp_message, alert)\n"
            "`/office eod` — End-of-day summary\n"
            "`/office text send|inbox|convo` — Send/receive texts from business line\n"
            "`/office reply sms|hcp [id] [message]` — Quick reply to texts or HCP messages\n"
            "`/office profit [last]` — Employee profitability report (this week or last)\n"
            "`/office payrate [name] [rate]` — View/set hourly pay rates\n"
            "`/office emails` — Email queue status\n"
            "`/office scheduler` — Proactive scheduler status\n"
            "`/office status` — System status overview"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 8 — /carolyn  (meet | answer | profile | update | mood)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/carolyn")
def carolyn_cmd(ack, respond, command):
    ack()
    sub, rest = parse_sub(command.get("text", ""))

    # ── /carolyn meet ──
    if sub == "meet":
        profile = load_profile()
        if profile.get("onboarded") and rest.strip().lower() != "reset":
            respond(f"👋 Welcome back, {OFFICE_ASSISTANT_NAME}! Your profile is already set up.\nUse `/carolyn profile` to view it or `/carolyn meet reset` to start over.")
            return
        if rest.strip().lower() == "reset":
            profile["interview_step"] = 0
            profile["onboarded"] = False
            save_profile(profile)
        result = get_current_question(profile)
        if result is None:
            respond("✅ Profile complete! Use `/carolyn profile` to view.")
            return
        q, _ = result
        respond(q["question"])

    # ── /carolyn answer [text] ──
    elif sub == "answer":
        answer = rest.strip()
        if not answer:
            respond("Usage: `/carolyn answer [your answer]`")
            return
        profile = load_profile()
        msg, is_complete = process_interview_answer(profile, answer)
        respond(msg)

    # ── /carolyn profile ──
    elif sub == "profile":
        profile = load_profile()
        respond(blocks=format_profile_for_slack(profile))

    # ── /carolyn update [key] [value] ──
    elif sub == "update":
        parts = rest.strip().split(None, 1)
        if len(parts) < 2:
            respond("Usage: `/carolyn update [key] [value]`\nExample: `/carolyn update email_tone warm`\nKeys: `email_tone` `preferred_greeting` `sign_off` `response_urgency` `morning_brief` `priority_style` `escalation_style` `complaint_approach`")
            return
        key, value = parts[0], parts[1]
        if update_preference(key, value):
            respond(f"✅ Updated `{key}` to `{value}`")
        else:
            respond(f"⚠️ Unknown preference key: `{key}`")

    # ── /carolyn learn [category] [content] ──
    elif sub == "learn":
        parts = rest.strip().split(None, 1)
        if len(parts) < 2:
            cat_list = "\n".join([f"  `{k}` — {v}" for k, v in MEM_CATEGORIES.items()])
            respond(f"Usage: `/carolyn learn [category] [what to remember]`\n\nCategories:\n{cat_list}\n\nExamples:\n  `/carolyn learn preferences I like emails to be short and warm`\n  `/carolyn learn dont_do Stop sending alerts about unconfirmed jobs`\n  `/carolyn learn customer_notes Mrs. Henderson prefers Friday mornings`\n  `/carolyn learn email_style Never use the word 'valued' in emails`")
            return
        category, content = parts[0].lower(), parts[1]
        entry = mem_learn(category, content)
        if "error" in entry:
            respond(f"\u26a0\ufe0f {entry['error']}")
        else:
            respond(f"\u2705 Got it! I'll remember that.\n\n*Category:* {category}\n*Memory #{entry['id']}:* _{content}_\n\n_I'll apply this to everything I do from now on. To undo: `/carolyn forget {entry['id']}`_")

    # ── /carolyn forget [id or keyword] ──
    elif sub == "forget":
        identifier = rest.strip()
        if not identifier:
            respond("Usage: `/carolyn forget [memory # or keyword]`\nExample: `/carolyn forget 3` or `/carolyn forget alerts`")
            return
        result = mem_forget(identifier)
        if result["forgotten"] > 0:
            names = ", ".join([f"#{m['id']}" for m in result["items"]])
            respond(f"\u2705 Forgotten {result['forgotten']} memory(s): {names}\n\n_I won't apply these anymore._")
        else:
            respond(f"\u26a0\ufe0f No active memories matching '{identifier}'. Use `/carolyn memory all` to see what I know.")

    # ── /carolyn memory [category or 'all'] ──
    elif sub == "memory":
        category = rest.strip().lower() if rest.strip() else "all"
        if category == "stats":
            stats = get_memory_stats()
            cat_breakdown = "\n".join([f"  {k}: *{v}*" for k, v in stats['by_category'].items()]) if stats['by_category'] else "  _None yet_"
            respond(
                f"*Bot Memory Stats:*\n\n"
                f"  Active memories: *{stats['total_active']}*\n"
                f"  Total learned: *{stats['total_learned']}*\n"
                f"  Total forgotten: *{stats['total_forgotten']}*\n"
                f"  Last updated: {stats['last_updated'][:16]}\n\n"
                f"*By Category:*\n{cat_breakdown}"
            )
        else:
            memories = mem_recall(category=category if category != "all" else None)
            formatted = format_memories_for_slack(memories)
            respond(f"*What I Know{f' ({category})' if category != 'all' else ''}:*\n{formatted}")

    # ── /carolyn mood [mood] [note] ──
    elif sub == "mood":
        parts = rest.strip().split(None, 1)
        mood = parts[0] if parts else "neutral"
        note = parts[1] if len(parts) > 1 else ""
        entry = log_mood(mood, note)
        mood_responses = {
            "great": "That's wonderful to hear! 🌟 Let's channel that energy into knocking out your top priorities today.",
            "good": "Glad to hear it! 😊 A good day is a productive day. Let's make the most of it.",
            "okay": "Okay is okay! Sometimes steady wins the race. What's one thing I can help with to make today better?",
            "stressed": "I hear you. 💙 Let's take it one step at a time. Want me to pull up your priorities so we can tackle the most important thing first?",
            "tired": "Rest is important too. ☕ Let's focus on the essentials today and save the big projects for when you're recharged.",
            "frustrated": "I'm sorry you're feeling that way. 💪 Let's figure out what's causing it and see if I can help take something off your plate.",
            "excited": "Love that energy! 🚀 Let's put it to work. What are you most excited about?",
        }
        response = mood_responses.get(mood.lower(), f"Thanks for checking in! Your mood: {mood}. I'm here to help with whatever you need.")
        respond(f"😊 *Mood Check-In — {today()}*\n\nMood: *{mood}*{f' | Note: _{note}_' if note else ''}\n\n{response}")

    else:
        respond(
            "*\ud83d\udc64 /carolyn \u2014 Carolyn's Profile, Memory & Wellness*\n\n"
            "`/carolyn meet` \u2014 Start onboarding interview\n"
            "`/carolyn answer [text]` \u2014 Answer interview question\n"
            "`/carolyn profile` \u2014 View saved preferences\n"
            "`/carolyn update [key] [value]` \u2014 Update a preference\n"
            "`/carolyn learn [category] [text]` \u2014 Teach me something new\n"
            "`/carolyn forget [# or keyword]` \u2014 Make me forget something\n"
            "`/carolyn memory [category|all|stats]` \u2014 See what I know\n"
            "`/carolyn mood [mood] [note]` \u2014 Daily mood check-in\n"
            "  Moods: `great` `good` `okay` `stressed` `tired` `frustrated` `excited`"
        )


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 9 — /announce  (standalone — team broadcast)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/announce")
def announce(ack, respond, command):
    ack()
    msg = command.get("text", "").strip()
    if not msg:
        respond("Usage: `/announce Your message here`")
        return
    respond(f"📢 *Team Announcement from {BUSINESS_NAME}:*\n\n{msg}\n\n_— {OWNER_NAME}_")


# ═════════════════════════════════════════════════════════════════════════════
# COMMAND 10 — /cleanhelp  (full command reference)
# ═════════════════════════════════════════════════════════════════════════════

@app.command("/cleanhelp")
def clean_help(ack, respond):
    ack()
    respond(blocks=[
        {"type": "header", "text": {"type": "plain_text", "text": f"🧹 {BUSINESS_NAME} — Command Reference"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": (
            "*🔍 /leads — Lead Tools*\n"
            "`/leads find [category] [city]` — Find leads\n"
            "`/leads status` — Contacted leads\n"
            "`/leads inbox [platform]` — Unreviewed leads\n"
            "`/leads summary` — All-platform summary\n\n"

            "*👷 /job — Job Management*\n"
            "`/job assign @emp | addr | service | time`\n"
            "`/job list [status]` — View jobs\n"
            "`/job checkin JOB-XXXX` / `/job checkout JOB-XXXX`\n\n"

            "*👥 /customer — Customer Comms*\n"
            "`/customer new Name | Phone | Email | Addr | Service`\n"
            "`/customer followup Name | Phone | Service`\n"
            "`/customer complete Name | Addr | Service | Employee`\n\n"

            "*📊 /hcp — HousecallPro*\n"
            "`/hcp jobs [status]` — Pull jobs\n"
            "`/hcp customers [search]` — Search customers\n"
            "`/hcp leads` — Pipeline leads\n"
            "`/hcp analysis` — Full gap analysis\n\n"

            "*🤖 /ai — AI-Powered Tools*\n"
            "`/ai draft [type] [Name] [context]` — AI email\n"
            "`/ai complaint [Name] [issue]` — Complaint response\n"
            "`/ai recommend [topic]` — Business recommendations\n"
            "`/ai status` — AI model status\n\n"

            "*🛡️ /service — Customer Service*\n"
            "`/service script [scenario]` — Response script\n"
            "`/service standards` — Service standards\n"
            "`/service qa [job_type]` — QA checklist\n"
            "`/service wow [Name]` — Wow moment idea\n\n"

            "*🏢 /office — Carolyn's Command Center*\n"
            "`/office brief` — Daily briefing\n"
            "`/office priorities` — Priority action list\n"
            "`/office feed [filter]` — Unified event feed\n"
            "`/office eod` — End-of-day summary\n"
            "`/office text send|inbox|convo` — SMS from Slack\n"
            "`/office reply sms|hcp` — Quick reply\n"
            "`/office status` — System status\n\n"

            "*👤 /carolyn — Profile & Wellness*\n"
            "`/carolyn meet` — Onboarding interview\n"
            "`/carolyn answer [text]` — Answer question\n"
            "`/carolyn profile` — View preferences\n"
            "`/carolyn update [key] [value]` — Update pref\n"
            "`/carolyn mood [mood] [note]` — Mood check-in\n\n"

            "*📢 /announce [message]* — Team broadcast\n"
            "*❓ /cleanhelp* — This menu"
        )}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{BUSINESS_NAME} • {SERVICE_AREA} • {BUSINESS_PHONE}_"}]},
    ])


# ═════════════════════════════════════════════════════════════════════════════
# BUTTON ACTIONS (shared across modules)
# ═════════════════════════════════════════════════════════════════════════════

@app.action("email_approved")
def email_approved(ack, body, respond):
    ack()
    val = body["actions"][0]["value"]
    parts = val.split("|")
    respond(f"✅ *Email approved and marked as sent* by {OFFICE_ASSISTANT_NAME}\n📧 `{parts[0]}` → {parts[1] if len(parts)>1 else 'customer'} | 🕐 {now_ts()}")

@app.action("regenerate_email")
def regenerate_email(ack, body, respond):
    ack()
    val = body["actions"][0]["value"]
    parts = val.split("|")
    respond(f"🔄 Use `/ai draft {parts[0]} {parts[1] if len(parts)>1 else ''}` to regenerate.")

@app.action("show_email_menu")
def show_email_menu_action(ack, body, respond):
    ack()
    respond(
        "*✉️ AI-Powered Email Templates:*\n"
        "`/ai draft estimate_followup [Name]` — Follow up on estimates\n"
        "`/ai draft win_back [Name]` — Re-engage cancelled customers\n"
        "`/ai draft reengagement [Name]` — Re-engage lapsed customers\n"
        "`/ai draft airbnb_pitch [Name]` — Pitch Airbnb/STR hosts\n"
        "`/ai draft review_request [Name]` — Request a Google review\n"
        "`/ai draft upsell_carpet_window [Name]` — Upsell add-ons\n"
        "`/ai draft post_construction [Name]` — Pitch builders\n"
        "`/ai draft complaint_response [Name] [issue]` — Handle complaint\n"
        "`/ai draft thank_you [Name]` — Post-job thank you\n"
        "`/ai draft welcome [Name]` — Welcome new customer\n"
    )

@app.action("show_recovery")
def show_recovery(ack, body, respond):
    ack()
    respond(blocks=format_recovery_protocol_for_slack())

@app.action("mark_lead_reviewed")
def mark_reviewed_action(ack, body, respond):
    ack()
    lead_hash = body["actions"][0]["value"]
    if mark_lead_reviewed(lead_hash):
        respond("✅ Lead marked as reviewed.")
    else:
        respond("⚠️ Lead not found.")

@app.action("draft_lead_email")
def draft_lead_email_action(ack, body, respond):
    ack()
    val = body["actions"][0]["value"]
    parts = val.split("|")
    respond(f"Use `/ai draft {parts[0]} {parts[1] if len(parts)>1 else ''}` to draft an AI-powered email.")

@app.action("call_lead")
def call_lead_action(ack, body, respond):
    ack()
    phone = body["actions"][0]["value"]
    respond(f"📞 Call {phone} now. Remember: warmth first, listen actively, and say 'My pleasure!'")

@app.action("show_priorities")
def show_priorities_action(ack, body, respond):
    ack()
    priorities = build_priority_list()
    lines = [f"{item['priority']}. {item['icon']} *[{item['category']}]* {item['title']}\n   _{item['detail']}_\n   👉 {item['action']}" for item in priorities]
    respond(f"*📋 Full Priority List for {OFFICE_ASSISTANT_NAME}:*\n\n" + "\n\n".join(lines))

@app.action("run_hcp_analysis")
def run_hcp_analysis_action(ack, body, respond):
    ack()
    respond("⏳ Use `/hcp analysis` for the full report.")

@app.action("show_lead_inbox")
def show_lead_inbox_action(ack, body, respond):
    ack()
    respond("📬 Use `/leads inbox` to view all unreviewed leads across platforms.")

@app.action("update_pref_menu")
def update_pref_menu(ack, body, respond):
    ack()
    respond("Use `/carolyn update [key] [value]` to update a preference.\nKeys: `email_tone` `preferred_greeting` `sign_off` `response_urgency` `morning_brief` `priority_style` `escalation_style` `complaint_approach`")

@app.action("mood_checkin")
def mood_checkin_action(ack, body, respond):
    ack()
    respond("Use `/carolyn mood [mood] [optional note]`\nExamples: `/carolyn mood great Feeling productive today!` or `/carolyn mood stressed Too many things at once`")

# ── New v4 button actions ──

@app.action("mark_all_feed_read")
def mark_all_feed_read_action(ack, body, respond):
    ack()
    mark_all_read()
    respond("✅ All feed events marked as read.")

@app.action("refresh_feed")
def refresh_feed_action(ack, body, respond):
    ack()
    filter_type = body["actions"][0]["value"]
    if filter_type == "all":
        filter_type = None
    events = get_feed(limit=15, event_type=filter_type)
    if not events:
        respond("📋 Feed is empty.")
        return
    lines = [f"{e['icon']} *{e['title']}* — _{e['source']} • {e['timestamp']}_" for e in events]
    respond("📋 *Refreshed Feed:*\n\n" + "\n".join(lines))

@app.action("reply_sms")
def reply_sms_action(ack, body, respond):
    ack()
    phone = body["actions"][0]["value"]
    respond(f"💬 Reply to {phone}:\n`/office reply sms {phone} [your message]`")

@app.action("call_customer")
def call_customer_action(ack, body, respond):
    ack()
    phone = body["actions"][0]["value"]
    respond(f"📞 Call {phone} now.\n\nRemember: warmth first, listen actively, and say 'My pleasure!'\n\n_Use `/service script new_inquiry` for a phone script._")

@app.action("approve_email")
def approve_email_action(ack, body, respond):
    ack()
    try:
        val = json.loads(body["actions"][0]["value"])
        email_type = val.get("type", "")
        name = val.get("name", "")
        email = val.get("email", "")
        # Extract personal note from the input block
        personal_note = ""
        state_values = body.get("state", {}).get("values", {})
        for block_id, block_data in state_values.items():
            if "personal_note_input" in block_data:
                personal_note = block_data["personal_note_input"].get("value", "") or ""
                break
        key = f"{email_type}_{name}"
        if personal_note:
            queue_email(key, {"type": email_type, "name": name, "email": email, "personal_note": personal_note})
        success, msg = send_via_mailchimp(key, email)
        if success:
            respond(f"✅ *Email sent to {name}* ({email})\n\n{f'Personal note added: _{personal_note}_' if personal_note else '_No personal note added_'}\n\n_Sent via Mailchimp_")
        else:
            respond(f"⚠️ Failed to send: {msg}\n\n_You can try again or send manually from mtpremiumhousecare@gmail.com_")
    except Exception as e:
        respond(f"⚠️ Error processing approval: {str(e)}")

@app.action("skip_email")
def skip_email_action(ack, body, respond):
    ack()
    name = body["actions"][0]["value"]
    ea_skip_email(f"win_back_{name}")
    ea_skip_email(f"follow_up_{name}")
    respond(f"⏭️ Skipped email for {name}.")

@app.action("personal_note_input")
def personal_note_input_action(ack):
    ack()

@app.action("mark_sms_handled")
def mark_sms_handled_action(ack, body, respond):
    ack()
    respond("✅ Text marked as handled.")

@app.action("reply_hcp_message")
def reply_hcp_message_action(ack, body, respond):
    ack()
    conv_id = body["actions"][0]["value"]
    respond(f"💬 Reply to this HCP conversation:\n`/office reply hcp {conv_id} [your message]`")

@app.action("mark_hcp_handled")
def mark_hcp_handled_action(ack, body, respond):
    ack()
    respond("✅ HCP message marked as handled.")


# ═════════════════════════════════════════════════════════════════════════════
# NATURAL LANGUAGE CHAT — @mentions and DMs
# ═════════════════════════════════════════════════════════════════════════════

def _chat_ai_func(user_message: str, system_prompt: str) -> str:
    """Wrapper around ai_route_call for chat_handler's ai_func parameter."""
    return ai_route_call("reasoning", system_prompt, user_message, temperature=0.7, max_tokens=800)


def _chat_runner(action_hint: str):
    """Map a chat action_hint to the function that actually does the work.
    Returns {"text": str, "blocks": list|None, "file": dict|None} or None.
    A "file" dict has keys: content, filename, title."""
    if action_hint == "hcp_analysis":
        text, blocks = build_hcp_analysis()
        return {"text": text, "blocks": blocks}
    if action_hint.startswith("lost_customers_csv"):
        # action_hint format: "lost_customers_csv" or "lost_customers_csv:90"
        threshold = 60
        if ":" in action_hint:
            try:
                threshold = max(1, int(action_hint.split(":", 1)[1]))
            except ValueError:
                pass
        csv_text, result = build_lapsed_customers_csv(threshold)
        if csv_text is None:
            return {"text": f"⚠️ Could not pull customers: {result}"}
        count = result
        if count == 0:
            return {"text": f"✅ No customers inactive {threshold}+ days. Pipeline looks healthy."}
        return {
            "text": f"📎 Full lost-customer report — {count} customers inactive {threshold}+ days. See attached CSV.",
            "file": {
                "content": csv_text,
                "filename": f"lost_customers_{threshold}d_{datetime.date.today().isoformat()}.csv",
                "title": f"Lost Customers ({threshold}+ days inactive)",
            },
        }
    return None


def _post_chat_result(result, channel, say, thread_ts=None):
    """Send a chat_handler result, uploading any file attachment to Slack."""
    fi = result.get("file")
    text = result.get("text") or ""
    if fi and channel:
        try:
            app.client.files_upload_v2(
                channel=channel,
                content=fi["content"],
                filename=fi["filename"],
                title=fi.get("title"),
                initial_comment=text,
                thread_ts=thread_ts,
            )
            return
        except Exception as e:
            text = f"{text}\n\n⚠️ Couldn't upload the file: {e}"
    if thread_ts:
        say(text=text, blocks=result.get("blocks"), thread_ts=thread_ts)
    else:
        say(text=text, blocks=result.get("blocks"))


def _get_user_display_name(client, user_id: str) -> str:
    """Look up a Slack user's display name."""
    try:
        info = client.users_info(user=user_id)
        profile = info["user"]["profile"]
        return profile.get("display_name") or profile.get("real_name") or "there"
    except Exception:
        return "there"


# Dedup recently-handled events. Slack can redeliver an event if the handler
# is slow (e.g. an AI call takes >3s), which caused the duplicate replies
# Carolyn was seeing.
_HANDLED_EVENTS = {}
_HANDLED_TTL_SEC = 60


def _already_handled(event) -> bool:
    key = event.get("client_msg_id") or event.get("event_ts") or event.get("ts")
    if not key:
        return False
    now = time.time()
    # prune old entries opportunistically
    if len(_HANDLED_EVENTS) > 500:
        for k, t in list(_HANDLED_EVENTS.items()):
            if now - t > _HANDLED_TTL_SEC:
                _HANDLED_EVENTS.pop(k, None)
    if key in _HANDLED_EVENTS and now - _HANDLED_EVENTS[key] < _HANDLED_TTL_SEC:
        return True
    _HANDLED_EVENTS[key] = now
    return False


@app.event("app_mention")
def handle_app_mention(event, say, client):
    """Respond when someone @mentions the bot in a channel."""
    if _already_handled(event):
        return
    try:
        raw_text = event.get("text", "")
        # Strip the bot's @mention from the message
        import re as _re
        text = _re.sub(r"<@[A-Z0-9]+>", "", raw_text).strip()
        if not text:
            text = "hi"
        user_id = event.get("user", "")
        user_name = _get_user_display_name(client, user_id)
        result = build_chat_response(text, user_name=user_name, ai_func=_chat_ai_func,
                                      user_id=user_id, runner_func=_chat_runner)
        _post_chat_result(result, event.get("channel"), say, thread_ts=event.get("ts"))
    except Exception as e:
        say(text=f"Sorry, I hit an error: {str(e)}", thread_ts=event.get("ts"))


@app.event("message")
def handle_dm(event, say, client):
    """Respond to direct messages sent to the bot."""
    # Only respond to DMs (channel type 'im'), ignore bot messages and edits
    if event.get("channel_type") != "im":
        return
    if event.get("subtype") in ("bot_message", "message_changed", "message_deleted"):
        return
    if event.get("bot_id"):
        return
    if _already_handled(event):
        return
    try:
        text = event.get("text", "").strip()
        if not text:
            return
        user_id = event.get("user", "")
        user_name = _get_user_display_name(client, user_id)
        result = build_chat_response(text, user_name=user_name, ai_func=_chat_ai_func,
                                      user_id=user_id, runner_func=_chat_runner)
        _post_chat_result(result, event.get("channel"), say)
    except Exception as e:
        say(text=f"Sorry, I hit an error: {str(e)}")


# ═════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"🧹 {BUSINESS_NAME} Slack Bot (v5.1 — Natural Language Chat) starting...")
    print(f"📍 Service areas: {SERVICE_AREA}")
    print(f"🔑 HousecallPro API: {'✅' if HCP_API_KEY and HCP_API_KEY != 'your_housecallpro_api_key_here' else '⚠️  Not configured'}")
    # Show AI status
    ai = get_ai_status()
    for model, status in ai["models"].items():
        print(f"🤖 {model}: {status}")
    # Show memory status
    mem_stats = get_memory_stats()
    print(f"🧠 Bot Memory: {mem_stats['total_active']} active memories")
    # Start lead monitor polling in background (every 15 min)
    print("🔄 Starting lead monitor (polling every 15 min)...")
    start_polling(interval_seconds=900)
    # Start command center (smart alerts every 10 min, HCP messages every 5 min, EOD at 5pm)
    print("🧠 Starting Command Center (alerts, HCP messages, EOD summary)...")
    start_command_center()
    # Start proactive scheduler (morning brief at 9:30am, EOD at 5pm, email drafts Mon/Wed/Fri)
    print("📅 Starting Proactive Scheduler (morning brief 9:30am, emails Mon/Wed/Fri)...")
    start_proactive_scheduler()
    # Start Twilio SMS webhook server (receives incoming texts)
    twilio_status = get_twilio_status()
    if twilio_status["configured"]:
        print(f"📱 Starting Twilio SMS webhook server on port 5050...")
        start_webhook_server(port=5050)
    else:
        print("📱 Twilio SMS: ⚠️  Not configured (add credentials to .env when ready)")
    print("")
    print("═" * 55)
    print(f"  ⚡️ {BUSINESS_NAME} Bot v5.1 is LIVE")
    print(f"  👩 Carolyn's Command Center: ACTIVE")
    print(f"  📋 Unified Feed: ACTIVE")
    print(f"  🚨 Smart Alerts: ACTIVE (every 10 min)")
    print(f"  💬 HCP Messages: ACTIVE (every 5 min)")
    print(f"  📱 Twilio SMS: {'ACTIVE' if twilio_status['configured'] else 'WAITING FOR CONFIG'}")
    print(f"  📅 Proactive Scheduler: ACTIVE")
    print(f"     Morning Brief: 9:30 AM daily")
    print(f"     EOD Summary: 5:00 PM daily")
    print(f"     Email Drafts: Mon/Wed/Fri 10:00 AM")
    print(f"     Weekly Report: Friday 4:00 PM")
    print(f"  📧 Email Automation: ACTIVE (Mailchimp)")
    print(f"  🧠 Bot Memory: {mem_stats['total_active']} memories loaded")
    print(f"  💬 Natural Language Chat: ACTIVE (@mentions + DMs)")
    print(f"  🌅 EOD Summary: ACTIVE (5:00 PM daily)")
    print("═" * 55)
    print("")
    handler = SocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    handler.start()
