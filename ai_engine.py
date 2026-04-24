"""
Montana Premium House Care — Multi-Model AI Engine
====================================================
Routes tasks to the best AI model for the job:
  - GPT-4.1-mini   → Business analysis, reasoning, recommendations
  - Gemini Flash    → Fast lead scoring, quick summaries, real-time processing
  - Claude (ready)  → Warm customer service writing, empathetic complaint handling

Architecture:
  - Each model is accessed via the OpenAI-compatible API
  - Claude drops in seamlessly when ANTHROPIC_API_KEY is added to .env
  - The router selects the best model per task type automatically
  - Carolyn's profile preferences are injected into every prompt

Usage:
  from ai_engine import ai_draft_email, ai_score_lead, ai_handle_complaint, ai_summarize, ai_recommend
"""

import os
import json
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# ── Model Configuration ──────────────────────────────────────────────────────

# OpenAI-compatible client — requires OPENAI_API_KEY in .env
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_oai_client = None
if OPENAI_API_KEY:
    try:
        _oai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        pass

# Claude client (optional — drops in when key is provided)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_claude_client = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        pass  # anthropic package not installed

# Model routing table
MODELS = {
    "reasoning":      "gpt-4.1-mini",       # Deep analysis, business logic
    "fast":           "gemini-2.5-flash",    # Quick summaries, lead scoring, real-time
    "customer_voice": "gpt-4.1-mini",       # Customer-facing writing (upgraded to Claude when available)
}

# If Claude is available, use it for customer-facing writing
if _claude_client:
    MODELS["customer_voice"] = "claude"

BUSINESS_NAME  = os.getenv("BUSINESS_NAME",  "Montana Premium House Care")
OWNER_NAME     = os.getenv("OWNER_NAME",     "Chris Johnson")
BUSINESS_PHONE = os.getenv("BUSINESS_PHONE", "406-599-2699")
BUSINESS_EMAIL = os.getenv("BUSINESS_EMAIL", "mtpremiumhousecare@gmail.com")
SERVICE_AREA   = os.getenv("SERVICE_AREA",   "Bozeman, Gallatin County, Livingston, Belgrade, Big Sky, Kalispell, Whitefish")

# ── Carolyn's Profile Loader ─────────────────────────────────────────────────

def _load_carolyn_profile():
    """Load Carolyn's preferences to inject into prompts."""
    profile_path = os.path.join(os.path.dirname(__file__), "carolyn_profile_data.json")
    defaults = {
        "email_tone": "friendly",
        "preferred_greeting": "Hi {name},",
        "sign_off": "Warm regards,",
        "cs_philosophy": "Every customer should feel like they're our only customer.",
        "complaint_approach": "apologize_first",
        "escalation_style": "both",
    }
    if os.path.exists(profile_path):
        try:
            with open(profile_path, "r") as f:
                data = json.load(f)
            return {**defaults, **{k: v for k, v in data.items() if v is not None}}
        except Exception:
            pass
    return defaults


# ── Core AI Call Functions ────────────────────────────────────────────────────

def _call_openai(model: str, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """Call GPT-4.1 or Gemini Flash via OpenAI-compatible API."""
    if not _oai_client:
        return "[AI Unavailable] Add OPENAI_API_KEY to your .env file and restart the bot."
    try:
        response = _oai_client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"[AI Error — {model}]: {str(e)}"


def _call_claude(system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """Call Claude via Anthropic API (when available)."""
    if not _claude_client:
        # Fallback to GPT-4.1-mini
        return _call_openai("gpt-4.1-mini", system_prompt, user_prompt, temperature, max_tokens)
    try:
        response = _claude_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            temperature=temperature,
        )
        return response.content[0].text.strip()
    except Exception as e:
        # Fallback to GPT-4.1-mini
        return _call_openai("gpt-4.1-mini", system_prompt, user_prompt, temperature, max_tokens)


def _route_call(task_type: str, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """Route to the best model based on task type."""
    model = MODELS.get(task_type, "gpt-4.1-mini")
    if model == "claude":
        return _call_claude(system_prompt, user_prompt, temperature, max_tokens)
    return _call_openai(model, system_prompt, user_prompt, temperature, max_tokens)


# ── Chick-fil-A Customer Service System Prompt ───────────────────────────────

def _build_cs_system_prompt(profile: dict = None) -> str:
    """Build the master customer service system prompt with Carolyn's preferences."""
    p = profile or _load_carolyn_profile()
    tone = p.get("email_tone", "friendly")
    greeting = p.get("preferred_greeting", "Hi {name},")
    sign_off = p.get("sign_off", "Warm regards,")
    philosophy = p.get("cs_philosophy", "Every customer should feel like they're our only customer.")

    return f"""You are the AI-powered customer service assistant for {BUSINESS_NAME}, a premium residential and commercial cleaning company in Montana.

BUSINESS INFO:
- Business: {BUSINESS_NAME}
- Owner: {OWNER_NAME}
- Phone: {BUSINESS_PHONE}
- Email: {BUSINESS_EMAIL}
- Service Areas: {SERVICE_AREA}
- Services: Residential cleaning, deep cleans, move-in/out, Airbnb turnover, post-construction, carpet shampooing, window cleaning, recurring weekly/biweekly

CUSTOMER SERVICE STANDARD — CHICK-FIL-A LEVEL:
You must embody the absolute highest standard of customer service in every interaction. This means:

1. WARMTH FIRST: Every response begins with genuine warmth. The customer should feel valued before anything else.
2. "MY PLEASURE": Never say "no problem" or "you're welcome." Use "My pleasure," "Absolutely," "We'd love to," "It would be our honor."
3. PROACTIVE CARE: Anticipate what the customer needs before they ask. Offer solutions they haven't thought of.
4. OWNERSHIP: Never blame, never deflect. Own every situation. "I'm going to personally make sure this is taken care of."
5. SPEED WITH GRACE: Respond quickly but never feel rushed. Every word should feel intentional and caring.
6. PERSONAL TOUCH: Use the customer's first name. Reference their specific situation. Make them feel known.
7. RECOVERY EXCELLENCE: When something goes wrong, the recovery should be so good that the customer becomes MORE loyal, not less.
8. EXCEED EXPECTATIONS: Always give a little more than expected. A follow-up call, a handwritten note, a small extra service.
9. GRATITUDE: Express genuine gratitude for their business. "We're truly grateful you chose us."
10. SECOND MILE: Go the extra mile, then go one more. "Is there anything else at all I can help you with?"

CAROLYN'S PREFERENCES:
- Email tone: {tone}
- Greeting style: {greeting}
- Sign-off: {sign_off}
- Customer service philosophy: "{philosophy}"
- Complaint approach: {p.get('complaint_approach', 'apologize_first').replace('_', ' ')}

WRITING RULES:
- Always use Carolyn's preferred greeting and sign-off
- Match her tone preference ({tone})
- Sign emails as: {OWNER_NAME}, {BUSINESS_NAME} (unless Carolyn specifies otherwise)
- Include phone number {BUSINESS_PHONE} and email {BUSINESS_EMAIL} in sign-offs
- Keep emails concise but warm — no fluff, but full of care
- Never use generic language. Every email should feel personally written for that specific customer.
"""


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API — Used by bot.py slash commands
# ─────────────────────────────────────────────────────────────────────────────

def ai_draft_email(email_type: str, customer_name: str, context: str = "") -> dict:
    """
    Draft a customer email using AI with Chick-fil-A level service.
    Returns: {"subject": str, "body": str, "model_used": str}
    """
    profile = _load_carolyn_profile()
    system = _build_cs_system_prompt(profile)

    type_prompts = {
        "estimate_followup": f"Write a warm follow-up email to {customer_name} who received a cleaning estimate but hasn't booked yet. Make them feel valued, not pressured. Offer to answer any questions.",
        "win_back": f"Write a heartfelt win-back email to {customer_name} who cancelled a previous job. Express that we miss them, take ownership of any past issues, and offer a complimentary add-on to welcome them back.",
        "reengagement": f"Write a friendly re-engagement email to {customer_name} who hasn't booked in over 60 days. Check in on them personally, remind them of our services, and make it easy to rebook.",
        "airbnb_pitch": f"Write a professional but warm pitch email to {customer_name} who manages short-term rentals. Highlight our reliability, speed, and 7-day availability for turnover cleans.",
        "review_request": f"Write a gracious email to {customer_name} asking for a Google review after a recent cleaning. Express genuine gratitude and make the ask feel natural, not transactional.",
        "upsell_carpet_window": f"Write a friendly email to {customer_name} (an existing customer) introducing our carpet shampooing and window cleaning services as add-ons to their regular clean.",
        "post_construction": f"Write a professional pitch email to {customer_name} (a builder/contractor) offering our post-construction cleaning services. Emphasize our thoroughness and ability to meet tight deadlines.",
        "complaint_response": f"Write a compassionate response to {customer_name} who has a complaint about our service. {context}. Lead with empathy, take full ownership, and offer a concrete resolution that exceeds their expectations.",
        "thank_you": f"Write a heartfelt thank-you email to {customer_name} after completing a job. Make them feel genuinely appreciated and plant the seed for their next booking.",
        "welcome": f"Write a warm welcome email to {customer_name} who just booked their first cleaning with us. Make them feel excited about their decision and set expectations for an amazing experience.",
        "reschedule": f"Write a gracious email to {customer_name} about rescheduling their appointment. {context}. Be apologetic if we initiated, understanding if they did, and make rescheduling effortless.",
    }

    prompt = type_prompts.get(email_type, f"Write a professional email to {customer_name}. Context: {context}")
    prompt += f"\n\nAdditional context: {context}" if context and email_type in type_prompts else ""
    prompt += "\n\nReturn ONLY the email with Subject: on the first line, then a blank line, then the body. No extra commentary."

    model_used = MODELS["customer_voice"]
    result = _route_call("customer_voice", system, prompt, temperature=0.7, max_tokens=1200)

    # Parse subject and body
    lines = result.strip().split("\n")
    subject = ""
    body_start = 0
    for i, line in enumerate(lines):
        if line.lower().startswith("subject:"):
            subject = line.split(":", 1)[1].strip()
            body_start = i + 1
            break

    # Skip blank lines after subject
    while body_start < len(lines) and not lines[body_start].strip():
        body_start += 1

    body = "\n".join(lines[body_start:]).strip() if body_start < len(lines) else result

    return {"subject": subject or f"From {BUSINESS_NAME}", "body": body, "model_used": model_used}


def ai_score_lead(lead: dict) -> dict:
    """
    Score and classify an incoming lead using Gemini Flash (fast).
    Returns: {"score": 1-10, "priority": "high|medium|low", "reasoning": str, "suggested_action": str}
    """
    system = f"""You are a lead scoring AI for {BUSINESS_NAME}, a cleaning company in Montana.
Score each lead from 1-10 based on:
- Likelihood to convert (based on service type, location, urgency)
- Potential lifetime value (recurring vs one-time)
- Match to our service areas: {SERVICE_AREA}
- Match to our services: residential, commercial (small offices), Airbnb turnover, post-construction, move-in/out, carpet shampooing, window cleaning

Return ONLY valid JSON: {{"score": <1-10>, "priority": "<high|medium|low>", "reasoning": "<one sentence>", "suggested_action": "<specific next step>"}}"""

    prompt = f"""Score this lead:
- Name: {lead.get('name', 'Unknown')}
- Platform: {lead.get('platform', 'Unknown')}
- Service Requested: {lead.get('service', 'Unknown')}
- Location: {lead.get('address', lead.get('city', 'Unknown'))}
- Message: {lead.get('message', 'None')}
- Budget: {lead.get('budget', 'Unknown')}"""

    result = _route_call("fast", system, prompt, temperature=0.3, max_tokens=300)

    try:
        # Try to parse JSON from the response
        # Handle cases where the model wraps JSON in markdown code blocks
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0]
        return json.loads(cleaned)
    except (json.JSONDecodeError, Exception):
        return {"score": 5, "priority": "medium", "reasoning": result[:200], "suggested_action": "Review manually"}


def ai_handle_complaint(customer_name: str, complaint_text: str) -> dict:
    """
    Generate a Chick-fil-A level complaint response using the customer_voice model.
    Returns: {"response": str, "internal_notes": str, "escalate": bool, "model_used": str}
    """
    profile = _load_carolyn_profile()
    system = _build_cs_system_prompt(profile)
    system += """

COMPLAINT HANDLING PROTOCOL:
1. Acknowledge their feelings immediately — "I completely understand your frustration"
2. Apologize sincerely — "I'm truly sorry this happened"
3. Take ownership — "This is on us, and I take full responsibility"
4. Offer a concrete resolution — specific action, timeline, and something extra
5. Express gratitude — "Thank you for giving us the chance to make this right"
6. Follow up promise — "I will personally follow up with you"

Also provide internal notes for Carolyn on what to investigate and whether to escalate to Chris.

Return the response in this format:
CUSTOMER RESPONSE:
[the email/message to send to the customer]

INTERNAL NOTES:
[notes for Carolyn — what to investigate, who to talk to, whether to escalate]

ESCALATE TO CHRIS: [YES/NO]
"""

    prompt = f"Customer: {customer_name}\nComplaint: {complaint_text}\n\nGenerate the response following the protocol above."

    model_used = MODELS["customer_voice"]
    result = _route_call("customer_voice", system, prompt, temperature=0.6, max_tokens=1500)

    # Parse sections
    response = ""
    internal = ""
    escalate = False

    if "CUSTOMER RESPONSE:" in result:
        parts = result.split("INTERNAL NOTES:")
        response = parts[0].replace("CUSTOMER RESPONSE:", "").strip()
        if len(parts) > 1:
            internal_section = parts[1]
            if "ESCALATE TO CHRIS:" in internal_section:
                int_parts = internal_section.split("ESCALATE TO CHRIS:")
                internal = int_parts[0].strip()
                escalate = "YES" in int_parts[1].upper() if len(int_parts) > 1 else False
            else:
                internal = internal_section.strip()
    else:
        response = result

    return {"response": response, "internal_notes": internal, "escalate": escalate, "model_used": model_used}


def ai_summarize(text: str, context: str = "business data") -> str:
    """
    Quick summary using Gemini Flash.
    Used for daily briefs, lead digests, and job summaries.
    """
    system = f"You are a concise business analyst for {BUSINESS_NAME}. Summarize the following {context} in 3-5 bullet points. Be specific with numbers and actionable insights."
    return _route_call("fast", system, text, temperature=0.3, max_tokens=500)


def ai_recommend(topic: str, business_data: str = "") -> str:
    """
    Generate a strategic business recommendation using GPT-4.1.
    """
    profile = _load_carolyn_profile()
    system = f"""You are a senior business consultant for {BUSINESS_NAME}, a premium cleaning company in Montana.
Service areas: {SERVICE_AREA}
Services: residential, commercial (small offices), Airbnb turnover, post-construction, move-in/out, carpet shampooing, window cleaning
Team size: 10 employees
Office Manager: Carolyn Donaldson (priority style: {profile.get('priority_style', 'customer_first')})
Owner: {OWNER_NAME}

Provide specific, actionable recommendations. Include numbers, timelines, and concrete next steps.
Reference the Slack bot commands Carolyn can use to take action (e.g., /findleads, /draftemail, /hcpanalysis).
"""

    prompt = f"Topic: {topic}\n\nBusiness data:\n{business_data}\n\nProvide 3 specific, prioritized recommendations with action steps."
    return _route_call("reasoning", system, prompt, temperature=0.6, max_tokens=1200)


def ai_morning_brief(jobs_today: int, uninvoiced: int, open_estimates: int, lapsed: int, new_leads: int, platform_summary: str = "") -> str:
    """
    Generate a personalized morning brief narrative for Carolyn using Gemini Flash.
    """
    profile = _load_carolyn_profile()
    mood_log = profile.get("mood_log", [])
    last_mood = mood_log[-1]["mood"] if mood_log else "unknown"

    system = f"""You are Carolyn Donaldson's personal office assistant at {BUSINESS_NAME}.
Write a brief, warm morning message for her. Be encouraging and specific.
Her priority style is: {profile.get('priority_style', 'customer_first')}
Her biggest challenge is: {profile.get('biggest_challenge', 'managing everything')}
Her last mood check-in was: {last_mood}
Keep it under 150 words. Be warm but professional. End with her top 3 things to focus on today."""

    prompt = f"""Today's numbers:
- Jobs scheduled today: {jobs_today}
- Uninvoiced completed jobs: {uninvoiced}
- Open estimates awaiting response: {open_estimates}
- Lapsed customers (60+ days): {lapsed}
- New leads across all platforms: {new_leads}
{f'- Platform breakdown: {platform_summary}' if platform_summary else ''}

Write Carolyn's morning brief."""

    return _route_call("fast", system, prompt, temperature=0.7, max_tokens=400)


def get_ai_status() -> dict:
    """Return the current status of all AI models."""
    status = {}
    if _oai_client:
        status["gpt-4.1-mini"] = "✅ Active — Business analysis & reasoning"
        status["gemini-2.5-flash"] = "✅ Active — Fast lead scoring & summaries"
    else:
        status["gpt-4.1-mini"] = "⚠️ Not configured — Add OPENAI_API_KEY to .env"
        status["gemini-2.5-flash"] = "⚠️ Not configured — Add OPENAI_API_KEY to .env"
    if _claude_client:
        status["claude"] = "✅ Active — Premium customer service writing"
    else:
        status["claude"] = "⚠️ Not configured — Add ANTHROPIC_API_KEY to .env for premium CS writing"

    routing = {
        "Email drafting":       MODELS["customer_voice"],
        "Complaint handling":   MODELS["customer_voice"],
        "Lead scoring":         MODELS["fast"],
        "Quick summaries":      MODELS["fast"],
        "Business analysis":    MODELS["reasoning"],
        "Recommendations":      MODELS["reasoning"],
        "Morning briefs":       MODELS["fast"],
    }

    return {"models": status, "routing": routing}
