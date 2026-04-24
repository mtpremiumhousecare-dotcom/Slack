"""
Montana Premium House Care — Email Automation
==============================================
Handles sending customer emails through Mailchimp after Carolyn's approval.
Designed for human-touch communication — no emoji spam, genuine warmth.

Flow:
  1. Bot drafts email using AI (GPT-4.1 or Claude)
  2. Draft posted to #carolyn with a fill-in-the-blank personal note field
  3. Carolyn reviews, adds her personal touch, clicks "Approve & Send"
  4. Bot sends via Mailchimp with Carolyn's note woven in
  5. Bot confirms delivery in Slack

Email Types:
  - win_back: Customer hasn't booked in 60+ days
  - follow_up: Estimate sent but never converted
  - thank_you: Post-job appreciation
  - seasonal: Seasonal cleaning promotion
  - referral_ask: Ask happy customers for referrals
"""

import os
import json
import hashlib
import requests
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────────────────────
MAILCHIMP_API_KEY  = os.getenv("MAILCHIMP_API_KEY", "")
MAILCHIMP_LIST_ID  = os.getenv("MAILCHIMP_LIST_ID", "")
MAILCHIMP_FROM_NAME = os.getenv("BUSINESS_NAME", "Montana Premium House Care")
MAILCHIMP_FROM_EMAIL = os.getenv("BUSINESS_EMAIL", "mtpremiumhousecare@gmail.com")

# Extract Mailchimp data center from API key (e.g., "us21" from "abc123-us21")
_mc_dc = MAILCHIMP_API_KEY.split("-")[-1] if MAILCHIMP_API_KEY and "-" in MAILCHIMP_API_KEY else ""
MC_BASE = f"https://{_mc_dc}.api.mailchimp.com/3.0" if _mc_dc else ""

# ── Pending email queue (in-memory, keyed by customer name) ──────────────────
_pending_emails = {}  # {customer_key: {type, name, email, subject, body, personal_note}}


# ── Human-Touch Email Templates ──────────────────────────────────────────────
# These are the base structures. AI fills in the details.
# Key principle: Write like a real person, not a marketing bot.

EMAIL_GUIDELINES = """
TONE GUIDELINES FOR ALL EMAILS:
- Write like Carolyn is personally typing this email to someone she knows
- Use the customer's first name naturally
- Keep it short — 3-4 paragraphs max
- No exclamation point overload (max 1-2 per email)
- No emojis — they signal automation
- No "Dear Valued Customer" or corporate language
- Sound like a neighbor checking in, not a business sending a blast
- Include one specific detail about their previous service if possible
- End with a warm, natural sign-off (not "Best regards" — more like "Talk soon" or "Hope to hear from you")
- Carolyn will add her own personal note — leave a natural place for it
- The personal note will be inserted after the opening paragraph
"""

TEMPLATES = {
    "win_back": {
        "subject_template": "Hi {first_name} — it's been a while",
        "prompt": """Write a short, warm win-back email from Carolyn at Montana Premium House Care to {name}.
They last had their home cleaned on {last_job_date} ({days_since} days ago).
The email should feel like a genuine check-in, not a sales pitch.
Mention that we'd love to take care of their home again whenever they're ready.
Don't offer a discount unless specifically asked — we lead with quality, not price.
{guidelines}""",
    },
    "follow_up": {
        "subject_template": "Following up on your cleaning estimate",
        "prompt": """Write a short, friendly follow-up email from Carolyn at Montana Premium House Care to {name}.
We sent them an estimate on {created_at} for ${estimate_total} but they haven't booked yet.
The email should be helpful, not pushy. Ask if they have any questions about the estimate.
Mention we're happy to adjust the scope if needed.
{guidelines}""",
    },
    "thank_you": {
        "subject_template": "Thanks, {first_name} — hope everything looks great",
        "prompt": """Write a short thank-you email from Carolyn at Montana Premium House Care to {name}.
We just completed a cleaning job for them. Express genuine appreciation.
Ask if everything looks good and let them know we're always a call away.
Keep it brief — 2-3 paragraphs.
{guidelines}""",
    },
    "seasonal": {
        "subject_template": "Spring cleaning season is here, {first_name}",
        "prompt": """Write a short seasonal email from Carolyn at Montana Premium House Care to {name}.
Let them know it's a great time for a deep clean, window washing, or carpet shampooing.
Keep it conversational and helpful, not salesy.
Mention our full service list naturally: deep cleans, carpet shampooing, window cleaning.
{guidelines}""",
    },
    "referral_ask": {
        "subject_template": "Quick favor, {first_name}?",
        "prompt": """Write a short, genuine referral request email from Carolyn at Montana Premium House Care to {name}.
They're a happy customer. Ask if they know anyone who might need cleaning help.
Make it feel natural — like asking a friend, not running a referral program.
Don't mention rewards or incentives unless specifically asked.
{guidelines}""",
    },
}


def queue_email(email_type: str, customer_data: dict, ai_body: str, subject: str = None):
    """
    Queue a drafted email for Carolyn's review.

    Args:
        email_type: One of the template types (win_back, follow_up, etc.)
        customer_data: Dict with name, email, and any relevant fields
        ai_body: The AI-generated email body
        subject: Custom subject line (or auto-generated from template)
    """
    name = customer_data.get("name", "Customer")
    first_name = name.split()[0] if name else "there"
    email = customer_data.get("email", "")

    if not subject:
        template = TEMPLATES.get(email_type, {})
        subject = template.get("subject_template", "A note from Montana Premium House Care").format(
            first_name=first_name, name=name
        )

    key = f"{name.replace(' ', '_')}_{email_type}"
    _pending_emails[key] = {
        "type": email_type,
        "name": name,
        "first_name": first_name,
        "email": email,
        "subject": subject,
        "body": ai_body,
        "personal_note": "",  # Carolyn fills this in
        "status": "pending_review",
    }
    return key


def add_personal_note(key: str, note: str):
    """Add Carolyn's personal note to a queued email."""
    if key in _pending_emails:
        _pending_emails[key]["personal_note"] = note
        return True
    return False


def get_pending_emails() -> dict:
    """Get all emails pending Carolyn's review."""
    return {k: v for k, v in _pending_emails.items() if v["status"] == "pending_review"}


def _build_final_email(email_data: dict) -> str:
    """
    Combine AI draft with Carolyn's personal note into the final email body.
    The personal note gets woven in after the opening paragraph.
    """
    body = email_data["body"]
    note = email_data.get("personal_note", "").strip()

    if note:
        # Insert personal note after the first paragraph
        paragraphs = body.split("\n\n")
        if len(paragraphs) > 1:
            paragraphs.insert(1, note)
            body = "\n\n".join(paragraphs)
        else:
            body = f"{body}\n\n{note}"

    return body


def send_via_mailchimp(key: str) -> tuple:
    """
    Send an approved email through Mailchimp.

    Returns (success: bool, message: str)
    """
    if key not in _pending_emails:
        return False, "Email not found in queue"

    email_data = _pending_emails[key]
    recipient_email = email_data.get("email", "")

    if not recipient_email:
        return False, f"No email address for {email_data['name']}"

    if not MC_BASE or not MAILCHIMP_API_KEY:
        return False, "Mailchimp not configured. Add MAILCHIMP_API_KEY to .env"

    if not MAILCHIMP_LIST_ID:
        return False, "Mailchimp list ID not configured. Add MAILCHIMP_LIST_ID to .env"

    # Build final email with personal note
    final_body = _build_final_email(email_data)

    # Step 1: Ensure subscriber exists in the list
    subscriber_hash = hashlib.md5(recipient_email.lower().encode()).hexdigest()
    try:
        requests.put(
            f"{MC_BASE}/lists/{MAILCHIMP_LIST_ID}/members/{subscriber_hash}",
            auth=("anystring", MAILCHIMP_API_KEY),
            json={
                "email_address": recipient_email,
                "status_if_new": "subscribed",
                "merge_fields": {
                    "FNAME": email_data.get("first_name", ""),
                },
            },
            timeout=15,
        )
    except Exception as e:
        return False, f"Failed to add subscriber: {e}"

    # Step 2: Create and send a campaign (one-off email)
    try:
        # Create campaign
        campaign_resp = requests.post(
            f"{MC_BASE}/campaigns",
            auth=("anystring", MAILCHIMP_API_KEY),
            json={
                "type": "regular",
                "recipients": {
                    "list_id": MAILCHIMP_LIST_ID,
                    "segment_opts": {
                        "conditions": [{
                            "condition_type": "EmailAddress",
                            "field": "EMAIL",
                            "op": "is",
                            "value": recipient_email,
                        }],
                        "match": "all",
                    },
                },
                "settings": {
                    "subject_line": email_data["subject"],
                    "from_name": MAILCHIMP_FROM_NAME,
                    "reply_to": MAILCHIMP_FROM_EMAIL,
                    "title": f"{email_data['type']}_{email_data['name']}",
                },
            },
            timeout=15,
        )
        campaign_resp.raise_for_status()
        campaign_id = campaign_resp.json().get("id")

        if not campaign_id:
            return False, "Failed to create Mailchimp campaign"

        # Set campaign content (plain text + simple HTML)
        html_body = final_body.replace("\n\n", "</p><p>").replace("\n", "<br>")
        html_content = f"""
        <html>
        <body style="font-family: Georgia, serif; font-size: 16px; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <p>{html_body}</p>
            <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">
            <p style="font-size: 13px; color: #888;">
                Montana Premium House Care<br>
                {os.getenv('BUSINESS_PHONE', '406-599-2699')}<br>
                {os.getenv('BUSINESS_EMAIL', 'mtpremiumhousecare@gmail.com')}
            </p>
        </body>
        </html>
        """

        requests.put(
            f"{MC_BASE}/campaigns/{campaign_id}/content",
            auth=("anystring", MAILCHIMP_API_KEY),
            json={"html": html_content},
            timeout=15,
        )

        # Send the campaign
        send_resp = requests.post(
            f"{MC_BASE}/campaigns/{campaign_id}/actions/send",
            auth=("anystring", MAILCHIMP_API_KEY),
            timeout=15,
        )

        if send_resp.status_code in (200, 204):
            _pending_emails[key]["status"] = "sent"
            return True, f"Email sent to {email_data['name']} ({recipient_email})"
        else:
            return False, f"Mailchimp send failed: {send_resp.text[:200]}"

    except Exception as e:
        return False, f"Mailchimp error: {e}"


def approve_email(key: str, personal_note: str = None) -> tuple:
    """Approve an email: optionally add a personal note, then send via Mailchimp."""
    if key not in _pending_emails:
        return False, "Email not found in queue."
    if personal_note:
        add_personal_note(key, personal_note)
    return send_via_mailchimp(key)

def skip_email(key: str):
    """Mark an email as skipped."""
    if key in _pending_emails:
        _pending_emails[key]["status"] = "skipped"
def get_email_prompt(email_type: str, customer_data: dict) -> str:
    """
    Get the AI prompt for drafting an email of a given type.
    This is called by the AI engine to generate the email body.
    """
    template = TEMPLATES.get(email_type, TEMPLATES["follow_up"])
    prompt = template["prompt"].format(
        name=customer_data.get("name", "Customer"),
        first_name=customer_data.get("name", "Customer").split()[0],
        last_job_date=customer_data.get("last_job_date", "a while ago"),
        days_since=customer_data.get("days_since", "60+"),
        estimate_total=customer_data.get("estimate_total", ""),
        created_at=customer_data.get("created_at", "recently"),
        guidelines=EMAIL_GUIDELINES,
    )
    return prompt


def get_email_stats() -> dict:
    """Get stats on email queue."""
    stats = {"pending": 0, "sent": 0, "skipped": 0}
    for e in _pending_emails.values():
        status = e.get("status", "pending_review")
        if status == "pending_review":
            stats["pending"] += 1
        elif status == "sent":
            stats["sent"] += 1
        elif status == "skipped":
            stats["skipped"] += 1
    return stats
