"""
memory.py — Customer Interaction Memory Layer for ShopWave AI Support Agent
=============================================================================

This module gives the agent a short-term + persistent memory so that every
reply can be personalised with what has happened before.

How it works
------------
1.  An in-memory Python dict (``_memory_cache``) acts as the primary store
    while the agent is running.
2.  After every ticket is resolved, ``save_interaction()`` appends a new record
    and flushes the full store to ``outputs/memory_store.json``.
3.  On the next run the file is read once and cached again — so the agent
    always starts with a full history, not a blank slate.

Memory structure (per customer e-mail)
---------------------------------------
::

    {
      "alice.turner@email.com": [
        {
          "ticket_id":         "TKT-001",
          "intent":            "refund",
          "decision":          "refund_denied",
          "reason":            "Return window expired",
          "reply":             "Hi Alice, ...",
          "sentiment":         "angry",
          "order_id":          "ORD-1001",
          "escalation_status": "not_escalated",
          "timestamp":         "2026-04-19T10:00:00Z"
        }
      ]
    }

Public API
----------
- ``load_memory(force_reload)``   → load from disk (cached on first call)
- ``save_memory(memory)``         → flush to disk
- ``get_history(email, limit)``   → return past records for one customer
- ``save_interaction(email, …)``  → append + persist one interaction
- ``clear_history(email)``        → remove a single customer's records
- ``clear_all_memory()``          → wipe everything
- ``format_history_for_llm(…)``   → render history as a short text block
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Where memory is persisted between agent runs.
MEMORY_FILE: Path = BASE_DIR / "outputs" / "memory_store.json"

# Keep at most this many interactions per customer to prevent unbounded growth.
MAX_HISTORY_PER_CUSTOMER: int = 10

# ---------------------------------------------------------------------------
# Internal cache
#   None  -> not yet loaded (sentinel)
#   {}    -> loaded but empty
# ---------------------------------------------------------------------------
_memory_cache: dict[str, list[dict[str, Any]]] | None = None


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _normalize_email(email: str) -> str:
    """Return a lowercase, stripped email for use as a dict key."""
    return email.strip().lower()


def _ensure_parent_dir(path: Path) -> None:
    """Create parent directories so the JSON file can always be written."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _utc_timestamp() -> str:
    """Return the current UTC time as an ISO-8601 string ending in 'Z'."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _safe_memory_payload(
    payload: Any,
) -> dict[str, list[dict[str, Any]]]:
    """
    Validate and sanitise a raw object from disk or user code.

    Silently drops any key that is not a string or any value that is not a
    list of dicts so that malformed data never crashes the agent.
    """
    if not isinstance(payload, dict):
        return {}

    safe: dict[str, list[dict[str, Any]]] = {}
    for email, records in payload.items():
        if not isinstance(email, str) or not isinstance(records, list):
            continue
        normalized = _normalize_email(email)
        safe[normalized] = [r for r in records if isinstance(r, dict)]

    return safe


# ---------------------------------------------------------------------------
# Public API — load / save
# ---------------------------------------------------------------------------

def load_memory(force_reload: bool = False) -> dict[str, list[dict[str, Any]]]:
    """
    Return the full memory store, loading from disk if necessary.

    Parameters
    ----------
    force_reload:
        When ``True`` the file is always re-read, bypassing the cache.
        Useful for tests that write to the file and want to verify persistence.

    Returns
    -------
    dict
        A deep copy of the in-memory store so callers cannot mutate the cache
        accidentally.
    """
    global _memory_cache

    # Return cached copy if available and a reload has not been requested.
    if _memory_cache is not None and not force_reload:
        return deepcopy(_memory_cache)

    # No file yet -> start with an empty store.
    if not MEMORY_FILE.exists():
        _memory_cache = {}
        return {}

    try:
        raw = json.loads(MEMORY_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Corrupt or unreadable file — reset gracefully.
        _memory_cache = {}
        return {}

    _memory_cache = _safe_memory_payload(raw)
    return deepcopy(_memory_cache)


def save_memory(
    memory: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """
    Persist memory to disk and refresh the in-memory cache.

    Parameters
    ----------
    memory:
        The memory dict to save.  If ``None`` the current cache is reloaded
        and written back (a convenient way to force a flush without data loss).

    Returns
    -------
    dict
        A deep copy of what was written to disk.
    """
    global _memory_cache

    if memory is None:
        memory = load_memory()

    safe = _safe_memory_payload(memory)
    _ensure_parent_dir(MEMORY_FILE)
    MEMORY_FILE.write_text(json.dumps(safe, indent=2, ensure_ascii=False), encoding="utf-8")
    _memory_cache = deepcopy(safe)
    return deepcopy(safe)


# ---------------------------------------------------------------------------
# Public API — get / save individual interactions
# ---------------------------------------------------------------------------

def get_history(
    email: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve past interactions for a customer.

    Parameters
    ----------
    email:
        The customer's e-mail address (case-insensitive).
    limit:
        When set, only the *most recent* ``limit`` records are returned.
        Pass ``None`` to get the full history (up to ``MAX_HISTORY_PER_CUSTOMER``
        items, as enforced during writes).

    Returns
    -------
    list
        A list of interaction dicts, oldest first.  Returns ``[]`` when the
        customer has no prior history.
    """
    memory = load_memory()
    key = _normalize_email(email)
    history = memory.get(key, [])

    if limit is not None:
        history = history[-limit:]

    return deepcopy(history)


def save_interaction(
    email: str,
    interaction: dict[str, Any],
    max_items: int = MAX_HISTORY_PER_CUSTOMER,
) -> list[dict[str, Any]]:
    """
    Append one interaction to a customer's history and persist to disk.

    A UTC timestamp is automatically added if the interaction dict does not
    already contain one.  Older entries are pruned so that each customer's
    history never exceeds ``max_items`` records.

    Parameters
    ----------
    email:
        The customer's e-mail address.
    interaction:
        A dict containing at least: ticket_id, intent, decision, reason,
        reply, sentiment, order_id, escalation_status.
        Any extra keys are stored as-is.
    max_items:
        Maximum number of records to retain per customer.
        Defaults to ``MAX_HISTORY_PER_CUSTOMER`` (10).

    Returns
    -------
    list
        The updated history for the customer (after pruning).
    """
    memory = load_memory()
    key = _normalize_email(email)

    # Deep-copy so we do not mutate the caller's dict.
    record = deepcopy(interaction)

    # Stamp the record with the current UTC time if not already present.
    record.setdefault("timestamp", _utc_timestamp())

    # Append and optionally prune to keep the store lean.
    customer_history = memory.setdefault(key, [])
    customer_history.append(record)

    if max_items > 0:
        memory[key] = customer_history[-max_items:]

    save_memory(memory)
    return get_history(key)


# ---------------------------------------------------------------------------
# Public API — housekeeping
# ---------------------------------------------------------------------------

def clear_history(email: str) -> dict[str, list[dict[str, Any]]]:
    """
    Remove all interaction records for a single customer.

    Parameters
    ----------
    email:
        The customer's e-mail address.

    Returns
    -------
    dict
        The remaining memory store after the deletion.
    """
    memory = load_memory()
    memory.pop(_normalize_email(email), None)
    return save_memory(memory)


def clear_all_memory() -> dict[str, list[dict[str, Any]]]:
    """
    Wipe the entire memory store — both cache and file.

    Useful at the start of a test run to ensure a clean slate.

    Returns
    -------
    dict
        An empty dict (what was written to disk).
    """
    return save_memory({})


# ---------------------------------------------------------------------------
# Public API — LLM helper
# ---------------------------------------------------------------------------

def format_history_for_llm(
    history: list[dict[str, Any]],
    max_items: int = 3,
) -> str:
    """
    Render a customer's recent history as a short, readable text block.

    This string is injected directly into the LLM reply-generation prompt so
    the model can acknowledge past interactions without hallucinating details.

    Parameters
    ----------
    history:
        The list returned by ``get_history()``.
    max_items:
        How many recent interactions to include (default: last 3).

    Returns
    -------
    str
        A newline-separated summary, or ``"No prior support history."`` when
        the history list is empty.

    Example output::

        - 2026-04-19T10:00:00Z | ticket=TKT-001 | intent=refund | decision=refund_denied | sentiment=angry | escalation=not_escalated | reason=Return window expired | reply=Hi Alice, I'm unable to approve...
        - 2026-04-19T12:00:00Z | ticket=TKT-003 | intent=refund | decision=escalate | sentiment=angry | escalation=escalated | reason=Repeated refund issue | reply=Hi Alice, your case has been sent...
    """
    if not history:
        return "No prior support history."

    recent = history[-max_items:]
    lines: list[str] = []

    for item in recent:
        ticket_id = item.get("ticket_id", "unknown")
        intent = item.get("intent", "unknown")
        decision = item.get("decision", "unknown")
        reason = item.get("reason", "")
        timestamp = item.get("timestamp", "unknown_time")
        escalated = item.get("escalation_status", "not_escalated")
        sentiment = item.get("sentiment", "neutral")

        # Truncate the reply preview so the prompt stays concise.
        reply_preview = str(item.get("reply", "")).strip()
        if len(reply_preview) > 80:
            reply_preview = f"{reply_preview[:80]}..."

        line = (
            f"- {timestamp} | ticket={ticket_id} | intent={intent}"
            f" | decision={decision} | sentiment={sentiment}"
            f" | escalation={escalated}"
        )

        if reason:
            line += f" | reason={reason}"

        if reply_preview:
            line += f" | reply={reply_preview}"

        lines.append(line)

    return "\n".join(lines)
