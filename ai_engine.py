"""
ai_engine.py — Multi-Model AI Engine for Montana Premium House Care
Models: GPT-4.1-mini (reasoning), Gemini 2.5 Flash (fast), Claude (customer voice)
Falls back gracefully when models are unavailable.
"""
import os, json

from openai import OpenAI

# ── Bot Memory Integration ────────────────────────────────────────────────────
try:
    from bot_memory import get_context_for_ai, get_customer_context
    _memory_available = True
except ImportError:
    _memory_available = False
    def get_context_for_ai(task_type=None): return ""
    def get_customer_context(name): return ""

# ── Model Configuration ──────────────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
_oai_client = None
if OPENAI_API_KEY:
    try:
        _oai_client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        pass

# Claude client (optional)
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
_claude_client = None
if ANTHROPIC_API_KEY:
    try:
        import anthropic
        _claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    except ImportError:
        pass

# ── Startup Model Detection ──────────────────────────────────────────────────
# Test which models are actually available with the provided API key
_gemini_available = False
if _oai_client:
    try:
        _test = _oai_client.chat.completions.create(
            model="gemini-2.5-flash",
            messages=[{"role": "user", "content": "test"}],
            max_tokens=5,
        )
        _gemini_available = True
    except Exception:
        _gemini_available = False

# Model routing table — falls back to gpt-4.1-mini if Gemini unavailable
MODELS = {
    "reasoning":      "gpt-4.1-mini",
    "fast":           "gemini-2.5-flash" if _gemini_available else "gpt-4.1-mini",
    "customer_voice": "gpt-4.1-mini",
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
    """Call GPT-4.1 or Gemini Flash via OpenAI-compatible API with automatic fallback."""
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
        # If the model fails (e.g., gemini not available), fall back to gpt-4.1-mini
        if model != "gpt-4.1-mini":
            try:
                response = _oai_client.chat.completions.create(
                    model="gpt-4.1-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user",   "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                return response.choices[0].message.content.strip()
            except Exception as e2:
                return f"[AI Error — fallback also failed]: {str(e2)}"
        return f"[AI Error — {model}]: {str(e)}"

def _call_claude(system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """Call Claude via Anthropic API (when available)."""
    if not _claude_client:
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
        return _call_openai("gpt-4.1-mini", system_prompt, user_prompt, temperature, max_tokens)

def _route_call(task_type: str, system_prompt: str, user_prompt: str, temperature: float = 0.7, max_tokens: int = 1500) -> str:
    """Route to the best model based on task type. Injects learned memory context."""
    memory_context = get_context_for_ai(task_type=task_type)
    if memory_context:
        system_prompt = system_prompt + "\n\n--- LEARNED FROM CAROLYN (always apply these) ---\n" + memory_context + "\n--- END LEARNED CONTEXT ---"
    model = MODELS.get(task_type, "gpt-4.1-mini")
    if model == "claude":
        return _call_claude(system_prompt, user_prompt, temperature, max_tokens)
    return _call_openai(model, system_prompt, user_prompt, temperature, max_tokens)

# ── Chick-fil-A Customer Service System Prompt ───────────────────────────────
def _build_cs_system_prompt(email_type: str = "general") -> str:
    profile = _load_carolyn_profile()
    return f"""You are the customer communication voice of {BUSINESS_NAME}.
You write emails and messages on behalf of Carolyn Donaldson, Office Manager.

TONE & STYLE RULES:
- Warm, genuine, and personal — like a trusted neighbor, not a corporation
- NO emoji overload — one or zero emoji per email maximum
- NO exclamation point overload — use sparingly and only when genuinely enthusiastic
- Write like a real human wrote this, not AI
- Use contractions naturally (we're, you're, it's)
- Reference specific details about the customer when available
- Keep paragraphs short (2-3 sentences max)
- Always sound like you actually care, because we do

CAROLYN'S PREFERENCES:
- Greeting style: {profile.get('preferred_greeting', 'Hi {{name}},')}
- Sign-off: {profile.get('sign_off', 'Warm regards,')}
- Tone: {profile.get('email_tone', 'friendly')}
- CS Philosophy: {profile.get('cs_philosophy', 'Every customer should feel like our only customer.')}
- Complaint approach: {profile.get('complaint_approach', 'apologize_first')}

BUSINESS INFO:
- Business: {BUSINESS_NAME}
- Phone: {BUSINESS_PHONE}
- Email: {BUSINESS_EMAIL}
- Service area: {SERVICE_AREA}
- Services: residential, commercial (small offices), Airbnb turnover, post-construction, move-in/out, deep clean, carpet shampooing, window cleaning

IMPORTANT: Leave a [PERSONAL NOTE] placeholder in the email where Carolyn can add her own personal touch. This should be a natural spot in the email where a handwritten-feeling sentence would fit.
"""

# ── Public AI Functions ───────────────────────────────────────────────────────
def ai_draft_email(email_type: str, customer_data: dict) -> dict:
    system = _build_cs_system_prompt(email_type)
    customer_context = get_customer_context(customer_data.get("name", "")) if _memory_available else ""
    if customer_context:
        system += f"\n\nWHAT WE KNOW ABOUT THIS CUSTOMER:\n{customer_context}"
    prompts = {
        "followup": f"Write a follow-up email to {customer_data.get('name', 'the customer')} after their recent cleaning. Thank them, ask how everything looks, and invite them to book again. Include a [PERSONAL NOTE] placeholder.",
        "winback": f"Write a win-back email to {customer_data.get('name', 'the customer')} who hasn't booked in {customer_data.get('days_lapsed', '60+')} days. Be warm, not pushy. Mention we miss seeing them. Include a [PERSONAL NOTE] placeholder.",
        "cold_lead": f"Write a first-touch email to {customer_data.get('name', 'the potential customer')} who submitted an estimate request {customer_data.get('days_ago', 'recently')} but never booked. Be helpful, not salesy. Include a [PERSONAL NOTE] placeholder.",
        "airbnb_pitch": f"Write an outreach email to {customer_data.get('name', 'the property manager')} who manages Airbnb/STR properties. Pitch our turnover cleaning service. Be professional but personable. Include a [PERSONAL NOTE] placeholder.",
        "thank_you": f"Write a heartfelt thank-you email to {customer_data.get('name', 'the customer')} for being a loyal customer. Mention they've been with us for {customer_data.get('tenure', 'a while')}. Include a [PERSONAL NOTE] placeholder.",
    }
    prompt = prompts.get(email_type, f"Write a professional {email_type} email to {customer_data.get('name', 'the customer')}. Include a [PERSONAL NOTE] placeholder.")
    model_used = MODELS["customer_voice"]
    body = _route_call("customer_voice", system, prompt, temperature=0.7, max_tokens=800)
    subject_prompt = f"Write a short, natural email subject line for this {email_type} email to {customer_data.get('name', 'a customer')} from a cleaning company. No quotes, no emoji, just the subject line text."
    subject = _route_call("fast", "You write email subject lines. Return only the subject line, nothing else.", subject_prompt, temperature=0.8, max_tokens=50)
    return {"subject": subject, "body": body, "model_used": model_used, "email_type": email_type}

def ai_handle_complaint(customer_name: str, complaint_text: str) -> dict:
    profile = _load_carolyn_profile()
    system = f"""You are the complaint resolution specialist for {BUSINESS_NAME}.
Carolyn Donaldson handles complaints with a '{profile.get('complaint_approach', 'apologize_first')}' approach.

COMPLAINT RESPONSE PROTOCOL:
1. Acknowledge the customer's frustration immediately
2. Apologize sincerely — take ownership, no excuses
3. Explain what happened (if known) without blaming anyone
4. Offer a concrete solution (re-clean, discount, refund)
5. End with a personal commitment to make it right

TONE: Empathetic, humble, solution-focused. No corporate speak. No emoji.
Write as if Carolyn is personally responding.

FORMAT YOUR RESPONSE AS:
CUSTOMER RESPONSE: [the email/message to send to the customer]
INTERNAL NOTES: [what Carolyn should know, who to talk to, whether to escalate]
ESCALATE TO CHRIS: [YES/NO]
"""
    prompt = f"Customer: {customer_name}\nComplaint: {complaint_text}\n\nGenerate the response following the protocol above."
    model_used = MODELS["customer_voice"]
    result = _route_call("customer_voice", system, prompt, temperature=0.6, max_tokens=1500)
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
    system = f"You are a concise business analyst for {BUSINESS_NAME}. Summarize the following {context} in 3-5 bullet points. Be specific with numbers and actionable insights."
    return _route_call("fast", system, text, temperature=0.3, max_tokens=500)

def ai_recommend(topic: str, business_data: str = "") -> str:
    profile = _load_carolyn_profile()
    system = f"""You are a senior business consultant for {BUSINESS_NAME}, a premium cleaning company in Montana.
Service areas: {SERVICE_AREA}
Services: residential, commercial (small offices), Airbnb turnover, post-construction, move-in/out, carpet shampooing, window cleaning
Team size: 10 employees
Office Manager: Carolyn Donaldson (priority style: {profile.get('priority_style', 'customer_first')})
Owner: {OWNER_NAME}
Provide specific, actionable recommendations. Include numbers, timelines, and concrete next steps.
Reference the Slack bot commands Carolyn can use to take action (e.g., /leads find, /ai draft, /hcp analysis).
"""
    prompt = f"Topic: {topic}\n\nBusiness data:\n{business_data}\n\nProvide 3 specific, prioritized recommendations with action steps."
    return _route_call("reasoning", system, prompt, temperature=0.6, max_tokens=1200)

def ai_morning_brief(jobs_today: int, uninvoiced: int, open_estimates: int, lapsed: int, new_leads: int, platform_summary: str = "") -> str:
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
        if _gemini_available:
            status["gemini-2.5-flash"] = "✅ Active — Fast lead scoring & summaries"
        else:
            status["gemini-2.5-flash"] = "⚠️ Unavailable — Using gpt-4.1-mini as fallback"
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
