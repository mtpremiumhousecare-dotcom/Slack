"""
Employee Profitability Tracker — Montana Premium House Care
============================================================
Pulls employee data, job appointments, and invoices from HousecallPro
to calculate rough profit margins per employee per week.

Carolyn can see:
- Hours worked per employee (from job appointment durations)
- Revenue generated per employee (from job invoices)
- Tips earned per employee
- Labor cost (hours × hourly rate)
- Profit margin per employee
- Who's taking too long vs. who deserves a raise
"""

import os
import datetime
import requests
from dotenv import load_dotenv

load_dotenv()

HCP_API_KEY = os.getenv("HOUSECALLPRO_API_KEY", "")
HCP_BASE = "https://api.housecallpro.com"

# ── Default hourly pay rates (override in .env or via /office payrate) ──
# Format in .env: EMPLOYEE_PAY_RATES=John:18,Sarah:17,Mike:16
_pay_rates_raw = os.getenv("EMPLOYEE_PAY_RATES", "")
DEFAULT_HOURLY_RATE = float(os.getenv("DEFAULT_HOURLY_RATE", "17.00"))

# Parse pay rates from .env
EMPLOYEE_PAY_RATES = {}
if _pay_rates_raw:
    for entry in _pay_rates_raw.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 2:
            EMPLOYEE_PAY_RATES[parts[0].strip().lower()] = float(parts[1].strip())

# In-memory override (set via /office payrate command)
_runtime_pay_rates = {}


def set_pay_rate(employee_name: str, rate: float):
    """Set or update an employee's hourly pay rate at runtime."""
    _runtime_pay_rates[employee_name.strip().lower()] = rate


def get_pay_rate(employee_name: str) -> float:
    """Get an employee's hourly rate. Checks runtime overrides, then .env, then default."""
    name = employee_name.strip().lower()
    if name in _runtime_pay_rates:
        return _runtime_pay_rates[name]
    if name in EMPLOYEE_PAY_RATES:
        return EMPLOYEE_PAY_RATES[name]
    return DEFAULT_HOURLY_RATE


def get_all_pay_rates() -> dict:
    """Return all known pay rates (merged)."""
    merged = dict(EMPLOYEE_PAY_RATES)
    merged.update(_runtime_pay_rates)
    return merged


def _hcp_get(path, params=None):
    """Make a GET request to HousecallPro API."""
    if not HCP_API_KEY or HCP_API_KEY == "your_housecallpro_api_key_here":
        return None, "HCP API key not configured"
    headers = {"Authorization": f"Token {HCP_API_KEY}", "Accept": "application/json"}
    try:
        r = requests.get(f"{HCP_BASE}{path}", headers=headers, params=params or {}, timeout=15)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _get_week_range(weeks_ago=0):
    """Get Monday-Sunday date range for a given week (0 = current week)."""
    today = datetime.date.today()
    monday = today - datetime.timedelta(days=today.weekday() + (weeks_ago * 7))
    sunday = monday + datetime.timedelta(days=6)
    return monday, sunday


def fetch_employees():
    """Fetch all employees from HCP."""
    data, err = _hcp_get("/employees", params={"page_size": 100})
    if err:
        return [], err
    return data.get("employees", []), None


def fetch_completed_jobs(start_date, end_date, page=1, all_jobs=None):
    """Fetch completed jobs within a date range, handling pagination."""
    if all_jobs is None:
        all_jobs = []
    params = {
        "page": page,
        "page_size": 100,
        "work_status": "completed",
    }
    data, err = _hcp_get("/jobs", params=params)
    if err:
        return all_jobs, err
    jobs = data.get("jobs", [])
    # Filter by date range (scheduled_start)
    for job in jobs:
        sched = job.get("schedule", {})
        start = sched.get("scheduled_start", "")[:10] if sched and sched.get("scheduled_start") else ""
        if start and start_date.isoformat() <= start <= end_date.isoformat():
            all_jobs.append(job)
    # Paginate if needed
    total_pages = data.get("total_pages", 1)
    if page < total_pages:
        return fetch_completed_jobs(start_date, end_date, page + 1, all_jobs)
    return all_jobs, None


def calculate_job_hours(job):
    """Calculate hours spent on a job from schedule or appointment times."""
    sched = job.get("schedule", {})
    if not sched:
        return 0.0

    # Try dispatched (actual) times first, then scheduled
    start_str = sched.get("dispatched_start") or sched.get("scheduled_start") or ""
    end_str = sched.get("dispatched_end") or sched.get("scheduled_end") or ""

    if not start_str or not end_str:
        # Fallback: estimate 2 hours per job if no times available
        return 2.0

    try:
        # Parse ISO datetime strings
        start_dt = datetime.datetime.fromisoformat(start_str.replace("Z", "+00:00"))
        end_dt = datetime.datetime.fromisoformat(end_str.replace("Z", "+00:00"))
        hours = (end_dt - start_dt).total_seconds() / 3600
        # Sanity check: cap at 12 hours, minimum 0.5
        return max(0.5, min(hours, 12.0))
    except (ValueError, TypeError):
        return 2.0


def get_job_revenue(job):
    """Get revenue from a job (total from invoice or line items)."""
    # Try invoice total first
    total = job.get("total_amount") or job.get("invoice", {}).get("total") or 0
    if isinstance(total, str):
        try:
            total = float(total.replace("$", "").replace(",", ""))
        except ValueError:
            total = 0
    return float(total)


def get_job_tips(job):
    """Get tips from a job."""
    tip = job.get("tip_amount") or job.get("invoice", {}).get("tip_amount") or 0
    if isinstance(tip, str):
        try:
            tip = float(tip.replace("$", "").replace(",", ""))
        except ValueError:
            tip = 0
    return float(tip)


def get_assigned_employees(job):
    """Get list of assigned employee IDs/names from a job."""
    assigned = job.get("assigned_employees", [])
    if not assigned:
        # Try dispatched_employees or technicians
        assigned = job.get("dispatched_employees", []) or job.get("technicians", [])
    return assigned


def build_profitability_report(weeks_ago=0):
    """
    Build a full profitability report for all employees for a given week.

    Returns:
    {
        "week_label": "Apr 14 - Apr 20, 2026",
        "start_date": "2026-04-14",
        "end_date": "2026-04-20",
        "employees": [
            {
                "name": "Sarah Johnson",
                "id": "abc123",
                "jobs_completed": 12,
                "hours_worked": 32.5,
                "revenue_generated": 2450.00,
                "tips_earned": 185.00,
                "hourly_rate": 17.00,
                "labor_cost": 552.50,
                "gross_profit": 1897.50,
                "profit_margin": 77.4,
                "revenue_per_hour": 75.38,
                "avg_hours_per_job": 2.71,
                "efficiency_flag": "good"  # good, slow, fast
            },
            ...
        ],
        "totals": {
            "total_jobs": 45,
            "total_hours": 120.5,
            "total_revenue": 8500.00,
            "total_tips": 650.00,
            "total_labor_cost": 2048.50,
            "total_gross_profit": 6451.50,
            "overall_margin": 75.9
        },
        "insights": [
            "🟢 Sarah has the highest profit margin at 82.1% — consider a raise.",
            "🔴 Mike is averaging 4.2 hrs/job vs team avg of 2.7 — may need coaching.",
            ...
        ]
    }
    """
    monday, sunday = _get_week_range(weeks_ago)
    week_label = f"{monday.strftime('%b %d')} - {sunday.strftime('%b %d, %Y')}"

    # Fetch employees
    employees, emp_err = fetch_employees()
    if emp_err:
        return {"error": f"Could not fetch employees: {emp_err}"}

    # Build employee lookup
    emp_lookup = {}
    for emp in employees:
        emp_id = emp.get("id", "")
        emp_name = f"{emp.get('first_name', '')} {emp.get('last_name', '')}".strip()
        emp_lookup[emp_id] = {
            "name": emp_name,
            "id": emp_id,
            "jobs_completed": 0,
            "hours_worked": 0.0,
            "revenue_generated": 0.0,
            "tips_earned": 0.0,
            "hourly_rate": get_pay_rate(emp.get("first_name", "")),
            "labor_cost": 0.0,
            "gross_profit": 0.0,
            "profit_margin": 0.0,
            "revenue_per_hour": 0.0,
            "avg_hours_per_job": 0.0,
            "efficiency_flag": "good",
            "jobs": [],
        }

    # Fetch completed jobs for the week
    jobs, job_err = fetch_completed_jobs(monday, sunday)
    if job_err:
        return {"error": f"Could not fetch jobs: {job_err}"}

    # Assign jobs to employees
    for job in jobs:
        assigned = get_assigned_employees(job)
        hours = calculate_job_hours(job)
        revenue = get_job_revenue(job)
        tips = get_job_tips(job)

        # Split revenue among assigned employees if multiple
        num_assigned = max(len(assigned), 1)
        rev_per_emp = revenue / num_assigned
        tips_per_emp = tips / num_assigned
        hours_per_emp = hours  # Each employee works the full duration

        for emp_ref in assigned:
            emp_id = emp_ref if isinstance(emp_ref, str) else emp_ref.get("id", "")
            if emp_id in emp_lookup:
                emp_lookup[emp_id]["jobs_completed"] += 1
                emp_lookup[emp_id]["hours_worked"] += hours_per_emp
                emp_lookup[emp_id]["revenue_generated"] += rev_per_emp
                emp_lookup[emp_id]["tips_earned"] += tips_per_emp
                emp_lookup[emp_id]["jobs"].append({
                    "name": job.get("customer", {}).get("first_name", "Job"),
                    "hours": hours_per_emp,
                    "revenue": rev_per_emp,
                })

    # Calculate profitability metrics
    all_employees = []
    total_jobs = 0
    total_hours = 0.0
    total_revenue = 0.0
    total_tips = 0.0
    total_labor = 0.0

    for emp_id, emp in emp_lookup.items():
        if emp["jobs_completed"] == 0:
            emp["efficiency_flag"] = "idle"
            all_employees.append(emp)
            continue

        emp["labor_cost"] = round(emp["hours_worked"] * emp["hourly_rate"], 2)
        emp["gross_profit"] = round(emp["revenue_generated"] - emp["labor_cost"], 2)
        emp["profit_margin"] = round(
            (emp["gross_profit"] / emp["revenue_generated"] * 100)
            if emp["revenue_generated"] > 0 else 0, 1
        )
        emp["revenue_per_hour"] = round(
            emp["revenue_generated"] / emp["hours_worked"]
            if emp["hours_worked"] > 0 else 0, 2
        )
        emp["avg_hours_per_job"] = round(
            emp["hours_worked"] / emp["jobs_completed"]
            if emp["jobs_completed"] > 0 else 0, 1
        )
        emp["hours_worked"] = round(emp["hours_worked"], 1)
        emp["revenue_generated"] = round(emp["revenue_generated"], 2)
        emp["tips_earned"] = round(emp["tips_earned"], 2)

        total_jobs += emp["jobs_completed"]
        total_hours += emp["hours_worked"]
        total_revenue += emp["revenue_generated"]
        total_tips += emp["tips_earned"]
        total_labor += emp["labor_cost"]

        all_employees.append(emp)

    # Calculate team average hours per job for efficiency comparison
    team_avg_hours = total_hours / total_jobs if total_jobs > 0 else 2.5

    # Set efficiency flags
    insights = []
    for emp in all_employees:
        if emp["jobs_completed"] == 0:
            continue
        if emp["avg_hours_per_job"] > team_avg_hours * 1.3:
            emp["efficiency_flag"] = "slow"
            insights.append(
                f"🔴 *{emp['name']}* is averaging {emp['avg_hours_per_job']} hrs/job "
                f"vs team avg of {round(team_avg_hours, 1)} — may need coaching or lighter assignments."
            )
        elif emp["avg_hours_per_job"] < team_avg_hours * 0.7:
            emp["efficiency_flag"] = "fast"
            insights.append(
                f"🟢 *{emp['name']}* is averaging {emp['avg_hours_per_job']} hrs/job "
                f"— fastest on the team. High performer!"
            )
        else:
            emp["efficiency_flag"] = "good"

    # Profit margin insights
    active_emps = [e for e in all_employees if e["jobs_completed"] > 0]
    if active_emps:
        best = max(active_emps, key=lambda x: x["profit_margin"])
        worst = min(active_emps, key=lambda x: x["profit_margin"])
        highest_tips = max(active_emps, key=lambda x: x["tips_earned"])
        most_jobs = max(active_emps, key=lambda x: x["jobs_completed"])

        insights.append(
            f"💰 *{best['name']}* has the highest profit margin at {best['profit_margin']}% "
            f"— consider a raise or bonus."
        )
        if worst["profit_margin"] < 50:
            insights.append(
                f"⚠️ *{worst['name']}* has the lowest margin at {worst['profit_margin']}% "
                f"— review job assignments and efficiency."
            )
        if highest_tips["tips_earned"] > 0:
            insights.append(
                f"⭐ *{highest_tips['name']}* earned the most tips (${highest_tips['tips_earned']:.2f}) "
                f"— customers love them!"
            )
        insights.append(
            f"🏆 *{most_jobs['name']}* completed the most jobs ({most_jobs['jobs_completed']}) this week."
        )

    idle_emps = [e for e in all_employees if e["jobs_completed"] == 0]
    if idle_emps:
        names = ", ".join([e["name"] for e in idle_emps])
        insights.append(f"⚪ *No jobs recorded for:* {names} — check scheduling or HCP assignment data.")

    # Sort by profit margin descending
    all_employees.sort(key=lambda x: x["profit_margin"], reverse=True)

    total_gross = round(total_revenue - total_labor, 2)
    overall_margin = round((total_gross / total_revenue * 100) if total_revenue > 0 else 0, 1)

    return {
        "week_label": week_label,
        "start_date": monday.isoformat(),
        "end_date": sunday.isoformat(),
        "employees": all_employees,
        "totals": {
            "total_jobs": total_jobs,
            "total_hours": round(total_hours, 1),
            "total_revenue": round(total_revenue, 2),
            "total_tips": round(total_tips, 2),
            "total_labor_cost": round(total_labor, 2),
            "total_gross_profit": total_gross,
            "overall_margin": overall_margin,
        },
        "insights": insights,
        "team_avg_hours_per_job": round(team_avg_hours, 1),
    }


def format_profitability_for_slack(report):
    """Format the profitability report as Slack blocks."""
    if "error" in report:
        return [{"type": "section", "text": {"type": "mrkdwn", "text": f"⚠️ {report['error']}"}}]

    t = report["totals"]
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"💰 Employee Profitability — {report['week_label']}"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"_Team avg: {report['team_avg_hours_per_job']} hrs/job • {t['total_jobs']} jobs • ${t['total_revenue']:,.2f} revenue_"}]},
        {"type": "divider"},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Total Revenue:*\n${t['total_revenue']:,.2f}"},
            {"type": "mrkdwn", "text": f"*Total Tips:*\n${t['total_tips']:,.2f}"},
            {"type": "mrkdwn", "text": f"*Total Labor Cost:*\n${t['total_labor_cost']:,.2f}"},
            {"type": "mrkdwn", "text": f"*Gross Profit:*\n${t['total_gross_profit']:,.2f}"},
            {"type": "mrkdwn", "text": f"*Overall Margin:*\n{t['overall_margin']}%"},
            {"type": "mrkdwn", "text": f"*Total Hours:*\n{t['total_hours']}"},
        ]},
        {"type": "divider"},
    ]

    # Employee breakdown
    for emp in report["employees"]:
        if emp["jobs_completed"] == 0:
            flag = "⚪"
            status = "No jobs this week"
        elif emp["efficiency_flag"] == "slow":
            flag = "🔴"
            status = f"Slow — {emp['avg_hours_per_job']} hrs/job"
        elif emp["efficiency_flag"] == "fast":
            flag = "🟢"
            status = f"Fast — {emp['avg_hours_per_job']} hrs/job"
        else:
            flag = "🟡"
            status = f"On pace — {emp['avg_hours_per_job']} hrs/job"

        if emp["jobs_completed"] > 0:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
                f"{flag} *{emp['name']}* (${emp['hourly_rate']:.2f}/hr)\n"
                f"  Jobs: *{emp['jobs_completed']}* | Hours: *{emp['hours_worked']}* | "
                f"Revenue: *${emp['revenue_generated']:,.2f}* | Tips: *${emp['tips_earned']:,.2f}*\n"
                f"  Labor: ${emp['labor_cost']:,.2f} | Profit: *${emp['gross_profit']:,.2f}* | "
                f"Margin: *{emp['profit_margin']}%* | $/hr: ${emp['revenue_per_hour']:,.2f}\n"
                f"  _{status}_"
            )}})
        else:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": (
                f"{flag} *{emp['name']}* (${emp['hourly_rate']:.2f}/hr)\n"
                f"  _{status}_"
            )}})

    # Insights
    if report["insights"]:
        blocks.append({"type": "divider"})
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*📊 Insights & Recommendations:*"}})
        for insight in report["insights"]:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": insight}})

    return blocks
