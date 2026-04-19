"""
test_memory.py — Interactive demo + unit assertions for the memory layer
========================================================================

Run this file directly to verify that the memory module works correctly:

    python -m app.test_memory

What this script covers
-----------------------
1. Writing interactions to memory
2. Reading them back and asserting correctness
3. Verifying JSON persistence (force-reload from disk)
4. Formatting history for the LLM prompt
5. Edge cases: empty history, repeated issues, prior escalations
6. Generating a history-aware reply via generate_reply()
7. clear_history() and clear_all_memory() housekeeping
"""

from __future__ import annotations

import sys

from app.llm import generate_reply
from app.memory import (
    clear_all_memory,
    clear_history,
    format_history_for_llm,
    get_history,
    load_memory,
    save_interaction,
    save_memory,
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _ok(label: str) -> None:
    """Print a green-ish PASS message."""
    print(f"  [PASS] {label}")


def _fail(label: str, detail: str = "") -> None:
    """Print a FAIL message and exit so the CI/demo fails loudly."""
    print(f"  [FAIL] {label} — {detail}")
    sys.exit(1)


def _assert(condition: bool, label: str, detail: str = "") -> None:
    if condition:
        _ok(label)
    else:
        _fail(label, detail)


def _section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# Sample data
# ---------------------------------------------------------------------------

EMAIL = "alice.turner@email.com"
EMAIL_NEW = "new.customer@email.com"

# Three realistic interactions that build a story:
#   Ticket 1 → refund denied
#   Ticket 2 → tracking update
#   Ticket 3 → escalated (repeated refund issue, angry)

INTERACTION_1 = {
    "ticket_id": "TKT-001",
    "intent": "refund",
    "decision": "refund_denied",
    "reason": "Return window expired",
    "reply": "Hi Alice, I'm unable to approve the refund because the return window has expired.",
    "sentiment": "neutral",
    "order_id": "ORD-1001",
    "escalation_status": "not_escalated",
    "timestamp": "2026-04-19T10:00:00Z",
}

INTERACTION_2 = {
    "ticket_id": "TKT-002",
    "intent": "tracking",
    "decision": "tracking_update",
    "reason": "Your order is in transit. Tracking ID: TRK-12345",
    "reply": "Hi Alice, your order is in transit. Tracking ID: TRK-12345.",
    "sentiment": "neutral",
    "order_id": "ORD-1002",
    "escalation_status": "not_escalated",
    "timestamp": "2026-04-19T11:00:00Z",
}

INTERACTION_3 = {
    "ticket_id": "TKT-003",
    "intent": "refund",
    "decision": "escalate",
    "reason": "Customer reported repeated refund issue and requested urgent help.",
    "reply": "Hi Alice, I understand this has been frustrating. Your case has been escalated.",
    "sentiment": "angry",
    "order_id": "ORD-1001",
    "escalation_status": "escalated",
    "timestamp": "2026-04-19T12:00:00Z",
}


# ---------------------------------------------------------------------------
# Test sections
# ---------------------------------------------------------------------------

def test_empty_history() -> None:
    """Verify that a customer with no history returns an empty list."""
    _section("TEST 1 — Empty history for unknown customer")

    history = get_history(EMAIL_NEW)
    _assert(history == [], "get_history() returns [] for unknown customer")

    summary = format_history_for_llm(history)
    _assert(
        summary == "No prior support history.",
        "format_history_for_llm() returns sentinel string for empty history",
    )
    print(f"  Formatted: {summary!r}")


def test_save_and_retrieve() -> None:
    """Save three interactions and retrieve them in order."""
    _section("TEST 2 — Save and retrieve interactions")

    save_interaction(EMAIL, INTERACTION_1)
    save_interaction(EMAIL, INTERACTION_2)
    save_interaction(EMAIL, INTERACTION_3)

    history = get_history(EMAIL)
    _assert(len(history) == 3, "get_history() returns 3 records after 3 saves")

    # Verify order: oldest first
    _assert(
        history[0]["ticket_id"] == "TKT-001",
        "First record is TKT-001 (oldest first)",
    )
    _assert(
        history[-1]["ticket_id"] == "TKT-003",
        "Last record is TKT-003 (most recent)",
    )

    print("\n  Retrieved history:")
    for item in history:
        print(f"    [{item['timestamp']}] {item['ticket_id']} | {item['intent']} | {item['decision']}")


def test_persistence() -> None:
    """Force-reload from disk and confirm data survived."""
    _section("TEST 3 — JSON persistence (force reload from disk)")

    reloaded = load_memory(force_reload=True)
    key = "alice.turner@email.com"
    _assert(key in reloaded, f"Customer key '{key}' found after reload")

    on_disk = reloaded[key]
    _assert(len(on_disk) == 3, "Exactly 3 records persisted on disk")
    _assert(
        on_disk[0]["ticket_id"] == "TKT-001",
        "First disk record is TKT-001",
    )
    print("  Memory persisted to disk and reloaded correctly.")


def test_limit_parameter() -> None:
    """get_history(limit=...) should return only the most recent N records."""
    _section("TEST 4 — get_history() with limit parameter")

    last_two = get_history(EMAIL, limit=2)
    _assert(len(last_two) == 2, "get_history(limit=2) returns 2 records")
    _assert(
        last_two[0]["ticket_id"] == "TKT-002",
        "With limit=2, first item is TKT-002 (second-most-recent)",
    )
    _assert(
        last_two[-1]["ticket_id"] == "TKT-003",
        "With limit=2, last item is TKT-003 (most recent)",
    )
    print("  Limit slicing works correctly.")


def test_repeated_issue_detection() -> None:
    """Show how the agent detects repeated intents from history."""
    _section("TEST 5 — Repeated issue detection from history")

    history = get_history(EMAIL)
    repeated_refund_count = sum(1 for h in history if h.get("intent") == "refund")
    prior_escalations = sum(
        1 for h in history if h.get("escalation_status") == "escalated"
    )

    _assert(repeated_refund_count == 2, "Detected 2 refund interactions in history")
    _assert(prior_escalations == 1, "Detected 1 prior escalation in history")

    print(f"  Repeated refund contacts : {repeated_refund_count}")
    print(f"  Prior escalations        : {prior_escalations}")


def test_format_history_for_llm() -> None:
    """Verify the LLM-ready summary text looks correct."""
    _section("TEST 6 — format_history_for_llm()")

    history = get_history(EMAIL)
    summary = format_history_for_llm(history, max_items=3)

    _assert("TKT-001" in summary or "TKT-002" in summary or "TKT-003" in summary,
            "LLM summary contains at least one ticket reference")
    _assert("escalated" in summary, "LLM summary mentions escalation status")
    _assert("refund" in summary, "LLM summary includes intent=refund")

    print("\n  LLM history summary:\n")
    for line in summary.splitlines():
        print(f"    {line}")


def test_history_aware_reply() -> None:
    """
    Show a full history-aware reply from generate_reply().

    This is the key hackathon demo: the reply should acknowledge that
    Alice contacted support before and that her case was escalated.
    """
    _section("TEST 7 — History-aware LLM reply generation")

    history = get_history(EMAIL)
    history_summary = format_history_for_llm(history)
    repeated_refund_count = sum(1 for h in history if h.get("intent") == "refund")
    prior_escalations = sum(
        1 for h in history if h.get("escalation_status") == "escalated"
    )

    context = {
        "name": "Alice Turner",
        "intent": "refund",
        "decision": "escalate",
        "reason": "We are reviewing your refund concern again and a specialist will contact you.",
        "sentiment": "angry",
        "tier": "vip",
        "order_status": "delivered",
        "escalation_status": "escalated",
        "recent_history": history[-3:],
        "history_summary": history_summary,
        "prior_escalations": prior_escalations,
        "repeated_issue_count": repeated_refund_count,
    }

    reply = generate_reply(context)

    _assert(isinstance(reply, str) and len(reply) > 10, "generate_reply() returned a non-empty string")

    print("\n  Context passed to LLM:")
    print(f"    Customer  : {context['name']} ({context['tier'].upper()})")
    print(f"    Intent    : {context['intent']}")
    print(f"    Decision  : {context['decision']}")
    print(f"    Sentiment : {context['sentiment']}")
    print(f"    Repeated refund contacts : {repeated_refund_count}")
    print(f"    Prior escalations        : {prior_escalations}")
    print(f"\n  Generated reply:\n\n    {reply}\n")


def test_clear_history() -> None:
    """clear_history() should wipe one customer without affecting others."""
    _section("TEST 8 — clear_history() for a single customer")

    # Add a record for a second customer so we can verify isolation.
    save_interaction(
        "bob.smith@email.com",
        {
            "ticket_id": "TKT-100",
            "intent": "cancel",
            "decision": "cancel_approved",
            "reason": "Cancellation recorded.",
            "reply": "Hi Bob, your order has been cancelled.",
            "sentiment": "neutral",
            "order_id": "ORD-9001",
            "escalation_status": "not_escalated",
        },
    )

    clear_history(EMAIL)

    alice_history = get_history(EMAIL)
    bob_history = get_history("bob.smith@email.com")

    _assert(alice_history == [], "Alice's history cleared successfully")
    _assert(len(bob_history) == 1, "Bob's history (different customer) was NOT affected")
    print("  Single-customer clear works correctly.")


def test_clear_all_memory() -> None:
    """clear_all_memory() should leave the store completely empty."""
    _section("TEST 9 — clear_all_memory()")

    clear_all_memory()
    all_memory = load_memory(force_reload=True)

    _assert(all_memory == {}, "Memory store is empty after clear_all_memory()")
    print("  Full memory wipe confirmed.")


def test_save_memory_roundtrip() -> None:
    """save_memory() with an explicit dict writes to disk and can be read back."""
    _section("TEST 10 — save_memory() round-trip")

    snapshot = {
        "demo@example.com": [
            {
                "ticket_id": "TKT-999",
                "intent": "policy",
                "decision": "policy_answer",
                "reason": "Return window is 30 days.",
                "reply": "Hi Demo, our return window is 30 days.",
                "sentiment": "neutral",
                "order_id": None,
                "escalation_status": "not_escalated",
                "timestamp": "2026-04-19T13:00:00Z",
            }
        ]
    }

    save_memory(snapshot)
    reloaded = load_memory(force_reload=True)

    _assert(
        "demo@example.com" in reloaded,
        "Saved email key found after force reload",
    )
    _assert(
        reloaded["demo@example.com"][0]["ticket_id"] == "TKT-999",
        "Saved record has correct ticket_id",
    )
    print("  save_memory() round-trip verified.")

    # Clean up after ourselves.
    clear_all_memory()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_memory_demo() -> None:
    """Run all memory-layer tests in sequence."""
    print("\n" + "#" * 60)
    print("  ShopWave AI Agent — Memory Layer Test Suite")
    print("#" * 60)

    # Always start with a blank slate.
    clear_all_memory()

    test_empty_history()
    test_save_and_retrieve()
    test_persistence()
    test_limit_parameter()
    test_repeated_issue_detection()
    test_format_history_for_llm()
    test_history_aware_reply()
    test_clear_history()
    test_clear_all_memory()
    test_save_memory_roundtrip()

    print("\n" + "#" * 60)
    print("  All memory layer tests PASSED.")
    print("#" * 60 + "\n")


if __name__ == "__main__":
    run_memory_demo()
