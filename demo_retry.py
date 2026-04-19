"""
demo_retry.py — Retry Budget System Demo
==========================================

Run this with:   python demo_retry.py

Demonstrates all four scenarios:
  1. Immediate success (no retries)
  2. Success on 2nd attempt
  3. Budget exhausted (all retries fail)
  4. Non-transient error (no retry, propagate immediately)
"""

import random
import sys, os

# Make sure app/ is importable when run from project root.
sys.path.insert(0, os.path.dirname(__file__))

from app.retry import safe_call
from app.logger import FILE_LOGGING_ENABLED
import app.logger as logger_module

# Point logs to a local file for demo
logger_module._LOG_FILE = os.path.join(os.path.dirname(__file__), "outputs", "retry_logs.json")

# ── Mock tool functions ────────────────────────────────────────────────────────

def always_succeeds(order_id: str) -> dict:
    """Never fails."""
    return {"status": "success", "data": {"order_id": order_id, "amount": 99.0}}


_call_count: dict = {"flaky": 0}

def flaky_on_first(order_id: str) -> dict:
    """Fails with timeout on first call, succeeds on 2nd."""
    _call_count["flaky"] += 1
    if _call_count["flaky"] == 1:
        return {"status": "error", "message": "Tool timeout"}
    return {"status": "success", "data": {"order_id": order_id}}


def always_times_out(order_id: str) -> dict:
    """Always returns a timeout error — budget exhausted scenario."""
    return {"status": "error", "message": "Tool timeout"}


def not_found(email: str) -> dict:
    """Non-transient error — should NOT be retried."""
    return {"status": "error", "message": "Customer not found"}


# ── Helpers ────────────────────────────────────────────────────────────────────

SEP = "-" * 60

def section(title: str) -> None:
    print(f"\n{SEP}\n  {title}\n{SEP}")

# ── Demo scenarios ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n=== Retry Budget System — Live Demo ===\n")

    # Scenario 1: Immediate success
    section("Scenario 1: Tool succeeds immediately (no retries needed)")
    result = safe_call(always_succeeds, "ORD-1001", tool_name="get_order")
    print("  Result:", result)

    # Scenario 2: Transient failure then success
    section("Scenario 2: Tool fails once (timeout), succeeds on retry")
    result = safe_call(flaky_on_first, "ORD-1002",
                       tool_name="check_refund_eligibility",
                       retries=3, backoff_factor=1)   # backoff=1 for faster demo
    print("  Result:", result)

    # Scenario 3: Budget exhausted
    section("Scenario 3: All retries fail — budget exhausted")
    result = safe_call(always_times_out, "ORD-1003",
                       tool_name="issue_refund",
                       retries=3, backoff_factor=1)
    print("  Result:", result)

    # Scenario 4: Non-transient error — propagated immediately, no backoff
    section("Scenario 4: Non-transient error — no retry, immediate propagation")
    result = safe_call(not_found, "no-reply@test.com", tool_name="get_customer")
    print("  Result:", result)

    print(f"\n{SEP}")
    print("  Retry log saved to: outputs/retry_logs.json")
    print(f"{SEP}\n")
