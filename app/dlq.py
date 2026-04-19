"""
dlq.py — Dead Letter Queue (DLQ) System
=========================================

WHY DLQ IS IMPORTANT
---------------------
In any distributed, event-driven or agentic system, individual processing steps
can fail at any point:
  - Network timeouts calling external APIs (Shiprocket, Twilio, Payment Gateway)
  - LLM returning malformed / low-confidence JSON
  - Downstream services returning 5xx errors
  - Unexpected exceptions inside business logic

Without a DLQ, these failures silently DROP the customer ticket — it is gone
forever, causing data loss, SLA breaches, and unhappy customers.

HOW DLQ IMPROVES RELIABILITY
------------------------------
A Dead Letter Queue captures every failed ticket BEFORE returning to the caller.
Failed tickets are persisted to disk (dead_letter_queue.jsonl) with full context:
  - What failed  (reason)
  - Where it failed  (stage)
  - When it failed  (timestamp)
  - The full original ticket payload (for reprocessing)

This means NO ticket is ever lost — it can be retried manually or automatically
via reprocess_dlq().

WHERE DLQ IS USED IN REAL SYSTEMS
-----------------------------------
  • Apache Kafka       : consumer groups write unprocessable messages to a DLQ topic
  • AWS SQS            : configures a redrive policy after N receive attempts
  • Azure Service Bus  : moves dead messages to a sub-queue automatically
  • RabbitMQ           : alternate exchange for rejected / expired messages
  • Google Pub/Sub     : dead letter topics with max delivery attempts
  • Celery (Python)    : task.apply_async(link_error=handle_failure)

This implementation mirrors the same pattern with a simple, dependency-free
file-based approach suitable for demo/hackathon use and easy migration to any
real message broker in production.

Public API
----------
    log_to_dlq(ticket, reason, stage)        -> None
    reprocess_dlq(process_fn)                -> dict   # summary
    get_dlq_entries()                        -> list[dict]
    count_failed_tickets()                   -> int
    print_dlq_summary()                      -> None
"""

import json
import os
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

# ── Configuration ──────────────────────────────────────────────────────────────

# DLQ lives in the project outputs/ directory, alongside retry_logs.json
_DLQ_FILE: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "outputs",
    "dead_letter_queue.jsonl",
)

# A temporary file used during reprocessing (swap-write pattern keeps it safe)
_DLQ_TEMP_FILE: str = _DLQ_FILE + ".tmp"

# Set to False to suppress file I/O (useful in unit tests)
DLQ_FILE_ENABLED: bool = True


# ── Internal helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format (second precision)."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _ensure_outputs_dir() -> None:
    """Create the outputs/ directory if it does not yet exist."""
    os.makedirs(os.path.dirname(_DLQ_FILE), exist_ok=True)


def _read_raw_lines() -> List[str]:
    """
    Return all non-empty lines from the DLQ file.
    Returns an empty list when the file does not exist.
    """
    if not os.path.exists(_DLQ_FILE):
        return []
    try:
        with open(_DLQ_FILE, "r", encoding="utf-8") as fh:
            return [line.strip() for line in fh if line.strip()]
    except OSError as exc:
        print(f"  ⚠️  [DLQ] Cannot read DLQ file: {exc}")
        return []


# ── Public API ─────────────────────────────────────────────────────────────────

def log_to_dlq(ticket: Dict[str, Any], reason: str, stage: str) -> None:
    """
    Append a failed ticket to the Dead Letter Queue file.

    NEVER raises — any file I/O error is caught and printed so that the
    calling code can still return a safe response to the user.

    Parameters
    ----------
    ticket : dict
        The full original ticket payload (must contain at least ``ticket_id``).
    reason : str
        Human-readable description of why the ticket failed.
        Example: "Refund tool failure after 3 retries"
    stage : str
        The processing stage where the failure occurred.
        Example: "refund_processing", "schema_validation", "llm_analysis"
    """
    ticket_id = ticket.get("ticket_id", "UNKNOWN")

    entry: Dict[str, Any] = {
        "ticket_id":   ticket_id,
        "reason":      reason,
        "stage":       stage,
        "timestamp":   _now_iso(),
        "ticket_data": ticket,
    }

    # ── stdout visibility ──────────────────────────────────────────────────────
    print(
        f"\n  🚨 [DLQ] Ticket {ticket_id!r} logged to Dead Letter Queue"
        f"\n     Stage  : {stage}"
        f"\n     Reason : {reason}"
        f"\n     Time   : {entry['timestamp']}\n"
    )

    # ── File persistence ───────────────────────────────────────────────────────
    if not DLQ_FILE_ENABLED:
        return

    try:
        _ensure_outputs_dir()
        with open(_DLQ_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
        print(f"  ✅ [DLQ] Entry persisted → {_DLQ_FILE}")
    except OSError as exc:
        # Never let logging crash the main agent flow.
        print(f"  ⚠️  [DLQ] CRITICAL — Could not write to DLQ file: {exc}")


def get_dlq_entries() -> List[Dict[str, Any]]:
    """
    Return all entries currently stored in the Dead Letter Queue.

    Returns
    -------
    list[dict]
        Parsed DLQ entries, oldest first.  Returns [] if the queue is empty.
    """
    entries: List[Dict[str, Any]] = []
    for line in _read_raw_lines():
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"  ⚠️  [DLQ] Skipping malformed line: {exc}")
    return entries


def count_failed_tickets() -> int:
    """Return the number of tickets currently sitting in the DLQ."""
    return len(_read_raw_lines())


def print_dlq_summary() -> None:
    """
    Print a human-readable summary of the Dead Letter Queue to stdout.

    Example output
    --------------
    ┌─────────────────────────────────────────┐
    │         DEAD LETTER QUEUE SUMMARY       │
    ├─────────────────────────────────────────┤
    │  Total failed tickets : 3               │
    │  TKT-001  refund_processing  2026-04-19 │
    │  TKT-002  schema_validation  2026-04-19 │
    │  TKT-003  llm_analysis       2026-04-19 │
    └─────────────────────────────────────────┘
    """
    entries = get_dlq_entries()
    count   = len(entries)

    print("\n" + "═" * 55)
    print("        💀  DEAD LETTER QUEUE SUMMARY")
    print("═" * 55)
    print(f"  Total failed tickets : {count}")

    if count == 0:
        print("  Queue is empty — all tickets processed successfully ✅")
    else:
        print(f"  {'Ticket ID':<15}  {'Stage':<25}  {'Timestamp'}")
        print("  " + "-" * 52)
        for entry in entries:
            print(
                f"  {entry.get('ticket_id', 'UNKNOWN'):<15}  "
                f"{entry.get('stage', 'unknown'):<25}  "
                f"{entry.get('timestamp', 'N/A')}"
            )

    print("═" * 55 + "\n")


def reprocess_dlq(
    process_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Retry all tickets currently in the Dead Letter Queue.

    Behavior
    --------
    1. Read all failed tickets from the DLQ file.
    2. For each ticket, call ``process_fn(ticket_data)`` (defaults to the
       agent's ``process_ticket`` if not provided).
    3. If the retry succeeds  → ticket is removed from the DLQ.
    4. If the retry fails again → ticket stays in the DLQ with an updated
       ``retry_count`` counter.
    5. Writes a new DLQ file containing only the still-failing tickets
       (atomic swap pattern: write to .tmp, then rename).

    Parameters
    ----------
    process_fn : callable, optional
        Function with signature ``(ticket: dict) -> dict``.
        Must return a dict with at least ``{"status": "success" | "error"}``.
        Defaults to ``app.agent.process_ticket`` when not supplied.

    Returns
    -------
    dict
        {
            "total":      int,   # tickets found in DLQ
            "succeeded":  int,   # successfully reprocessed
            "still_failed": int, # still failing (kept in DLQ)
            "details":    list   # per-ticket outcome records
        }

    Why this pattern?
    ------------------
    This mirrors the "requeue-on-success, leave-on-failure" pattern used by
    AWS SQS redrive policies and Kafka consumer retries.  It guarantees that
    a partial reprocessing run never loses tickets — even if the process is
    interrupted halfway through.
    """
    # Lazy import to avoid circular dependency (agent imports dlq, dlq imports agent)
    if process_fn is None:
        from app.agent import process_ticket  # noqa: PLC0415
        process_fn = process_ticket

    entries = get_dlq_entries()
    total = len(entries)

    print("\n" + "═" * 55)
    print("  🔄  REPROCESSING DEAD LETTER QUEUE")
    print("═" * 55)
    print(f"  Found {total} failed ticket(s) to retry\n")

    if total == 0:
        print("  ✅ Nothing to reprocess — DLQ is empty.\n")
        return {"total": 0, "succeeded": 0, "still_failed": 0, "details": []}

    succeeded  = 0
    still_bad: List[Dict[str, Any]] = []     # entries that still fail
    details:   List[Dict[str, Any]] = []

    for entry in entries:
        ticket_id   = entry.get("ticket_id", "UNKNOWN")
        ticket_data = entry.get("ticket_data", {})
        retry_count = entry.get("retry_count", 0) + 1

        print(f"  [→] Retrying ticket {ticket_id!r}  (attempt #{retry_count}) …")

        try:
            result = process_fn(ticket_data)
            outcome = result.get("status", "error")
        except Exception as exc:
            outcome = "error"
            print(f"  [✗] Exception while reprocessing {ticket_id!r}: {exc}")
            result  = {"status": "error", "message": str(exc)}

        if outcome == "success":
            succeeded += 1
            print(f"  [✓] {ticket_id!r} reprocessed successfully — removed from DLQ")
            details.append({"ticket_id": ticket_id, "outcome": "success"})
        else:
            # Keep in DLQ with incremented retry_count
            updated_entry = {**entry, "retry_count": retry_count}
            still_bad.append(updated_entry)
            print(f"  [✗] {ticket_id!r} still failing — kept in DLQ (retry #{retry_count})")
            details.append({
                "ticket_id":   ticket_id,
                "outcome":     "failed",
                "retry_count": retry_count,
            })

    # ── Atomic DLQ file rewrite ────────────────────────────────────────────────
    # Write remaining failures to a temp file, then replace the original.
    # This ensures the DLQ is never left in a corrupted state.
    if DLQ_FILE_ENABLED:
        try:
            _ensure_outputs_dir()
            with open(_DLQ_TEMP_FILE, "w", encoding="utf-8") as fh:
                for bad_entry in still_bad:
                    fh.write(json.dumps(bad_entry) + "\n")
            # Atomic rename (works on Windows too)
            if os.path.exists(_DLQ_FILE):
                os.remove(_DLQ_FILE)
            if still_bad:
                os.rename(_DLQ_TEMP_FILE, _DLQ_FILE)
            elif os.path.exists(_DLQ_TEMP_FILE):
                os.remove(_DLQ_TEMP_FILE)
            print(f"\n  📝 DLQ file updated → {_DLQ_FILE}")
        except OSError as exc:
            print(f"  ⚠️  [DLQ] Could not update DLQ file after reprocessing: {exc}")

    still_failed = len(still_bad)
    summary = {
        "total":        total,
        "succeeded":    succeeded,
        "still_failed": still_failed,
        "details":      details,
    }

    print("\n" + "─" * 55)
    print(f"  ✅ Reprocessed  : {succeeded}/{total}")
    print(f"  ❌ Still failed : {still_failed}/{total}")
    print("═" * 55 + "\n")

    return summary
