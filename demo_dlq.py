"""
demo_dlq.py -- Dead Letter Queue Demo Script
=============================================

Demonstrates all 5 DLQ integration points:

  Case 1 : Tool failure after retry budget exhausted
  Case 2 : Schema validation failure          (simulated via bad ticket dict)
  Case 3 : Unhandled exception in process_ticket()
  Case 4 : LLM confidence too low             (simulated)
  Case 5 : Unknown critical error             (simulated via ValueError)

Run with:
    python demo_dlq.py

Expected outputs:
  - Console logs showing each failure being caught and written to DLQ
  - Dead Letter Queue Summary printed at the end
  - reprocess_dlq() run to demonstrate retry-on-failure behavior
  - outputs/dead_letter_queue.jsonl file populated with entries
"""

import json
import os
import sys

# Fix Windows console encoding for Unicode output
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# -- Patch DLQ to use a test-only file so we don't pollute the real queue ------
import app.dlq as dlq_module

_DEMO_DLQ = os.path.join("outputs", "demo_dead_letter_queue.jsonl")
os.makedirs("outputs", exist_ok=True)

# Override the DLQ file path for the demo
dlq_module._DLQ_FILE      = _DEMO_DLQ
dlq_module._DLQ_TEMP_FILE = _DEMO_DLQ + ".tmp"

# Clear demo file before starting
if os.path.exists(_DEMO_DLQ):
    os.remove(_DEMO_DLQ)

from app.dlq import log_to_dlq, get_dlq_entries, count_failed_tickets, print_dlq_summary, reprocess_dlq


# ------------------------------------------------------------------
# HELPER: build a minimal valid ticket
# ------------------------------------------------------------------

def make_ticket(ticket_id: str, intent_hint: str = "refund") -> dict:
    return {
        "ticket_id":      ticket_id,
        "customer_email": "demo@shopwave.com",
        "subject":        f"Demo ticket {ticket_id}",
        "body":           f"I need help with my {intent_hint} request.",
        "source":         "email",
        "created_at":     "2026-04-19T12:00:00",
    }


# ------------------------------------------------------------------
# CASE 1 -- Tool failure after retry budget exhausted
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  CASE 1 : Tool failure after retry budget exhausted")
print("=" * 60)

ticket_1 = make_ticket("TKT-001")
log_to_dlq(
    ticket=ticket_1,
    reason="issue_refund tool failed after 3 retries (timeout)",
    stage="refund_processing",
)


# ------------------------------------------------------------------
# CASE 2 -- Schema validation failure
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  CASE 2 : Schema validation failure")
print("=" * 60)

ticket_2 = make_ticket("TKT-002")
log_to_dlq(
    ticket=ticket_2,
    reason="LLM response failed JSON schema validation: missing 'intent' field",
    stage="schema_validation",
)


# ------------------------------------------------------------------
# CASE 3 -- Unhandled exception in process_ticket()
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  CASE 3 : Unhandled exception in process_ticket()")
print("=" * 60)

ticket_3 = make_ticket("TKT-003")

try:
    raise RuntimeError("Unexpected NoneType error in memory layer")
except Exception as exc:
    log_to_dlq(
        ticket=ticket_3,
        reason=f"Unhandled exception: {exc}",
        stage="process_ticket_outer",
    )
    print("  Safe message returned to customer:")
    print("  \"Your request is being reviewed. Our team will get back to you shortly.\"")


# ------------------------------------------------------------------
# CASE 4 -- LLM confidence too low
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  CASE 4 : LLM confidence score too low")
print("=" * 60)

ticket_4 = make_ticket("TKT-004", "complaint")
log_to_dlq(
    ticket=ticket_4,
    reason="LLM confidence score 0.31 below threshold 0.70 -- cannot make safe decision",
    stage="llm_analysis",
)


# ------------------------------------------------------------------
# CASE 5 -- Unknown critical error
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  CASE 5 : Unknown / critical system error")
print("=" * 60)

ticket_5 = make_ticket("TKT-005", "tracking")
log_to_dlq(
    ticket=ticket_5,
    reason="Critical: database connection pool exhausted -- cannot persist memory",
    stage="memory_save",
)


# ------------------------------------------------------------------
# SUMMARY -- print DLQ state
# ------------------------------------------------------------------

print_dlq_summary()

# Show the raw JSONL file contents
print(f"Raw DLQ file ({_DEMO_DLQ}):")
print("-" * 60)
entries = get_dlq_entries()
for entry in entries:
    # Pretty print each entry for readability
    printable = {k: v for k, v in entry.items() if k != "ticket_data"}
    printable["ticket_data"] = "{...}"
    print(json.dumps(printable, indent=2))
print("-" * 60)


# ------------------------------------------------------------------
# REPROCESS -- demonstrate retry-on-failure
# ------------------------------------------------------------------

print("\n" + "=" * 60)
print("  REPROCESS : Running reprocess_dlq() with a mock processor")
print("=" * 60)

# We'll use a mock process_fn that succeeds for TKT-001 and TKT-003,
# but still fails for TKT-002, TKT-004, TKT-005
_attempt_counts: dict = {}

def mock_process(ticket: dict) -> dict:
    tid = ticket.get("ticket_id", "UNKNOWN")
    _attempt_counts[tid] = _attempt_counts.get(tid, 0) + 1

    # Simulate TKT-001 and TKT-003 recovering on reprocess
    if tid in ("TKT-001", "TKT-003"):
        print(f"    [mock] {tid} -> RECOVERED")
        return {"status": "success", "ticket_id": tid}

    # Others still fail
    print(f"    [mock] {tid} -> STILL FAILING")
    return {"status": "error", "ticket_id": tid, "message": "Dependency unavailable"}


summary = reprocess_dlq(process_fn=mock_process)

print("\nReprocess Summary:")
print(json.dumps(summary, indent=2))

# Final state
print_dlq_summary()
