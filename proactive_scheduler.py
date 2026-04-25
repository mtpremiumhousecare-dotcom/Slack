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

from email_automation import queue_email

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN     = os.getenv("SLACK_BOT_TOKEN", "")
CAROLYN_CHANNEL     = os.getenv("SLACK_CAROLYN_CHANNEL", "#carolyn")
CAROLYN_SLACK_ID    = os.getenv("CAROLYN_SLACK_ID", "")  # Carolyn's Slack user ID — DMs go here when set
CAROLYN_PHONE       = os.getenv("CAROLYN_PHONE", "")  # Carolyn's number to text
BUSINESS_PHONE      = os.getenv("BUSINESS_PHONE", "406-599-2699")
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN    = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER", "")
MORNING_BRIEF_TIME  = os.getenv("MORNING_BRIEF_TIME", "09:30")  # 24h format, MT
EOD_SUMMARY_TIME    = os.getenv("EOD_SUMMARY_TIME", "17:00")
FRIDAY_REPORT_TIME  = os.getenv("FRIDAY_REPORT_TIME", "16:00")
SUNDAY_RECO_TIME    = os.getenv("SUNDAY_RECO_TIME", "18:00")  # Sunday weekly proactive reco

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


def _carolyn_target() -> str:
    """Where to deliver Carolyn-targeted messages. Prefer DM if her Slack ID is set."""
    return CAROLYN_SLACK_ID or CAROLYN_CHANNEL


def _post_draft_for_review(email_type: str, customer: dict, ai_body: str, ai_subject: str = None,
                           context_line: str = "") -> str:
    """Queue a draft email and post the review card to Carolyn.
    Returns the queue key Carolyn's Approve button will reference."""
    name = customer.get("name", "Customer")
    email = customer.get("email", "")
    customer_data = {"name": name, "email": email}
    # email_automation.queue_email returns the key it stored under and computes
    # the subject from the template if we don't pass one.
    key = queue_email(email_type, customer_data, ai_body, subject=ai_subject)

    safe_block_id = f"personal_note_{key}"
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"Draft: {email_type.replace('_',' ').title()} — {name}"}},
    ]
    if context_line:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"_{context_line}_"}]})
    blocks.extend([
        {"type": "section", "text": {"type": "mrkdwn", "text": (ai_body or "")[:2900]}},
        {"type": "input", "block_id": safe_block_id, "optional": True, "element": {
            "type": "plain_text_input",
            "action_id": "personal_note_input",
            "placeholder": {"type": "plain_text", "text": "Add a personal sentence (e.g. 'Hope the kids loved the snow last weekend!')"},
            "multiline": True,
        }, "label": {"type": "plain_text", "text": "Your personal note (optional — woven into the email)"}},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✅ Approve & Send"}, "style": "primary",
             "value": key, "action_id": "approve_email"},
            {"type": "button", "text": {"type": "plain_text", "text": "⏭ Skip"},
             "value": key, "action_id": "skip_email"},
        ]},
    ])
    _post_to_slack(_carolyn_target(), f"Draft {email_type} for {name}", blocks=blocks)
    return key


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
    _post_to_slack(_carolyn_target(), f"*Morning Brief — {datetime.date.today().strftime('%A, %B %d')}*\n\n{brief_text}")
    print(f"  ✅ Morning brief sent to Carolyn")


def run_eod_summary():
    """Generate and send the end-of-day summary."""
    if _already_sent("eod_summary"):
        return
    print(f"  📋 Generating end-of-day summary...")
    eod_text = _build_eod_summary()

    _text_carolyn(eod_text)
    _post_to_slack(_carolyn_target(), f"*End of Day Summary — {datetime.date.today().strftime('%A, %B %d')}*\n\n{eod_text}")
    print(f"  ✅ EOD summary sent to Carolyn")


def run_email_drafts(ai_draft_func=None) -> dict:
    """
    Generate win-back and cold lead email drafts for Carolyn's review.
    Called on Monday and Wednesday mornings.

    ai_draft_func: a callable(draft_type, customer_data_dict) that returns
                   a dict like {"subject": str, "body": str}.

    Returns {"win_back": [keys...], "follow_up": [keys...]} so the caller (e.g.
    the bundled morning brief) can mention how many drafts are awaiting review.
    """
    today = datetime.date.today()
    day_name = today.strftime("%A")
    posted = {"win_back": [], "follow_up": []}

    # Monday: Lost customer win-backs
    if day_name == "Monday" and not _already_sent("monday_winbacks"):
        lost = _build_lost_customer_list()
        if lost and ai_draft_func:
            for c in lost[:10]:
                try:
                    draft = ai_draft_func("winback", {
                        "name": c["name"], "email": c.get("email", ""),
                        "days_lapsed": c["days_since"], "last_job_date": c["last_job_date"],
                    })
                    body = draft.get("body", "") if isinstance(draft, dict) else str(draft)
                    subject = draft.get("subject") if isinstance(draft, dict) else None
                    context = f"{c['days_since']} days since last booking | Last job: {c['last_job_date']} | Email: {c.get('email', 'N/A')}"
                    key = _post_draft_for_review("win_back", {"name": c["name"], "email": c.get("email", "")},
                                                  body, ai_subject=subject, context_line=context)
                    posted["win_back"].append(key)
                except Exception as e:
                    print(f"  ⚠️  Failed to draft email for {c['name']}: {e}")
            if posted["win_back"]:
                print(f"  ✅ Posted {len(posted['win_back'])} Monday win-back drafts for Carolyn")

    # Wednesday: Cold lead follow-ups
    if day_name == "Wednesday" and not _already_sent("wednesday_coldleads"):
        cold = _build_cold_lead_list()
        if cold and ai_draft_func:
            for c in cold[:10]:
                try:
                    draft = ai_draft_func("cold_lead", {
                        "name": c["name"], "email": c.get("email", ""),
                        "days_ago": "a few weeks", "estimate_total": c.get("estimate_total", "?"),
                        "created_at": c.get("created_at", "recently"),
                    })
                    body = draft.get("body", "") if isinstance(draft, dict) else str(draft)
                    subject = draft.get("subject") if isinstance(draft, dict) else None
                    context = f"Estimate: ${c['estimate_total']} | Sent: {c['created_at']} | Status: {c['status']}"
                    key = _post_draft_for_review("follow_up", {"name": c["name"], "email": c.get("email", "")},
                                                  body, ai_subject=subject, context_line=context)
                    posted["follow_up"].append(key)
                except Exception as e:
                    print(f"  ⚠️  Failed to draft email for {c['name']}: {e}")
            if posted["follow_up"]:
                print(f"  ✅ Posted {len(posted['follow_up'])} Wednesday cold-lead drafts for Carolyn")

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
                _post_to_slack(_carolyn_target(), f"*Weekly Employee Profitability Report*\n\n{text_summary}")
                print(f"  ✅ Friday profitability report sent to Carolyn")
        except Exception as e:
            print(f"  ⚠️  Failed to generate Friday report: {e}")

    return posted


# ── Bundled Morning Brief ────────────────────────────────────────────────────

def run_bundled_morning_brief(ai_draft_func=None, priority_func=None) -> None:
    """One delivery for Carolyn each morning: brief + top priorities + drafts.

    priority_func: optional callable returning the same shape as bot.build_priority_list
                   — a list of {priority, category, icon, title, detail, action}.
    """
    if _already_sent("bundled_morning_brief"):
        return
    print("  📋 Building bundled morning brief...")
    brief_text = _build_morning_brief()

    # Post drafts FIRST (so we can reference them by count in the brief).
    drafts_posted = run_email_drafts(ai_draft_func=ai_draft_func)
    n_winback = len(drafts_posted.get("win_back", []))
    n_followup = len(drafts_posted.get("follow_up", []))

    # Top priorities (if a priority builder was passed in from bot.py).
    priority_block = ""
    if priority_func:
        try:
            top = priority_func()[:3]
            if top:
                lines = [f"  {i+1}. {p['icon']} *[{p['category']}]* {p['title']} — _{p['detail']}_"
                         for i, p in enumerate(top)]
                priority_block = "\n\n*🎯 Top 3 priorities for today:*\n" + "\n".join(lines)
        except Exception as e:
            print(f"  ⚠️  Could not compute priorities: {e}")

    drafts_block = ""
    if n_winback or n_followup:
        bits = []
        if n_winback:
            bits.append(f"{n_winback} win-back email{'s' if n_winback != 1 else ''}")
        if n_followup:
            bits.append(f"{n_followup} cold-lead follow-up{'s' if n_followup != 1 else ''}")
        drafts_block = (f"\n\n*📬 I drafted {' and '.join(bits)} for you.* Each one is posted below "
                        f"with a personal-note field — add a sentence in your voice, then hit *Approve & Send*. "
                        f"Nothing goes out until you click approve.")

    full_text = f"*Morning Brief — {datetime.date.today().strftime('%A, %B %d')}*\n\n{brief_text}{priority_block}{drafts_block}"
    # Single delivery: one Slack post + one text.
    _text_carolyn(brief_text + (drafts_block.replace("*", "") if drafts_block else ""))
    _post_to_slack(_carolyn_target(), full_text)
    print(f"  ✅ Bundled morning brief delivered to Carolyn")


# ── Sunday Weekly Proactive Recommendation ───────────────────────────────────

def _build_weekly_snapshot() -> dict:
    """Pull the past week's HCP data so the AI can pick a focus area."""
    today = datetime.date.today()
    week_ago = today - datetime.timedelta(days=7)
    snap = {
        "completed_jobs": 0, "revenue_estimate": 0.0,
        "new_leads": 0, "open_estimates": 0,
        "lapsed_60": 0, "lapsed_90": 0,
        "uninvoiced_completed": 0,
    }
    jobs_data, err = _hcp_get("/jobs", params={"page_size": 200})
    if not err and jobs_data:
        for j in jobs_data.get("jobs", []):
            completed = (j.get("completed_at") or "")[:10]
            if completed:
                try:
                    if datetime.date.fromisoformat(completed) >= week_ago:
                        snap["completed_jobs"] += 1
                        try:
                            snap["revenue_estimate"] += float(j.get("total_amount", 0) or 0)
                        except (ValueError, TypeError):
                            pass
                except ValueError:
                    pass
            if j.get("invoice_status") == "uninvoiced" and j.get("work_status") == "completed":
                snap["uninvoiced_completed"] += 1
    est_data, est_err = _hcp_get("/estimates", params={"page_size": 200})
    if not est_err and est_data:
        snap["open_estimates"] = sum(1 for e in est_data.get("estimates", [])
                                     if e.get("status") not in ("approved", "converted_to_job"))
    cust_data, cust_err = _hcp_get("/customers", params={"page_size": 200})
    if not cust_err and cust_data:
        for c in cust_data.get("customers", []):
            last_job = c.get("last_job_date")
            if not last_job:
                continue
            try:
                d = (today - datetime.date.fromisoformat(last_job[:10])).days
                if d > 60:
                    snap["lapsed_60"] += 1
                if d > 90:
                    snap["lapsed_90"] += 1
            except (ValueError, TypeError):
                pass
    return snap


def run_sunday_recommendation(ai_func=None, ai_draft_func=None) -> None:
    """Sunday evening: ask the AI to pick a focus for the week and draft 3
    supporting emails. Posts the recommendation + drafts to Carolyn.

    ai_func: callable(system_prompt, user_prompt) -> str. Used to generate the focus narrative.
    ai_draft_func: same shape used by run_email_drafts.
    """
    if _already_sent("sunday_recommendation"):
        return
    snap = _build_weekly_snapshot()
    snap_text = (
        f"Past 7 days: {snap['completed_jobs']} jobs completed, ~${snap['revenue_estimate']:,.0f} revenue.\n"
        f"Pipeline today: {snap['open_estimates']} open estimates, {snap['uninvoiced_completed']} uninvoiced completed jobs.\n"
        f"Lapsed customers: {snap['lapsed_60']} (60+ days), {snap['lapsed_90']} (90+ days)."
    )

    focus = ""
    if ai_func:
        try:
            system = ("You are the proactive business strategist for Montana Premium House Care. "
                      "Carolyn is the office manager. Pick ONE focus area for the coming week based "
                      "on the snapshot — be specific, actionable, and short. Three short paragraphs max. "
                      "End with a one-line call-to-action Carolyn can do Monday morning. No emojis.")
            focus = ai_func(system, f"Snapshot:\n{snap_text}\n\nWhat should Carolyn focus on this week, and why?")
        except Exception as e:
            focus = f"(AI focus generation failed: {e})"

    intro = (f"*Sunday Planning — Week of {(datetime.date.today() + datetime.timedelta(days=1)).strftime('%B %d')}*\n\n"
             f"_{snap_text}_\n\n"
             f"*🎯 Recommended focus this week:*\n{focus or '(no focus generated)'}\n\n"
             f"I'm drafting 3 supporting emails below — review, add a personal note, and approve.")
    _post_to_slack(_carolyn_target(), intro)

    # Draft up to 3 supporting emails: prioritize the longest-lapsed customers,
    # since win-back is almost always the best week-opener.
    if ai_draft_func:
        lost = _build_lost_customer_list()
        for c in lost[:3]:
            try:
                draft = ai_draft_func("winback", {
                    "name": c["name"], "email": c.get("email", ""),
                    "days_lapsed": c["days_since"], "last_job_date": c["last_job_date"],
                })
                body = draft.get("body", "") if isinstance(draft, dict) else str(draft)
                subject = draft.get("subject") if isinstance(draft, dict) else None
                _post_draft_for_review(
                    "win_back", {"name": c["name"], "email": c.get("email", "")},
                    body, ai_subject=subject,
                    context_line=f"Sunday-planning draft | {c['days_since']} days inactive",
                )
            except Exception as e:
                print(f"  ⚠️  Sunday draft failed for {c['name']}: {e}")

    _text_carolyn(f"Sunday planning brief is in Slack. {snap['lapsed_60']} lapsed customers, {snap['open_estimates']} open estimates. I drafted 3 emails — review and approve when you're ready.")
    print("  ✅ Sunday weekly recommendation delivered to Carolyn")


# ── Main Scheduler Loop ──────────────────────────────────────────────────────

_scheduler_running = False

def start_proactive_scheduler(ai_draft_func=None, ai_func=None, priority_func=None):
    """
    Start the background scheduler that checks the clock every 60 seconds
    and fires tasks at the right times.

    ai_draft_func: callable(draft_type, customer_data_dict) -> {"subject", "body"}.
                   Required to generate Monday/Wednesday/Sunday email drafts.
    ai_func:       callable(system_prompt, user_prompt) -> str.
                   Required for the Sunday weekly recommendation narrative.
    priority_func: callable() -> list of priority dicts.
                   Optional — used to enrich the bundled morning brief.
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
                day_name = now.strftime("%A")

                # Reset daily tracker at midnight
                if current_date != last_date:
                    _reset_daily_tracker()
                    last_date = current_date

                # Morning brief at configured time (default 9:30 AM) — bundled with
                # priorities and any drafted emails.
                if current_time == MORNING_BRIEF_TIME:
                    run_bundled_morning_brief(ai_draft_func=ai_draft_func,
                                              priority_func=priority_func)

                # EOD summary at configured time (default 5:00 PM)
                if current_time == EOD_SUMMARY_TIME:
                    run_eod_summary()

                # Friday profitability report fires through run_email_drafts
                if day_name == "Friday" and current_time == FRIDAY_REPORT_TIME:
                    run_email_drafts(ai_draft_func=ai_draft_func)

                # Sunday evening proactive recommendation
                if day_name == "Sunday" and current_time == SUNDAY_RECO_TIME:
                    run_sunday_recommendation(ai_func=ai_func, ai_draft_func=ai_draft_func)

            except Exception as e:
                print(f"  ⚠️  Scheduler error: {e}")

            time.sleep(60)  # Check every minute

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"  ⏰ Proactive scheduler started (Brief: {MORNING_BRIEF_TIME}, EOD: {EOD_SUMMARY_TIME}, Sunday reco: {SUNDAY_RECO_TIME})")
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
