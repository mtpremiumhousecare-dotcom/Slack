"""
Montana Premium House Care — Bot Memory System
===============================================
Persistent learning memory so the bot gets smarter over time.
Carolyn can teach it preferences, corrections, and insights.
Everything is saved to a JSON file so it survives restarts and redeployments.

Memory Categories:
  - preferences: How Carolyn likes things done (tone, timing, format)
  - dont_do: Things the bot should stop doing
  - insights: Business knowledge Carolyn shares
  - customer_notes: Notes about specific customers
  - corrections: When Carolyn corrects the bot's behavior
  - email_style: Learned email writing preferences
  - alert_rules: Custom alert preferences (what to alert on, what to ignore)

Usage in Slack:
  /carolyn learn [category] [what to remember]
  /carolyn forget [memory ID or keyword]
  /carolyn memory [category]  — view what the bot knows
  /carolyn memory all         — view everything
"""

import os
import json
import datetime
import threading
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

# Memory file location — persists across restarts
MEMORY_DIR = os.getenv("BOT_MEMORY_DIR", os.path.dirname(os.path.abspath(__file__)))
MEMORY_FILE = os.path.join(MEMORY_DIR, "carolyn_memory.json")

# Thread lock for safe concurrent access
_lock = threading.Lock()

# Valid memory categories
CATEGORIES = {
    "preferences": "How Carolyn likes things done",
    "dont_do": "Things the bot should NOT do",
    "insights": "Business knowledge and observations",
    "customer_notes": "Notes about specific customers",
    "corrections": "Corrections to bot behavior",
    "email_style": "Email writing preferences",
    "alert_rules": "What to alert on and what to ignore",
}

# ── Core Memory Functions ────────────────────────────────────────────────────

def _load_memory() -> dict:
    """Load memory from disk."""
    try:
        if os.path.exists(MEMORY_FILE):
            with open(MEMORY_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"  ⚠️  Memory load error: {e}")
    # Return default structure
    return {
        "version": 1,
        "created": datetime.datetime.now().isoformat(),
        "last_updated": datetime.datetime.now().isoformat(),
        "memories": [],
        "stats": {"total_learned": 0, "total_forgotten": 0},
    }


def _save_memory(data: dict):
    """Save memory to disk."""
    data["last_updated"] = datetime.datetime.now().isoformat()
    try:
        with open(MEMORY_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        print(f"  ⚠️  Memory save error: {e}")


def learn(category: str, content: str, source: str = "carolyn") -> dict:
    """
    Add a new memory. Returns the memory entry.

    Args:
        category: One of the valid CATEGORIES
        content: What to remember
        source: Who taught this (default: carolyn)
    """
    if category not in CATEGORIES:
        return {"error": f"Unknown category '{category}'. Valid: {', '.join(CATEGORIES.keys())}"}

    with _lock:
        data = _load_memory()
        memory_id = len(data["memories"]) + 1
        entry = {
            "id": memory_id,
            "category": category,
            "content": content,
            "source": source,
            "created": datetime.datetime.now().isoformat(),
            "active": True,
        }
        data["memories"].append(entry)
        data["stats"]["total_learned"] += 1
        _save_memory(data)
        return entry


def forget(identifier: str) -> dict:
    """
    Deactivate a memory by ID number or keyword match.
    Doesn't delete — marks as inactive so we have a history.
    """
    with _lock:
        data = _load_memory()
        forgotten = []

        for mem in data["memories"]:
            if not mem["active"]:
                continue
            # Match by ID
            if identifier.isdigit() and mem["id"] == int(identifier):
                mem["active"] = False
                mem["deactivated"] = datetime.datetime.now().isoformat()
                forgotten.append(mem)
            # Match by keyword in content
            elif not identifier.isdigit() and identifier.lower() in mem["content"].lower():
                mem["active"] = False
                mem["deactivated"] = datetime.datetime.now().isoformat()
                forgotten.append(mem)

        if forgotten:
            data["stats"]["total_forgotten"] += len(forgotten)
            _save_memory(data)

        return {"forgotten": len(forgotten), "items": forgotten}


def recall(category: str = None, active_only: bool = True) -> list:
    """
    Retrieve memories, optionally filtered by category.
    Returns list of memory entries.
    """
    with _lock:
        data = _load_memory()
        memories = data.get("memories", [])

        if active_only:
            memories = [m for m in memories if m.get("active", True)]

        if category and category != "all":
            memories = [m for m in memories if m["category"] == category]

        return memories


def get_context_for_ai(task_type: str = None) -> str:
    """
    Build a context string from memories to inject into AI prompts.
    This is how the bot actually uses what it has learned.

    Args:
        task_type: Optional filter — "email", "alert", "brief", "customer_service"
    """
    memories = recall(active_only=True)
    if not memories:
        return ""

    context_parts = []

    # Always include preferences and dont_do
    prefs = [m for m in memories if m["category"] == "preferences"]
    if prefs:
        context_parts.append("CAROLYN'S PREFERENCES (always follow these):")
        for m in prefs:
            context_parts.append(f"  - {m['content']}")

    donts = [m for m in memories if m["category"] == "dont_do"]
    if donts:
        context_parts.append("\nTHINGS TO NEVER DO:")
        for m in donts:
            context_parts.append(f"  - {m['content']}")

    corrections = [m for m in memories if m["category"] == "corrections"]
    if corrections:
        context_parts.append("\nPAST CORRECTIONS (learn from these):")
        for m in corrections:
            context_parts.append(f"  - {m['content']}")

    # Task-specific memories
    if task_type == "email":
        email_mems = [m for m in memories if m["category"] == "email_style"]
        if email_mems:
            context_parts.append("\nEMAIL STYLE PREFERENCES:")
            for m in email_mems:
                context_parts.append(f"  - {m['content']}")

    if task_type == "alert":
        alert_mems = [m for m in memories if m["category"] == "alert_rules"]
        if alert_mems:
            context_parts.append("\nALERT PREFERENCES:")
            for m in alert_mems:
                context_parts.append(f"  - {m['content']}")

    if task_type == "customer_service":
        cust_mems = [m for m in memories if m["category"] == "customer_notes"]
        if cust_mems:
            context_parts.append("\nCUSTOMER NOTES:")
            for m in cust_mems:
                context_parts.append(f"  - {m['content']}")

    # Always include business insights
    insights = [m for m in memories if m["category"] == "insights"]
    if insights:
        context_parts.append("\nBUSINESS INSIGHTS:")
        for m in insights:
            context_parts.append(f"  - {m['content']}")

    if not context_parts:
        return ""

    return "\n".join(context_parts)


def get_customer_context(customer_name: str) -> str:
    """
    Get all memories related to a specific customer.
    Used when drafting emails or handling complaints for that customer.
    """
    memories = recall(category="customer_notes", active_only=True)
    relevant = [m for m in memories if customer_name.lower() in m["content"].lower()]
    if not relevant:
        return ""
    lines = [f"NOTES ABOUT {customer_name.upper()}:"]
    for m in relevant:
        lines.append(f"  - {m['content']}")
    return "\n".join(lines)


def should_skip_alert(alert_type: str, alert_content: str) -> bool:
    """
    Check if Carolyn has told the bot to stop alerting about something.
    Returns True if the alert should be suppressed.
    """
    alert_rules = recall(category="alert_rules", active_only=True)
    for rule in alert_rules:
        content = rule["content"].lower()
        # Check for suppression rules
        if any(word in content for word in ["stop", "don't", "ignore", "skip", "mute"]):
            if alert_type.lower() in content or any(word in content for word in alert_content.lower().split()):
                return True
    return False


def get_memory_stats() -> dict:
    """Get stats about the memory system."""
    with _lock:
        data = _load_memory()
        active = [m for m in data.get("memories", []) if m.get("active", True)]
        by_category = {}
        for m in active:
            cat = m["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

        return {
            "total_active": len(active),
            "total_learned": data.get("stats", {}).get("total_learned", 0),
            "total_forgotten": data.get("stats", {}).get("total_forgotten", 0),
            "by_category": by_category,
            "last_updated": data.get("last_updated", "Never"),
            "memory_file": MEMORY_FILE,
        }


def format_memories_for_slack(memories: list) -> str:
    """Format a list of memories for Slack display."""
    if not memories:
        return "_No memories found. Teach me with `/carolyn learn [category] [what to remember]`_"

    lines = []
    current_cat = ""
    for m in sorted(memories, key=lambda x: x["category"]):
        if m["category"] != current_cat:
            current_cat = m["category"]
            lines.append(f"\n*{CATEGORIES.get(current_cat, current_cat)}:*")
        status = "" if m.get("active", True) else " ~(forgotten)~"
        lines.append(f"  `#{m['id']}` {m['content']}{status}")

    return "\n".join(lines)
