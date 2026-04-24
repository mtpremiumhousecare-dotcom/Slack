"""
Montana Premium House Care — Chick-fil-A Level Customer Service Module
=======================================================================
This module provides:
  1. Service Standards & Scripts — Pre-built response templates for every scenario
  2. AI-Powered Complaint Handler — Generates empathetic, ownership-driven responses
  3. Customer Lifecycle Tracker — Tracks where each customer is in their journey
  4. Service Recovery Protocol — Turns complaints into loyalty
  5. Proactive Outreach Engine — Anticipates customer needs before they ask
  6. Quality Assurance Checklists — Post-job quality standards

Commands:
  /servicescript [scenario]  — Get a Chick-fil-A level response script
  /complaint [name] [issue]  — AI-generates a complaint response for Carolyn's review
  /servicestandards          — View the full service standards guide
  /qualitycheck              — Post-job quality assurance checklist
  /wowmoment [name]          — Generate a "wow moment" idea for a specific customer
"""

import os
import json
import datetime

# ── Chick-fil-A Inspired Service Standards ────────────────────────────────────

SERVICE_STANDARDS = {
    "core_values": [
        "Every customer is our ONLY customer in that moment",
        "We don't say 'No problem' — we say 'My pleasure'",
        "We own every outcome — good or bad",
        "Speed is important, but care is more important",
        "We leave every home better than expected",
        "Gratitude is not optional — it's our culture",
    ],
    "language_guide": {
        "never_say": [
            ("No problem", "My pleasure"),
            ("We can't do that", "Here's what we CAN do"),
            ("That's not our fault", "I understand, and I'm going to fix this"),
            ("You should have...", "Next time, we'll make sure to..."),
            ("I don't know", "Great question — let me find out for you right away"),
            ("That's our policy", "I want to find the best solution for you"),
            ("Calm down", "I completely understand your frustration"),
            ("We're busy", "You're important to us — let me find the earliest time"),
        ],
        "always_say": [
            "My pleasure!",
            "Absolutely, we'd love to help with that.",
            "Thank you for choosing Montana Premium House Care.",
            "Is there anything else I can do to make your experience even better?",
            "We're truly grateful for your trust in us.",
            "I'm going to personally make sure this is taken care of.",
            "Your satisfaction means everything to us.",
        ],
    },
}

# ── Response Scripts for Common Scenarios ─────────────────────────────────────

SCRIPTS = {
    "new_inquiry": {
        "title": "New Customer Inquiry",
        "scenario": "Someone calls or messages asking about services",
        "script": (
            "Thank you so much for reaching out to Montana Premium House Care! "
            "My name is {agent_name}, and I'd love to help you.\n\n"
            "Can I start by getting your name? ... {customer_name}, it's wonderful to meet you! "
            "Tell me a little about what you're looking for — I want to make sure we take perfect care of you.\n\n"
            "[Listen actively, take notes, repeat back what they said]\n\n"
            "That sounds great, {customer_name}. We would absolutely love to help with that. "
            "Let me tell you what we can do for you...\n\n"
            "[Present services, pricing, availability]\n\n"
            "Is there anything else you'd like to know? I want to make sure you feel completely "
            "comfortable before we get started.\n\n"
            "Thank you again for considering us, {customer_name}. It would be our pleasure to serve you!"
        ),
    },
    "booking_confirmation": {
        "title": "Booking Confirmation Call/Text",
        "scenario": "Confirming a scheduled cleaning",
        "script": (
            "Hi {customer_name}! This is {agent_name} from Montana Premium House Care. "
            "I'm calling to confirm your {service_type} scheduled for {date_time}.\n\n"
            "Our team will arrive right on time, and we'll make sure everything is absolutely spotless for you. "
            "Is there anything special you'd like us to focus on or any areas that need extra attention?\n\n"
            "[Note any special requests]\n\n"
            "Perfect! We've got that noted. We're really looking forward to taking care of your home, "
            "{customer_name}. If anything comes up before then, don't hesitate to call us at 406-599-2699. "
            "Thank you so much!"
        ),
    },
    "post_clean_followup": {
        "title": "Post-Clean Follow-Up",
        "scenario": "Following up after a completed job",
        "script": (
            "Hi {customer_name}! This is {agent_name} from Montana Premium House Care. "
            "I just wanted to personally check in and make sure everything looks wonderful after your cleaning today.\n\n"
            "How does everything look? ... [Listen]\n\n"
            "[If happy]: That makes me so happy to hear! Our team takes such pride in their work, "
            "and I'll be sure to pass along your kind words. Is there anything else at all we can do for you?\n\n"
            "[If issue]: Oh, I'm so sorry about that, {customer_name}. That is absolutely not the standard "
            "we hold ourselves to. I'm going to personally make sure this gets taken care of right away. "
            "Can I send someone back out [today/tomorrow] to make it right?\n\n"
            "Thank you so much for your time, {customer_name}. We truly appreciate your business, "
            "and it's our pleasure to take care of your home!"
        ),
    },
    "complaint": {
        "title": "Customer Complaint Response",
        "scenario": "Customer is unhappy with service",
        "script": (
            "{customer_name}, first and foremost, thank you for bringing this to my attention. "
            "I am truly sorry that your experience didn't meet the high standard we set for ourselves.\n\n"
            "I want you to know that I hear you, and your feelings are completely valid. "
            "This is not the experience we want any of our customers to have.\n\n"
            "Here's what I'm going to do right now:\n"
            "1. I'm personally looking into exactly what happened\n"
            "2. I'm going to make this right for you — [specific resolution]\n"
            "3. I'm going to follow up with you personally to make sure you're 100% satisfied\n\n"
            "Additionally, as a thank-you for your patience and for giving us the chance to make this right, "
            "I'd like to [offer: complimentary add-on service / discount on next clean / free re-clean].\n\n"
            "Your trust means everything to us, {customer_name}, and I'm committed to earning it back. "
            "Is there anything else I can do for you right now?"
        ),
    },
    "cancellation_save": {
        "title": "Cancellation Save Attempt",
        "scenario": "Customer wants to cancel their service",
        "script": (
            "I'm sorry to hear that, {customer_name}. We've truly valued having you as part of the "
            "Montana Premium House Care family.\n\n"
            "Would you mind sharing what's prompting the change? I ask because I genuinely want to "
            "understand — and if there's anything we can do differently, I'd love the chance to make it right.\n\n"
            "[Listen carefully — don't interrupt]\n\n"
            "[If pricing]: I completely understand. Let me see what I can do — your loyalty means a lot to us, "
            "and I'd love to find a way to make this work for your budget.\n\n"
            "[If quality]: That's really important feedback, and I'm sorry we fell short. "
            "I'd love the chance to show you what we're truly capable of — can I offer a complimentary "
            "deep clean so you can see the difference?\n\n"
            "[If scheduling]: Absolutely, we want to work around YOUR schedule. Let me see what other "
            "time slots we have available.\n\n"
            "Regardless of what you decide, {customer_name}, we're grateful for the time you've spent with us. "
            "And our door is always open if you'd like to come back."
        ),
    },
    "price_objection": {
        "title": "Price Objection Response",
        "scenario": "Customer says the price is too high",
        "script": (
            "I completely understand, {customer_name}, and I appreciate you being upfront about that. "
            "Pricing is an important consideration.\n\n"
            "I'd love to share what's included in our service so you can see the full picture:\n"
            "• Our team is fully trained, insured, and background-checked\n"
            "• We use premium, eco-friendly cleaning products\n"
            "• Every clean includes a quality inspection\n"
            "• We guarantee your satisfaction — if anything isn't right, we'll come back and fix it at no charge\n\n"
            "Many of our customers tell us that the peace of mind and consistency is worth every penny. "
            "That said, I want to find something that works for you. "
            "Would you like me to look at a few different options or packages?\n\n"
            "We'd truly love to earn your business, {customer_name}."
        ),
    },
    "referral_ask": {
        "title": "Referral Request",
        "scenario": "Asking a happy customer for referrals",
        "script": (
            "{customer_name}, I'm so glad you're happy with our service! That truly means the world to us.\n\n"
            "I have a small favor to ask — if you know anyone who might benefit from our cleaning services, "
            "we'd be so grateful for a referral. As a thank-you, we offer [referral incentive] "
            "for every new customer you send our way.\n\n"
            "There's no pressure at all — just knowing you'd recommend us is the highest compliment "
            "we could receive. Thank you for being such a wonderful customer, {customer_name}!"
        ),
    },
    "review_request": {
        "title": "Google Review Request",
        "scenario": "Asking for a Google review after a great clean",
        "script": (
            "Hi {customer_name}! We're so happy you loved your cleaning today! 😊\n\n"
            "If you have just a moment, it would mean the world to our small team if you could "
            "leave us a quick Google review. It helps other families in {area} find us, "
            "and it's the best way to support a local business.\n\n"
            "[Google Review Link]\n\n"
            "Thank you so much — we're truly grateful for your support and your trust in us! 💛"
        ),
    },
}

# ── WOW Moment Generator ─────────────────────────────────────────────────────

WOW_MOMENTS = [
    "Send a handwritten thank-you card after their first clean",
    "Leave a small bouquet of flowers on their kitchen counter after a deep clean",
    "Include a complimentary lavender sachet in their linen closet",
    "Send a 'Happy Home Anniversary' message on the 1-year mark of their first booking",
    "Offer a free window cleaning on their birthday month",
    "Leave a personalized note from the cleaner: 'It was my pleasure to take care of your home today!'",
    "Send a seasonal care tip email (spring cleaning checklist, winter home prep, etc.)",
    "After 5 recurring cleans, surprise them with a complimentary carpet spot treatment",
    "Send a 'Welcome Home' message after they return from vacation with a freshly cleaned house",
    "Include a small bottle of our favorite eco-friendly cleaner as a gift on their 10th booking",
    "Offer a complimentary fridge clean-out before Thanksgiving or Christmas",
    "Send their kids a coloring page about keeping a clean room (for families with young children)",
    "Leave a mint or chocolate on their pillow after a bedroom deep clean",
    "Send a handwritten holiday card signed by the whole team",
    "Offer a free 'spring refresh' add-on to loyal recurring customers each April",
]

# ── Service Recovery Protocol ─────────────────────────────────────────────────

RECOVERY_PROTOCOL = {
    "steps": [
        {
            "step": 1,
            "title": "Acknowledge & Empathize",
            "time": "Within 30 minutes of complaint",
            "action": "Call the customer. Listen without interrupting. Say: 'I'm truly sorry. Your feelings are completely valid.'",
        },
        {
            "step": 2,
            "title": "Investigate",
            "time": "Within 2 hours",
            "action": "Talk to the cleaning team. Review the job checklist. Identify what went wrong.",
        },
        {
            "step": 3,
            "title": "Resolve & Exceed",
            "time": "Within 4 hours",
            "action": "Offer a specific resolution PLUS something extra. Options: free re-clean, complimentary add-on, discount on next service.",
        },
        {
            "step": 4,
            "title": "Follow Up",
            "time": "24 hours after resolution",
            "action": "Call the customer personally. Ask: 'Is there anything else I can do?' Confirm they're satisfied.",
        },
        {
            "step": 5,
            "title": "Prevent Recurrence",
            "time": "Within 48 hours",
            "action": "Update team training. Add to quality checklist. Document in the service log.",
        },
        {
            "step": 6,
            "title": "Win Loyalty",
            "time": "1 week later",
            "action": "Send a handwritten note thanking them for their patience. Include a small gift or discount code.",
        },
    ],
    "resolution_options": {
        "minor_issue": "Complimentary add-on service (carpet spot treatment or window wipe-down) on next visit",
        "moderate_issue": "Free re-clean of affected areas within 24 hours + complimentary add-on",
        "major_issue": "Full re-clean at no charge + 50% off next service + personal call from Chris Johnson",
        "severe_issue": "Full refund + free re-clean + complimentary deep clean + personal call from Chris + handwritten apology",
    },
}

# ── Quality Assurance Checklist ───────────────────────────────────────────────

QA_CHECKLIST = {
    "standard_clean": [
        "All floors vacuumed/mopped — no debris or streaks",
        "All surfaces dusted and wiped — counters, tables, shelves",
        "Bathrooms sanitized — toilet, sink, shower, mirror",
        "Kitchen cleaned — counters, stovetop, sink, appliances wiped",
        "Trash emptied and new bags placed",
        "Beds made (if requested)",
        "Light switches and door handles wiped",
        "No cleaning supplies or equipment left behind",
        "Pleasant scent throughout — not overpowering",
        "Final walkthrough completed by team lead",
    ],
    "deep_clean": [
        "All standard clean items PLUS:",
        "Inside of oven cleaned",
        "Inside of refrigerator cleaned",
        "Baseboards wiped",
        "Ceiling fans and light fixtures dusted",
        "Window sills and tracks cleaned",
        "Behind and under furniture cleaned",
        "Grout scrubbed in bathrooms",
        "Cabinet fronts wiped",
        "All vents and registers dusted",
    ],
    "move_in_out": [
        "All deep clean items PLUS:",
        "Inside all cabinets and drawers wiped",
        "Inside all closets cleaned",
        "Garage swept (if applicable)",
        "All light fixtures cleaned",
        "All outlet covers wiped",
        "Windowsills and blinds cleaned",
        "Fireplace area cleaned (if applicable)",
        "Final photo documentation for property manager",
    ],
    "airbnb_turnover": [
        "All standard clean items PLUS:",
        "Linens changed and beds made hotel-style",
        "Towels folded and staged",
        "Amenities restocked (soap, shampoo, toilet paper)",
        "Welcome materials arranged",
        "Dishwasher emptied and dishes put away",
        "Coffee maker cleaned and fresh supplies set",
        "Thermostat set to welcome temperature",
        "All lights turned on for guest arrival",
        "Photo of completed setup sent to host",
    ],
}


def get_script(scenario: str, **kwargs) -> dict:
    """Get a service script with variables filled in."""
    script_data = SCRIPTS.get(scenario)
    if not script_data:
        return None
    filled = script_data["script"].format(
        customer_name=kwargs.get("customer_name", "[Customer Name]"),
        agent_name=kwargs.get("agent_name", "Carolyn"),
        service_type=kwargs.get("service_type", "cleaning"),
        date_time=kwargs.get("date_time", "[Date/Time]"),
        area=kwargs.get("area", "Bozeman"),
    )
    return {**script_data, "script": filled}


def get_wow_moment(customer_name: str = "", customer_history: str = "") -> str:
    """Get a personalized wow moment suggestion."""
    import random
    base = random.choice(WOW_MOMENTS)
    if customer_name:
        base = base.replace("their", f"{customer_name}'s").replace("them", customer_name)
    return base


def get_qa_checklist(job_type: str) -> list:
    """Get the QA checklist for a specific job type."""
    return QA_CHECKLIST.get(job_type, QA_CHECKLIST["standard_clean"])


def format_recovery_protocol_for_slack() -> list:
    """Format the service recovery protocol as Slack blocks."""
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "🛡️ Service Recovery Protocol — Chick-fil-A Standard"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Turn every complaint into a loyalty moment_"}]},
        {"type": "divider"},
    ]
    for step in RECOVERY_PROTOCOL["steps"]:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": (
                f"*Step {step['step']}: {step['title']}*\n"
                f"⏰ _{step['time']}_\n"
                f"👉 {step['action']}"
            )},
        })
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "section",
        "text": {"type": "mrkdwn", "text": (
            "*Resolution Options by Severity:*\n"
            + "\n".join([f"• *{k.replace('_',' ').title()}:* {v}" for k, v in RECOVERY_PROTOCOL["resolution_options"].items()])
        )},
    })
    return blocks


def format_standards_for_slack() -> list:
    """Format the service standards as Slack blocks."""
    lang = SERVICE_STANDARDS["language_guide"]
    never_say = "\n".join([f"• ❌ _{ns}_ → ✅ *{say}*" for ns, say in lang["never_say"]])
    always_say = "\n".join([f"• 💬 _{s}_" for s in lang["always_say"]])
    values = "\n".join([f"• ⭐ {v}" for v in SERVICE_STANDARDS["core_values"]])

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": "⭐ Montana Premium House Care — Service Standards"}},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_Chick-fil-A Level Customer Service Guide_"}]},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Our Core Values:*\n{values}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Language Guide — Never Say / Always Say:*\n{never_say}"}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Phrases We Live By:*\n{always_say}"}},
        {"type": "divider"},
        {"type": "context", "elements": [{"type": "mrkdwn", "text": "_\"People don't remember what you did. They remember how you made them feel.\"_"}]},
    ]
    return blocks
