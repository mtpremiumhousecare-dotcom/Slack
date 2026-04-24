"""
Montana Premium House Care — Carolyn Donaldson Profile & Interview Module
=========================================================================
This module conducts a structured onboarding interview with Carolyn to learn:
  - Her communication style preferences
  - How she likes to prioritize tasks
  - Her customer service philosophy
  - Her preferred working hours and response times
  - Her tone for emails and customer interactions
  - What stresses her out and what she needs help with most

The profile is saved persistently and used to personalize every interaction.

Commands:
  /meetcarolyn   — Start or restart the onboarding interview
  /myprofile     — View Carolyn's saved preferences
  /updatepref    — Update a specific preference
  /moodcheck     — Daily check-in: how is Carolyn doing today?
"""

import os
import json
import datetime

PROFILE_FILE = os.path.join(os.path.dirname(__file__), "carolyn_profile_data.json")

# ── Default profile (filled in during interview) ──────────────────────────────
DEFAULT_PROFILE = {
    "name":               "Carolyn Donaldson",
    "role":               "Office Manager / Assistant",
    "onboarded":          False,
    "interview_step":     0,
    "last_seen":          None,
    "mood_log":           [],

    # Communication preferences
    "email_tone":         None,   # formal | friendly | brief | warm
    "response_urgency":   None,   # immediate | within_hour | same_day
    "preferred_greeting": None,   # e.g. "Hi [Name]" vs "Hello [Name],"
    "sign_off":           None,   # e.g. "Warm regards," "Thanks!"

    # Work style
    "priority_style":     None,   # revenue_first | customer_first | operations_first
    "morning_brief":      None,   # yes | no
    "brief_time":         None,   # e.g. "8:00 AM"
    "notification_level": None,   # all_leads | urgent_only | digest_only
    "digest_time":        None,   # e.g. "5:00 PM"

    # Customer service philosophy
    "cs_philosophy":      None,   # free text
    "escalation_style":   None,   # handle_it | flag_chris | both
    "complaint_approach": None,   # apologize_first | investigate_first | offer_solution_first

    # Pain points
    "biggest_challenge":  None,   # free text
    "needs_most_help":    None,   # leads | scheduling | customer_comms | reporting | all

    # Personal touches
    "fun_fact":           None,
    "motivation":         None,
}

# ── Interview questions (conversational, step by step) ────────────────────────
INTERVIEW_QUESTIONS = [
    {
        "key":      "email_tone",
        "question": (
            "Great to meet you, Carolyn! 👋 I'm your Office Assistant, and I'm here to make your day easier.\n\n"
            "Let's start simple: *How would you describe your preferred email tone?*\n\n"
            "Reply with a number:\n"
            "1️⃣ *Formal* — Professional and polished\n"
            "2️⃣ *Friendly* — Warm but professional\n"
            "3️⃣ *Brief* — Short and to the point\n"
            "4️⃣ *Warm* — Personal and relationship-focused"
        ),
        "options": {"1": "formal", "2": "friendly", "3": "brief", "4": "warm"},
    },
    {
        "key":      "preferred_greeting",
        "question": (
            "Perfect! Now, *how do you like to open emails to customers?*\n\n"
            "1️⃣ `Hi [Name],`\n"
            "2️⃣ `Hello [Name],`\n"
            "3️⃣ `Dear [Name],`\n"
            "4️⃣ `Hey [Name]!`\n"
            "5️⃣ Type your own custom greeting"
        ),
        "options": {"1": "Hi {name},", "2": "Hello {name},", "3": "Dear {name},", "4": "Hey {name}!"},
        "custom": True,
    },
    {
        "key":      "sign_off",
        "question": (
            "And *how do you like to sign off on emails?*\n\n"
            "1️⃣ `Warm regards,`\n"
            "2️⃣ `Thank you!`\n"
            "3️⃣ `Looking forward to hearing from you,`\n"
            "4️⃣ `With appreciation,`\n"
            "5️⃣ Type your own custom sign-off"
        ),
        "options": {"1": "Warm regards,", "2": "Thank you!", "3": "Looking forward to hearing from you,", "4": "With appreciation,"},
        "custom": True,
    },
    {
        "key":      "response_urgency",
        "question": (
            "When a new lead comes in, *how quickly do you want to be notified?*\n\n"
            "1️⃣ *Immediately* — Alert me the moment a lead arrives\n"
            "2️⃣ *Within the hour* — Batch alerts every 60 minutes\n"
            "3️⃣ *Daily digest only* — One summary at the end of the day"
        ),
        "options": {"1": "immediate", "2": "within_hour", "3": "digest_only"},
    },
    {
        "key":      "morning_brief",
        "question": (
            "Would you like a *morning briefing* posted to your Slack channel each day?\n"
            "It would include: today's jobs, open leads, priority action items, and any urgent flags.\n\n"
            "1️⃣ *Yes please!*\n"
            "2️⃣ *No thanks*"
        ),
        "options": {"1": "yes", "2": "no"},
    },
    {
        "key":      "brief_time",
        "question": (
            "What time would you like your morning brief? ☀️\n\n"
            "1️⃣ 7:00 AM\n"
            "2️⃣ 7:30 AM\n"
            "3️⃣ 8:00 AM\n"
            "4️⃣ 8:30 AM\n"
            "5️⃣ 9:00 AM\n"
            "6️⃣ Type a custom time (e.g. `6:45 AM`)"
        ),
        "options": {"1": "7:00 AM", "2": "7:30 AM", "3": "8:00 AM", "4": "8:30 AM", "5": "9:00 AM"},
        "custom": True,
        "skip_if": {"morning_brief": "no"},
    },
    {
        "key":      "priority_style",
        "question": (
            "When you look at your to-do list, *what do you naturally tackle first?*\n\n"
            "1️⃣ *Revenue first* — Invoices, estimates, money stuff\n"
            "2️⃣ *Customer first* — Respond to customers, follow-ups\n"
            "3️⃣ *Operations first* — Jobs, scheduling, team\n"
            "4️⃣ *Urgent fires first* — Whatever is most pressing"
        ),
        "options": {"1": "revenue_first", "2": "customer_first", "3": "operations_first", "4": "urgent_first"},
    },
    {
        "key":      "escalation_style",
        "question": (
            "When a customer complaint or difficult situation comes up, *what's your style?*\n\n"
            "1️⃣ *Handle it myself* — I'll take care of it\n"
            "2️⃣ *Flag Chris* — Escalate to the owner\n"
            "3️⃣ *Both* — I handle it but keep Chris in the loop"
        ),
        "options": {"1": "handle_it", "2": "flag_chris", "3": "both"},
    },
    {
        "key":      "complaint_approach",
        "question": (
            "When a customer is upset, *what's your first instinct?*\n\n"
            "1️⃣ *Apologize first* — Acknowledge their feelings immediately\n"
            "2️⃣ *Investigate first* — Understand what happened before responding\n"
            "3️⃣ *Offer a solution first* — Jump straight to fixing it"
        ),
        "options": {"1": "apologize_first", "2": "investigate_first", "3": "offer_solution_first"},
    },
    {
        "key":      "needs_most_help",
        "question": (
            "What area do you feel you need the *most support* with right now?\n\n"
            "1️⃣ *Lead management* — Tracking and following up on new leads\n"
            "2️⃣ *Scheduling* — Keeping jobs organized and on track\n"
            "3️⃣ *Customer communications* — Emails, follow-ups, complaints\n"
            "4️⃣ *Reporting* — Understanding what's working and what's not\n"
            "5️⃣ *All of the above* — I need help everywhere!"
        ),
        "options": {"1": "leads", "2": "scheduling", "3": "customer_comms", "4": "reporting", "5": "all"},
    },
    {
        "key":      "biggest_challenge",
        "question": (
            "In your own words — *what's the biggest challenge you face in this role?*\n\n"
            "Just type it out. There are no wrong answers. This helps me understand how to support you best. 💬"
        ),
        "free_text": True,
    },
    {
        "key":      "cs_philosophy",
        "question": (
            "Last big one: *How would you describe your customer service philosophy in one sentence?*\n\n"
            "For example: _\"Every customer should feel like they're our only customer.\"_\n\n"
            "Type your own philosophy — this will guide how I draft all customer communications for you. ✨"
        ),
        "free_text": True,
    },
    {
        "key":      "fun_fact",
        "question": (
            "Almost done! 🎉 One fun one — *tell me something about yourself* so I can get to know you better.\n\n"
            "It could be a hobby, a favorite food, something you're proud of — anything! 😊"
        ),
        "free_text": True,
    },
    {
        "key":      "motivation",
        "question": (
            "Final question: *What motivates you most about working at Montana Premium House Care?*\n\n"
            "This helps me understand what drives you so I can keep you energized and focused. 💪"
        ),
        "free_text": True,
    },
]


# ── Profile persistence ────────────────────────────────────────────────────────

def load_profile():
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, "r") as f:
            data = json.load(f)
        # Merge with defaults to handle new keys added later
        merged = {**DEFAULT_PROFILE, **data}
        return merged
    return dict(DEFAULT_PROFILE)


def save_profile(profile: dict):
    with open(PROFILE_FILE, "w") as f:
        json.dump(profile, f, indent=2)


def update_preference(key: str, value: str):
    profile = load_profile()
    if key in profile:
        profile[key] = value
        save_profile(profile)
        return True
    return False


def log_mood(mood: str, note: str = ""):
    profile = load_profile()
    entry = {
        "date":  datetime.date.today().isoformat(),
        "time":  datetime.datetime.now().strftime("%H:%M"),
        "mood":  mood,
        "note":  note,
    }
    profile.setdefault("mood_log", []).append(entry)
    # Keep last 90 days
    profile["mood_log"] = profile["mood_log"][-90:]
    profile["last_seen"] = datetime.datetime.now().isoformat()
    save_profile(profile)
    return entry


def get_current_question(profile: dict):
    step = profile.get("interview_step", 0)
    if step >= len(INTERVIEW_QUESTIONS):
        return None
    q = INTERVIEW_QUESTIONS[step]
    # Check skip condition
    if "skip_if" in q:
        for k, v in q["skip_if"].items():
            if profile.get(k) == v:
                profile["interview_step"] = step + 1
                save_profile(profile)
                return get_current_question(profile)
    return q, step


def process_interview_answer(profile: dict, answer: str):
    """
    Process Carolyn's answer to the current interview question.
    Returns (response_message, is_complete).
    """
    result = get_current_question(profile)
    if result is None:
        return "✅ Your profile is already complete! Use `/myprofile` to view it.", True

    q, step = result
    key = q["key"]
    options = q.get("options", {})
    is_free_text = q.get("free_text", False)
    is_custom = q.get("custom", False)

    # Determine value
    if is_free_text:
        value = answer.strip()
    elif answer.strip() in options:
        value = options[answer.strip()]
    elif is_custom and answer.strip() not in options:
        # Custom text answer
        value = answer.strip()
    else:
        # Invalid answer
        valid = ", ".join(options.keys())
        return f"⚠️ Please reply with one of: {valid} (or type your own answer if applicable)", False

    # Save answer
    profile[key] = value
    profile["interview_step"] = step + 1
    save_profile(profile)

    # Check if interview is complete
    next_result = get_current_question(profile)
    if next_result is None:
        profile["onboarded"] = True
        save_profile(profile)
        return _build_completion_message(profile), True

    next_q, _ = next_result
    return f"✅ Got it!\n\n{next_q['question']}", False


def _build_completion_message(profile: dict) -> str:
    tone_map = {
        "formal": "professional and polished",
        "friendly": "warm and professional",
        "brief": "short and to the point",
        "warm": "personal and relationship-focused",
    }
    tone = tone_map.get(profile.get("email_tone", ""), profile.get("email_tone", ""))
    return (
        f"🎉 *Welcome aboard, {profile['name']}!* I've got everything I need to support you.\n\n"
        f"Here's what I've learned about you:\n"
        f"• *Email tone:* {tone}\n"
        f"• *Greeting style:* {profile.get('preferred_greeting','')}\n"
        f"• *Sign-off:* {profile.get('sign_off','')}\n"
        f"• *Lead alerts:* {profile.get('response_urgency','').replace('_',' ')}\n"
        f"• *Morning brief:* {profile.get('morning_brief','').title()} {'at ' + profile.get('brief_time','') if profile.get('morning_brief') == 'yes' else ''}\n"
        f"• *Priority style:* {profile.get('priority_style','').replace('_',' ')}\n"
        f"• *Escalation:* {profile.get('escalation_style','').replace('_',' ')}\n"
        f"• *CS philosophy:* _{profile.get('cs_philosophy','')}_\n\n"
        f"I'll use all of this to personalize every email draft, every alert, and every recommendation I give you.\n\n"
        f"*Your biggest challenge:* _{profile.get('biggest_challenge','')}_\n"
        f"That's exactly what I'm here to help with. Let's get to work! 💪\n\n"
        f"Type `/cleanhelp` to see everything I can do for you."
    )


def format_profile_for_slack(profile: dict) -> list:
    """Format Carolyn's profile as Slack blocks."""
    mood_log = profile.get("mood_log", [])
    recent_mood = mood_log[-1] if mood_log else None

    fields = [
        {"type": "mrkdwn", "text": f"*Email Tone:*\n{profile.get('email_tone','Not set').title()}"},
        {"type": "mrkdwn", "text": f"*Greeting:*\n{profile.get('preferred_greeting','Not set')}"},
        {"type": "mrkdwn", "text": f"*Sign-off:*\n{profile.get('sign_off','Not set')}"},
        {"type": "mrkdwn", "text": f"*Lead Alerts:*\n{profile.get('response_urgency','Not set').replace('_',' ').title()}"},
        {"type": "mrkdwn", "text": f"*Morning Brief:*\n{profile.get('morning_brief','Not set').title()} {('at ' + profile.get('brief_time','')) if profile.get('morning_brief') == 'yes' else ''}"},
        {"type": "mrkdwn", "text": f"*Priority Style:*\n{profile.get('priority_style','Not set').replace('_',' ').title()}"},
        {"type": "mrkdwn", "text": f"*Escalation:*\n{profile.get('escalation_style','Not set').replace('_',' ').title()}"},
        {"type": "mrkdwn", "text": f"*Complaint Approach:*\n{profile.get('complaint_approach','Not set').replace('_',' ').title()}"},
        {"type": "mrkdwn", "text": f"*Needs Most Help With:*\n{profile.get('needs_most_help','Not set').replace('_',' ').title()}"},
        {"type": "mrkdwn", "text": f"*Recent Mood:*\n{recent_mood['mood'] if recent_mood else 'No check-ins yet'}"},
    ]

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"👤 Carolyn's Profile — Montana Premium House Care"}},
        {"type": "divider"},
        {"type": "section", "fields": fields[:6]},
        {"type": "section", "fields": fields[6:]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Customer Service Philosophy:*\n_{profile.get('cs_philosophy','Not set')}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Biggest Challenge:*\n_{profile.get('biggest_challenge','Not set')}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*What Motivates Me:*\n_{profile.get('motivation','Not set')}_"}},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Fun Fact:*\n_{profile.get('fun_fact','Not set')}_"}},
        {"type": "divider"},
        {"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "✏️ Update a Preference"}, "action_id": "update_pref_menu", "value": "menu"},
            {"type": "button", "text": {"type": "plain_text", "text": "😊 Mood Check-In"}, "action_id": "mood_checkin", "value": "checkin"},
        ]},
    ]
    return blocks
