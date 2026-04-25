"""
chat_handler.py — Natural Language Chat for Montana Premium House Care Bot
Allows Carolyn (and Chris) to talk to the bot like a person instead of only slash commands.
Uses AI to detect intent and route to the right action or have a conversation.
"""
import os, re, json, time

# Per-user pending action state. user_id -> (action_hint, set_at_epoch).
# Lets the bot answer "yes" to a follow-up question like "Want me to run the full analysis?"
_PENDING_ACTIONS = {}
_PENDING_TTL_SEC = 300  # 5 minutes

AFFIRMATIVE_RE = re.compile(
    r"^\s*(yes+|yeah+|yep+|yup+|sure|please( do)?|do it|go ahead|run it|ok(ay)?|sounds good|absolutely|of course)\b[\s.!?]*$",
    re.IGNORECASE,
)


def is_affirmative(text: str) -> bool:
    return bool(AFFIRMATIVE_RE.match(text or ""))


def set_pending_action(user_id: str, action_hint: str) -> None:
    if user_id and action_hint:
        _PENDING_ACTIONS[user_id] = (action_hint, time.time())


def pop_pending_action(user_id: str):
    rec = _PENDING_ACTIONS.pop(user_id, None)
    if not rec:
        return None
    action, ts = rec
    if time.time() - ts > _PENDING_TTL_SEC:
        return None
    return action

# ── Intent Detection ──────────────────────────────────────────────────────────
# Maps natural language patterns to bot actions
INTENT_PATTERNS = [
    # Lead finding
    (r"(find|get|search|look for|pull)\s+(leads?|prospects?|contacts?)", "find_leads"),
    (r"(leads?\s+(for|in))", "find_leads"),
    (r"(residential|commercial|airbnb|hotel|post.?construction)\s+(leads?|prospects?)", "find_leads"),
    # HCP analysis
    (r"(analyze|analysis|check|review)\s+(hcp|housecall|house\s*call)", "hcp_analysis"),
    (r"(missed leads?|lost customers?|revenue gaps?|lapsed)", "hcp_analysis"),
    # Morning brief
    (r"(morning brief|daily brief|today.?s (brief|summary|numbers|report))", "morning_brief"),
    (r"(what.?s (happening|going on) today|how.?s (today|business) look)", "morning_brief"),
    # Email drafting
    (r"(draft|write|compose|create)\s+(an?\s+)?(email|message|follow.?up)", "draft_email"),
    (r"(reach out|contact|email)\s+(to\s+)?(\w+)", "draft_email"),
    (r"(win.?back|follow.?up|cold lead)\s+(email|message)", "draft_email"),
    # Complaint handling
    (r"(complaint|unhappy|angry|upset|frustrated)\s+(customer|client)", "complaint"),
    (r"(handle|respond to|deal with)\s+(a\s+)?(complaint|issue|problem)", "complaint"),
    # Employee profitability
    (r"(employee|staff|team|cleaner)\s+(profit|performance|hours|pay)", "employee_profit"),
    (r"(who.?s (making|earning|performing))", "employee_profit"),
    (r"(payroll|timesheets?|margins?)", "employee_profit"),
    # Recommendations
    (r"(recommend|suggest|advice|what should|how (can|do) (we|i))", "recommend"),
    (r"(grow|improve|increase|boost)\s+(revenue|sales|business|customers)", "recommend"),
    # Job management
    (r"(assign|schedule|create)\s+(a\s+)?(job|cleaning|appointment)", "assign_job"),
    (r"(what.?s on the schedule|upcoming jobs|today.?s jobs)", "job_list"),
    # Announcements
    (r"(announce|tell (the team|everyone)|broadcast|send to (all|team))", "announce"),
    # Feed / what's happening
    (r"(what.?s new|any updates|what did i miss|catch me up|feed)", "feed"),
    # Text / SMS
    (r"(send|text|sms)\s+(a\s+)?(text|message|sms)\s+to", "send_text"),
    (r"(check|show|view)\s+(texts?|messages?|inbox|sms)", "text_inbox"),
    # Priorities
    (r"(priorities|what should i (do|focus on)|most important|action items)", "priorities"),
    # End of day
    (r"(end of day|eod|wrap.?up|how.?d (today|we) do)", "eod_summary"),
    # Interview / meet
    (r"(interview|introduce yourself|who are you|what can you do|get started|meet)", "introduce"),
    # Mood check
    (r"(mood|how.?s my mood|feeling|check.?in|therapy)", "mood_check"),
    # Learning
    (r"(remember|learn|note|keep in mind|don.?t forget)", "learn"),
    (r"(forget|stop|don.?t|never)\s+(doing|sending|recommending|suggesting)", "learn_stop"),
    # AI status
    (r"(ai status|what models|which ai|system status)", "ai_status"),
    # Help
    (r"(help|commands|what can you do|how do i|menu)", "help"),
    # Greeting
    (r"^(hi|hey|hello|good morning|good afternoon|good evening|yo|sup)", "greeting"),
    # Thank you
    (r"(thank|thanks|thx|appreciate|great job|nice work|perfect)", "thanks"),
]

def detect_intent(message: str) -> tuple:
    """
    Detect the user's intent from a natural language message.
    Returns (intent_name, extracted_details).
    """
    msg_lower = message.lower().strip()

    for pattern, intent in INTENT_PATTERNS:
        match = re.search(pattern, msg_lower)
        if match:
            return intent, match.group(0)

    return "general_chat", None


def _run_action(action_hint: str, runner_func, user_name: str) -> dict:
    """Execute a runner-backed action. Returns response dict or None on failure."""
    if not runner_func or not action_hint:
        return None
    try:
        result = runner_func(action_hint)
    except Exception as e:
        return {"text": f"⚠️ I tried to run that but hit an error: {e}", "blocks": None, "action_hint": None}
    if not result:
        return None
    text = result.get("text") or f"Done, {user_name}."
    return {"text": text, "blocks": result.get("blocks"), "action_hint": None}


def build_chat_response(message: str, user_name: str = "there", ai_func=None,
                        user_id: str = "", runner_func=None) -> dict:
    """
    Process a natural language message and return a response with optional action suggestions.
    Returns: {"text": str, "blocks": list or None, "action_hint": str or None}

    runner_func, if provided, is called as runner_func(action_hint) and should return
    {"text": str, "blocks": list|None} or None. Used to actually execute actions
    (like running the HCP analysis) instead of only suggesting slash commands.
    """
    # ── Affirmative reply to a previously-offered action ──────────────────
    if user_id and is_affirmative(message):
        pending = pop_pending_action(user_id)
        if pending:
            ran = _run_action(pending, runner_func, user_name)
            if ran:
                return ran

    intent, detail = detect_intent(message)

    # ── Greetings ─────────────────────────────────────────────────────────
    if intent == "greeting":
        return {
            "text": f"Good morning, {user_name}! I'm here and ready to help. What do you need today? You can ask me anything or type `/cleanhelp` to see all my commands.",
            "blocks": None,
            "action_hint": None,
        }

    if intent == "thanks":
        return {
            "text": f"You're welcome, {user_name}! Always here if you need anything.",
            "blocks": None,
            "action_hint": None,
        }

    # ── Introduce / What can you do ───────────────────────────────────────
    if intent == "introduce":
        intro = f"""Hi {user_name}! I'm the Montana Premium House Care office assistant. Here's what I can do for you:

*Lead Management* — Find leads, score them, track follow-ups
*Customer Communication* — Draft emails, handle complaints, send texts
*HousecallPro Monitoring* — Jobs, customers, estimates, revenue gaps
*Employee Tracking* — Profitability, hours, pay rates
*Daily Operations* — Morning briefs, end-of-day summaries, priorities
*Smart Alerts* — I'll ping you when something needs attention

You can talk to me naturally or use slash commands. To set up your preferences so I can work the way you like, just say "let's do the interview" or type `/carolyn meet`.

What would you like to start with?"""
        return {"text": intro, "blocks": None, "action_hint": None}

    # ── Action-oriented intents with command suggestions ──────────────────
    INTENT_COMMANDS = {
        "find_leads": {
            "text": f"I can find leads for you! Here's how:\n\n`/leads find residential bozeman` — Residential leads in Bozeman\n`/leads find airbnb big sky` — Airbnb leads in Big Sky\n`/leads find commercial all` — Commercial leads across all service areas\n\nWhat type of leads are you looking for and in which city?",
            "action_hint": "find_leads",
        },
        "hcp_analysis": {
            "text": "I'll pull a full analysis from HousecallPro right now. Use:\n\n`/hcp analysis` — Full gap analysis (missed leads, lost customers, revenue gaps)\n`/hcp jobs` — Current jobs\n`/hcp customers` — Customer list\n`/hcp leads` — Pipeline leads\n\nWant me to run the full analysis?",
            "action_hint": "hcp_analysis",
        },
        "morning_brief": {
            "text": "Here's how to get your morning brief:\n\n`/office brief` — Get today's brief right now\n\nI also send it automatically every day at 9:30 AM. Want me to pull it up now?",
            "action_hint": "morning_brief",
        },
        "draft_email": {
            "text": f"I can draft an email for you! What type?\n\n`/ai draft followup [Name]` — Post-cleaning follow-up\n`/ai draft winback [Name]` — Win back a lapsed customer\n`/ai draft cold_lead [Name]` — First touch to an unconverted lead\n`/ai draft airbnb_pitch [Name]` — Pitch to an Airbnb host\n`/ai draft thank_you [Name]` — Thank a loyal customer\n\nWho do you want to email and what's the situation?",
            "action_hint": "draft_email",
        },
        "complaint": {
            "text": "I'll help you handle that complaint with care. Use:\n\n`/ai complaint [Customer Name] [describe the issue]`\n\nI'll draft an empathetic response for you to review before sending. What's the customer's name and what happened?",
            "action_hint": "complaint",
        },
        "employee_profit": {
            "text": "Here's how to check employee performance:\n\n`/office profit` — This week's profitability per employee\n`/office profit last` — Last week's report\n`/office payrate` — View all pay rates\n`/office payrate [Name] [Rate]` — Update a rate\n\nWant me to pull this week's numbers?",
            "action_hint": "employee_profit",
        },
        "recommend": {
            "text": "I can give you strategic recommendations! Use:\n\n`/ai recommend [topic]`\n\nExamples:\n- `/ai recommend growth` — How to grow revenue\n- `/ai recommend retention` — How to keep customers\n- `/ai recommend hiring` — When and who to hire\n\nWhat area would you like advice on?",
            "action_hint": "recommend",
        },
        "assign_job": {
            "text": "To assign a job:\n\n`/job assign @cleaner | 123 Main St | Deep Clean | Friday 9am`\n\nJust give me the cleaner's name, address, service type, and time.",
            "action_hint": "assign_job",
        },
        "job_list": {
            "text": "To see the schedule:\n\n`/job list` — All open and assigned jobs\n\nWant me to pull it up?",
            "action_hint": "job_list",
        },
        "announce": {
            "text": "To send a team announcement:\n\n`/announce [your message]`\n\nWhat do you want to tell the team?",
            "action_hint": "announce",
        },
        "feed": {
            "text": "Here's your activity feed command:\n\n`/office feed` — Everything that's happened across all sources\n\nWant me to pull it up?",
            "action_hint": "feed",
        },
        "send_text": {
            "text": "To send a text:\n\n`/office text send [phone number] [message]`\n\nWho do you want to text and what should I say?",
            "action_hint": "send_text",
        },
        "text_inbox": {
            "text": "To check texts:\n\n`/office text inbox` — Recent incoming texts\n`/office text convo [phone number]` — Full conversation with a number\n\nWant me to pull up the inbox?",
            "action_hint": "text_inbox",
        },
        "priorities": {
            "text": "To see your priorities:\n\n`/office priorities` — AI-ranked action items based on live HCP data\n\nWant me to pull them up?",
            "action_hint": "priorities",
        },
        "eod_summary": {
            "text": "To get the end-of-day wrap-up:\n\n`/office eod` — Summary of today\n\nI also send this automatically at 5:00 PM. Want it now?",
            "action_hint": "eod_summary",
        },
        "mood_check": {
            "text": f"Hey {user_name}, how are you feeling today? You can log your mood with:\n\n`/carolyn mood [how you're feeling]`\n\nOr just tell me how your day is going and I'll note it.",
            "action_hint": "mood_check",
        },
        "learn": {
            "text": "I can remember that! Use:\n\n`/carolyn learn [category] [what to remember]`\n\nCategories: `email_style`, `customer_notes`, `business_rules`, `preferences`, `complaints`\n\nOr just tell me what to remember and I'll file it away.",
            "action_hint": "learn",
        },
        "learn_stop": {
            "text": "Got it — tell me what to stop doing and I'll remember. Use:\n\n`/carolyn learn preferences [what to stop]`\n\nFor example: `/carolyn learn preferences Never suggest upselling to Mrs. Johnson`",
            "action_hint": "learn_stop",
        },
        "ai_status": {
            "text": "To check AI system status:\n\n`/ai status` — Shows which models are active and how tasks are routed",
            "action_hint": "ai_status",
        },
        "help": {
            "text": f"Here's everything I can do, {user_name}:\n\n`/cleanhelp` — Full command reference\n\nOr just ask me in plain English! For example:\n- \"Find me residential leads in Big Sky\"\n- \"Draft a follow-up email to Sarah\"\n- \"How's the team performing this week?\"\n- \"What should I focus on today?\"\n- \"Send a text to 406-555-1234\"",
            "action_hint": "help",
        },
    }

    if intent in INTENT_COMMANDS:
        # When the user explicitly asks for HCP analysis, just run it — don't
        # make them retype `/hcp analysis`. This is the whole point of chat.
        if intent == "hcp_analysis" and runner_func:
            ran = _run_action("hcp_analysis", runner_func, user_name)
            if ran:
                return ran

        cmd = INTENT_COMMANDS[intent]
        # Remember that we offered this action so a "yes" reply can execute it.
        if user_id and cmd.get("action_hint"):
            set_pending_action(user_id, cmd["action_hint"])
        return {"text": cmd["text"], "blocks": None, "action_hint": cmd.get("action_hint")}

    # ── General chat — use AI to respond ──────────────────────────────────
    if ai_func and intent == "general_chat":
        system = f"""You are the office assistant for Montana Premium House Care, a premium cleaning company in Montana.
You are chatting with {user_name} in Slack. Be helpful, warm, and professional.
You can help with: finding leads, drafting emails, handling complaints, checking HCP data, employee profitability, scheduling, announcements, and general business advice.
If the user asks something you can help with, suggest the relevant slash command.
Keep responses concise (under 150 words). Be conversational, not robotic.
If you don't know something, say so honestly.
Do not use excessive emoji."""
        try:
            response = ai_func(message, system)
            return {"text": response, "blocks": None, "action_hint": None}
        except Exception:
            pass

    # Fallback
    return {
        "text": f"I'm not sure I understood that, {user_name}. You can ask me things like:\n- \"Find residential leads in Bozeman\"\n- \"Draft a follow-up email to Sarah\"\n- \"What are my priorities today?\"\n- \"How's the team performing?\"\n\nOr type `/cleanhelp` for the full command list.",
        "blocks": None,
        "action_hint": None,
    }
