"""
Montana Premium House Care — Proactive Scheduler
=================================================
Runs automated tasks on a schedule so Carolyn never has to ask.
The bot comes to her — via text (Twilio) and Slack.

Schedule:
  - 9:30 AM MT daily: Morning Brief texted to Carolyn + posted in #carolyn
  - 5:00 PM MT daily: End-of-Day Summary texted + posted
  - Monday 9:30 AM: Weekly lost customer & cold lead email drafts
  - Wednesday 9:30 AM: Mid-week cold lead follow-up drafts
  - Friday 4:00 PM: Weekly employee profitability report
"""

import os
import time
import datetime
import threading
import json
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN", "")
CAROLYN_CHANNEL     = os.getenv("SLACK_CAROLYN_CHANNEL", "#carolyn")
CAROLYN_PHONE       = os.getenv("CAROLYN_PHONE", "")  # Carolyn's number to text
BUSINESS_PHONE      = os.getenv("BUSINESS_PHONE", "406-599-2699")
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
MORNING_BRIEF_TIME  = os.getenv("MORNING_BRIEF_TIME", "09:30")  # 24h format, MT
EOD_SUMMARY_TIME    = os.getenv("EOD_SUMMARY_TIME", "17:00")
FRIDAY_REPORT_TIME  = os.getenv("FRIDAY_REPORT_TIME", "16:00")

# Track what we've already sent today to avoid duplicates
_sent_today = {}


def _reset_daily_tracker():
    """Reset the daily tracker at midnight."""
    global _sent_today
    _sent_today = {}


def _already_sent(task_key: str) -> bool:
    """Check if a task has already been sent today."""
    today = datetime.date.today().isoformat()
    key = f"{today}:{task_key}"
    if key in _sent_today:
        return True
    _sent_today[key] = True
    return False


# ── Twilio Text Helper ───────────────────────────────────────────────────────

def _text_carolyn(message: str) -> bool:
    """Send a text message to Carolyn via Twilio."""
    if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER, CAROLYN_PHONE]):
        print("  ⚠️  Twilio or Carolyn phone not configured — skipping text")
        return False

    try:
        r = requests.post(
            f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_ACCOUNT_SID}/Messages.json",
            auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN),
            data={
                "To": CAROLYN_PHONE,
                "From": TWILIO_PHONE_NUMBER,
                "Body": message[:1600],  # Twilio limit
            },
            timeout=15,
        )
        return r.status_code in (200, 201)
    except Exception as e:
        print(f"  ⚠️  Failed to text Carolyn: {e}")
        return False


def _post_to_slack(channel: str, text: str, blocks: list = None):
    """Post a message to a Slack channel."""
    if not SLACK_BOT_TOKEN:
        return
    payload = {"channel": channel, "text": text}
    if blocks:
        payload["blocks"] = blocks
    try:
        requests.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
    except Exception:
        pass


# ── HCP Data Helpers ─────────────────────────────────────────────────────────

HCP_API_KEY = os.getenv("HOUSECALLPRO_API_KEY", "")
HCP_BASE = "https://api.housecallpro.com"

def _hcp_get(path, params=None):
    """Make a GET request to HousecallPro API."""
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return None, "HCP not configured"
    headers = {"Authorization": f"Token {HCP_API_KEY}", "Accept": "application/json"}
    try:
        r = requests.get(f"{HCP_BASE}{path}", headers=headers, params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _build_morning_brief() -> str:
    """Build the morning brief text message content."""
    today = datetime.date.today()
    brief_lines = [f"Good morning, Carolyn! Here's your brief for {today.strftime('%A, %B %d')}:\n"]

    # Today's jobs
    jobs_data, err = _hcp_get("/jobs", params={"page_size": 100})
    if not err and jobs_data:
        all_jobs = jobs_data.get("jobs", [])
        today_jobs = []
        for j in all_jobs:
            sched = (j.get("schedule") or {}).get("scheduled_start")
            if sched and sched[:10] == today.isoformat():
                today_jobs.append(j)
        brief_lines.append(f"JOBS TODAY: {len(today_jobs)}")
        for j in today_jobs[:5]:
            cust = j.get("customer", {})
            name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Unknown"
            job_type = (j.get("job_type") or {}).get("name", "Service")
            brief_lines.append(f"  - {name}: {job_type}")
        if len(today_jobs) > 5:
            brief_lines.append(f"  + {len(today_jobs) - 5} more")

        # Uninvoiced
        uninvoiced = [j for j in all_jobs if j.get("invoice_status") == "uninvoiced" and j.get("work_status") == "completed"]
        if uninvoiced:
            brief_lines.append(f"\nNEEDS INVOICE: {len(uninvoiced)} completed jobs")

    # Open estimates
    est_data, est_err = _hcp_get("/estimates", params={"page_size": 100})
    if not est_err and est_data:
        open_est = [e for e in est_data.get("estimates", []) if e.get("status") not in ("approved", "converted_to_job")]
        if open_est:
            brief_lines.append(f"OPEN ESTIMATES: {len(open_est)}")

    # Lapsed customers
    cust_data, cust_err = _hcp_get("/customers", params={"page_size": 100})
    if not cust_err and cust_data:
        lapsed = 0
        for c in cust_data.get("customers", []):
            last_job = c.get("last_job_date")
            if last_job:
                try:
                    days_since = (today - datetime.date.fromisoformat(last_job[:10])).days
                    if days_since > 60:
                        lapsed += 1
                except (ValueError, TypeError):
                    pass
        if lapsed:
            brief_lines.append(f"LAPSED CUSTOMERS (60+ days): {lapsed}")

    brief_lines.append("\nCheck Slack #carolyn for full details and action items.")
    return "\n".join(brief_lines)


def _build_eod_summary() -> str:
    """Build the end-of-day summary text."""
    today = datetime.date.today()
    lines = [f"End of day wrap-up for {today.strftime('%A, %B %d')}:\n"]

    jobs_data, err = _hcp_get("/jobs", params={"page_size": 100})
    if not err and jobs_data:
        all_jobs = jobs_data.get("jobs", [])
        completed_today = []
        scheduled_tomorrow = []
        tomorrow = (today + datetime.timedelta(days=1)).isoformat()

        for j in all_jobs:
            sched = (j.get("schedule") or {}).get("scheduled_start")
            if j.get("work_status") == "completed" and sched and sched[:10] == today.isoformat():
                completed_today.append(j)
            if sched and sched[:10] == tomorrow:
                scheduled_tomorrow.append(j)

        lines.append(f"COMPLETED TODAY: {len(completed_today)} jobs")
        lines.append(f"SCHEDULED TOMORROW: {len(scheduled_tomorrow)} jobs")

        for j in scheduled_tomorrow[:5]:
            cust = j.get("customer", {})
            name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip() or "Unknown"
            job_type = (j.get("job_type") or {}).get("name", "Service")
            lines.append(f"  - {name}: {job_type}")

    lines.append("\nGreat work today! See you tomorrow.")
    return "\n".join(lines)


def _build_lost_customer_list() -> list:
    """Identify customers who haven't booked in 60+ days for win-back emails."""
    today = datetime.date.today()
    lost = []
    cust_data, err = _hcp_get("/customers", params={"page_size": 200})
    if err or not cust_data:
        return lost

    for c in cust_data.get("customers", []):
        last_job = c.get("last_job_date")
        if not last_job:
            continue
        try:
            days_since = (today - datetime.date.fromisoformat(last_job[:10])).days
            if days_since > 60:
                name = f"{c.get('first_name', '')} {c.get('last_name', '')}".strip()
                email = c.get("email", "")
                if name and email:
                    lost.append({
                        "name": name,
                        "email": email,
                        "days_since": days_since,
                        "last_job_date": last_job[:10],
                    })
        except (ValueError, TypeError):
            pass

    # Sort by most recently lapsed first
    lost.sort(key=lambda x: x["days_since"])
    return lost


def _build_cold_lead_list() -> list:
    """Identify estimates that were never converted to jobs."""
    cold = []
    est_data, err = _hcp_get("/estimates", params={"page_size": 200})
    if err or not est_data:
        return cold

    for e in est_data.get("estimates", []):
        if e.get("status") in ("approved", "converted_to_job"):
            continue
        cust = e.get("customer", {})
        name = f"{cust.get('first_name', '')} {cust.get('last_name', '')}".strip()
        email = cust.get("email", "")
        if name:
            cold.append({
                "name": name,
                "email": email,
                "estimate_total": e.get("total_amount", "?"),
                "created_at": (e.get("created_at") or "")[:10],
                "status": e.get("status", "pending"),
            })

    return cold


# ── Scheduled Task Runners ───────────────────────────────────────────────────

def run_morning_brief():
    """Generate and send the morning brief to Carolyn."""
    if _already_sent("morning_brief"):
        return
    print(f"  📋 Generating morning brief...")
    brief_text = _build_morning_brief()

    # Text Carolyn
    _text_carolyn(brief_text)

    # Post to Slack with richer formatting
    _post_to_slack(CAROLYN_CHANNEL, f"*Morning Brief — {datetime.date.today().strftime('%A, %B %d')}*\n\n{brief_text}")
    print(f"  ✅ Morning brief sent to Carolyn")


def run_eod_summary():
    """Generate and send the end-of-day summary."""
    if _already_sent("eod_summary"):
        return
    print(f"  📋 Generating end-of-day summary...")
    eod_text = _build_eod_summary()

    _text_carolyn(eod_text)
    _post_to_slack(CAROLYN_CHANNEL, f"*End of Day Summary — {datetime.date.today().strftime('%A, %B %d')}*\n\n{eod_text}")
    print(f"  ✅ EOD summary sent to Carolyn")


def run_email_drafts(ai_draft_func=None):
    """
    Generate win-back and cold lead email drafts for Carolyn's review.
    Called on Monday and Wednesday mornings.

    ai_draft_func: a callable(draft_type, customer_name) that returns AI-drafted text.
                   Passed in from bot.py to use the ai_engine.
    """
    today = datetime.date.today()
    day_name = today.strftime("%A")

    # Monday: Lost customer win-backs
    if day_name == "Monday" and not _already_sent("monday_winbacks"):
        lost = _build_lost_customer_list()
        if lost:
            summary = f"I found {len(lost)} customers who haven't booked in 60+ days. I've drafted win-back emails for the top {min(len(lost), 10)}. Check #carolyn to review and approve.\n\nTop lapsed:"
            for c in lost[:5]:
                summary += f"\n  - {c['name']} ({c['days_since']} days, last: {c['last_job_date']})"

            _text_carolyn(summary)
            _post_to_slack(CAROLYN_CHANNEL, f"*Win-Back Email Drafts Ready*\n\n{summary}\n\nReply with `/ai draft win_back [Name]` to see each draft, or I'll post them below for your review.")

            # Post individual drafts to Slack for review
            if ai_draft_func:
                for c in lost[:10]:
                    try:
                        draft = ai_draft_func("win_back", c["name"])
                        blocks = [
                            {"type": "header", "text": {"type": "plain_text", "text": f"Draft: Win-Back Email for {c['name']}"}},
                            {"type": "context", "elements": [
                                {"type": "mrkdwn", "text": f"_{c['days_since']} days since last booking | Last job: {c['last_job_date']} | Email: {c.get('email', 'N/A')}_"}
                            ]},
                            {"type": "section", "text": {"type": "mrkdwn", "text": draft[:2900]}},
                            {"type": "input", "block_id": f"personal_note_{c['name'].replace(' ', '_')}", "element": {
                                "type": "plain_text_input",
                                "action_id": "personal_note_input",
                                "placeholder": {"type": "plain_text", "text": "Add a personal note here (e.g., 'Hope the kids are doing well!')"},
                                "multiline": False,
                            }, "label": {"type": "plain_text", "text": "Your Personal Touch"}},
                            {"type": "actions", "elements": [
                                {"type": "button", "text": {"type": "plain_text", "text": "Approve & Send"}, "style": "primary", "value": json.dumps({"type": "win_back", "name": c["name"], "email": c.get("email", "")}), "action_id": "approve_email"},
                                {"type": "button", "text": {"type": "plain_text", "text": "Skip"}, "value": c["name"], "action_id": "skip_email"},
                            ]},
                        ]
                        _post_to_slack(CAROLYN_CHANNEL, f"Draft win-back for {c['name']}", blocks=blocks)
                    except Exception as e:
                        print(f"  ⚠️  Failed to draft email for {c['name']}: {e}")

            print(f"  ✅ Monday win-back drafts posted for Carolyn")

    # Wednesday: Cold lead follow-ups
    if day_name == "Wednesday" and not _already_sent("wednesday_coldleads"):
        cold = _build_cold_lead_list()
        if cold:
            summary = f"I found {len(cold)} unconverted estimates (cold leads). I've drafted follow-up emails for the top {min(len(cold), 10)}. Check #carolyn to review.\n\nTop cold leads:"
            for c in cold[:5]:
                summary += f"\n  - {c['name']} (Est: ${c['estimate_total']}, sent: {c['created_at']})"

            _text_carolyn(summary)
            _post_to_slack(CAROLYN_CHANNEL, f"*Cold Lead Follow-Up Drafts Ready*\n\n{summary}")

            if ai_draft_func:
                for c in cold[:10]:
                    try:
                        draft = ai_draft_func("follow_up", c["name"])
                        blocks = [
                            {"type": "header", "text": {"type": "plain_text", "text": f"Draft: Follow-Up for {c['name']}"}},
                            {"type": "context", "elements": [
                                {"type": "mrkdwn", "text": f"_Estimate: ${c['estimate_total']} | Sent: {c['created_at']} | Status: {c['status']}_"}
                            ]},
                            {"type": "section", "text": {"type": "mrkdwn", "text": draft[:2900]}},
                            {"type": "input", "block_id": f"personal_note_{c['name'].replace(' ', '_')}", "element": {
                                "type": "plain_text_input",
                                "action_id": "personal_note_input",
                                "placeholder": {"type": "plain_text", "text": "Add a personal note (e.g., 'We'd love to take care of your home!')"},
                                "multiline": False,
                            }, "label": {"type": "plain_text", "text": "Your Personal Touch"}},
                            {"type": "actions", "elements": [
                                {"type": "button", "text": {"type": "plain_text", "text": "Approve & Send"}, "style": "primary", "value": json.dumps({"type": "follow_up", "name": c["name"], "email": c.get("email", "")}), "action_id": "approve_email"},
                                {"type": "button", "text": {"type": "plain_text", "text": "Skip"}, "value": c["name"], "action_id": "skip_email"},
                            ]},
                        ]
                        _post_to_slack(CAROLYN_CHANNEL, f"Draft follow-up for {c['name']}", blocks=blocks)
                    except Exception as e:
                        print(f"  ⚠️  Failed to draft email for {c['name']}: {e}")

            print(f"  ✅ Wednesday cold lead drafts posted for Carolyn")

    # Friday: Weekly profitability report
    if day_name == "Friday" and not _already_sent("friday_profit"):
        try:
            from employee_profitability import build_profitability_report
            report = build_profitability_report(weeks_ago=0)
            if "error" not in report:
                text_summary = f"Weekly Employee Profitability Report ({report.get('week_label', 'This Week')}):\n"
                totals = report.get("totals", {})
                text_summary += f"\nTotal Jobs: {totals.get('total_jobs', 0)}"
                text_summary += f"\nTotal Revenue: ${totals.get('total_revenue', 0):,.2f}"
                text_summary += f"\nTotal Labor Cost: ${totals.get('total_labor_cost', 0):,.2f}"
                text_summary += f"\nGross Profit: ${totals.get('total_gross_profit', 0):,.2f}"
                text_summary += f"\nOverall Margin: {totals.get('overall_margin', 0)}%"

                for emp in report.get("employees", [])[:5]:
                    if emp.get("jobs_completed", 0) > 0:
                        text_summary += f"\n\n{emp['name']}: {emp['jobs_completed']} jobs, ${emp['revenue_generated']:,.2f} rev, {emp['profit_margin']}% margin"

                insights = report.get("insights", [])
                if insights:
                    text_summary += "\n\nInsights:"
                    for i in insights[:3]:
                        text_summary += f"\n  {i}"

                _text_carolyn(text_summary)
                _post_to_slack(CAROLYN_CHANNEL, f"*Weekly Employee Profitability Report*\n\n{text_summary}")
                print(f"  ✅ Friday profitability report sent to Carolyn")
        except Exception as e:
            print(f"  ⚠️  Failed to generate Friday report: {e}")


# ── Main Scheduler Loop ──────────────────────────────────────────────────────

_scheduler_running = False

def start_proactive_scheduler(ai_draft_func=None):
    """
    Start the background scheduler that checks the clock every 60 seconds
    and fires tasks at the right times.
    """
    global _scheduler_running
    if _scheduler_running:
        return
    _scheduler_running = True

    def _loop():
        last_date = ""
        while True:
            try:
                now = datetime.datetime.now()
                current_time = now.strftime("%H:%M")
                current_date = now.strftime("%Y-%m-%d")

                # Reset daily tracker at midnight
                if current_date != last_date:
                    _reset_daily_tracker()
                    last_date = current_date

                # Morning brief at configured time (default 9:30 AM)
                if current_time == MORNING_BRIEF_TIME:
                    run_morning_brief()
                    # Also run email drafts (Monday/Wednesday)
                    run_email_drafts(ai_draft_func=ai_draft_func)

                # EOD summary at configured time (default 5:00 PM)
                if current_time == EOD_SUMMARY_TIME:
                    run_eod_summary()

                # Friday profitability report
                if now.strftime("%A") == "Friday" and current_time == FRIDAY_REPORT_TIME:
                    run_email_drafts(ai_draft_func=ai_draft_func)  # Triggers Friday report

            except Exception as e:
                print(f"  ⚠️  Scheduler error: {e}")

            time.sleep(60)  # Check every minute

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"  ⏰ Proactive scheduler started (Brief: {MORNING_BRIEF_TIME}, EOD: {EOD_SUMMARY_TIME})")
    return t


def get_scheduler_status() -> dict:
    """Return the current scheduler status."""
    return {
        "running": _scheduler_running,
        "morning_brief_time": MORNING_BRIEF_TIME,
        "eod_summary_time": EOD_SUMMARY_TIME,
        "friday_report_time": FRIDAY_REPORT_TIME,
        "carolyn_phone": CAROLYN_PHONE if CAROLYN_PHONE else "Not configured",
        "twilio_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER),
        "tasks_sent_today": list(_sent_today.keys()),
    }
