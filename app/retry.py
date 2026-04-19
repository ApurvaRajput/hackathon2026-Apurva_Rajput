"""
retry.py — Production-Grade Retry Budget System
=================================================

Implements a transparent, observable retry mechanism for all tool calls
inside the ShopWave AI Support Agent.

Design principles
-----------------
- NO silent failures  : every retry and every final failure is logged.
- Budget-based        : each call gets a fixed number of attempts (default 3).
- Exponential backoff : wait = backoff_factor ^ attempt  (1 s, 2 s, 4 s …)
- Transient-only      : only retries on ["timeout", "failure", "malformed"].
- Structured logs     : JSON-compatible dicts, written to stdout + file.

Public API
----------
    safe_call(func, *args, tool_name, retries, backoff_factor) -> dict
    log_retry_event(tool_name, attempt, error, status)        -> None
    log_dead_failure(tool_name, total_attempts)               -> dict
"""

import time
from typing import Any, Callable, Dict

from app.logger import log_retry_event, log_dead_failure


# ── Constants ──────────────────────────────────────────────────────────────────

# Errors that are considered transient (safe to retry).
TRANSIENT_ERRORS: tuple[str, ...] = ("timeout", "failure", "malformed")


# ── Core retry engine ──────────────────────────────────────────────────────────

def safe_call(
    func: Callable,
    *args: Any,
    tool_name: str = "unknown_tool",
    retries: int = 3,
    backoff_factor: int = 2,
) -> Dict[str, Any]:
    """
    Call *func* with *args*, retrying on transient errors until the retry
    budget is exhausted.

    Parameters
    ----------
    func          : Callable — the tool function to invoke.
    *args         : Any      — positional arguments forwarded to *func*.
    tool_name     : str      — human-readable label used in log entries.
    retries       : int      — maximum number of attempts (default 3).
    backoff_factor: int      — base of the exponential wait: 
                                wait = backoff_factor ^ attempt_index
                                attempt 0 → 1 s, attempt 1 → 2 s, attempt 2 → 4 s

    Returns
    -------
    dict
        On success  : the raw dict returned by *func*.
        On exhaustion: {"status": "error", "message": "Retry budget exhausted",
                        "tool": tool_name}

    Examples
    --------
    >>> result = safe_call(get_customer, email, tool_name="get_customer")
    >>> result = safe_call(issue_refund, order_id, amount,
    ...                   tool_name="issue_refund", retries=5)
    """
    last_error: str = "unknown error"

    for attempt in range(retries):
        try:
            result = func(*args)

        except Exception as exc:
            # Treat an unexpected exception as a transient failure.
            last_error = str(exc).lower()
            log_retry_event(
                tool_name=tool_name,
                attempt=attempt + 1,
                error=str(exc),
                status="retrying" if attempt + 1 < retries else "exhausted",
            )
            _backoff(attempt, backoff_factor, tool_name)
            continue

        # ── Happy path ────────────────────────────────────────────────────────
        if result.get("status") == "success":
            if attempt > 0:
                # Only worth noting if we needed at least one retry.
                print(
                    f"  [OK] '{tool_name}' succeeded on attempt {attempt + 1}/{retries}"
                )
            return result

        # ── Transient error ───────────────────────────────────────────────────
        error_msg: str = result.get("message", "")
        is_transient = any(t in error_msg.lower() for t in TRANSIENT_ERRORS)

        if is_transient:
            last_error = error_msg
            remaining = retries - attempt - 1
            log_retry_event(
                tool_name=tool_name,
                attempt=attempt + 1,
                error=error_msg,
                status="retrying" if remaining > 0 else "exhausted",
            )
            if remaining > 0:
                _backoff(attempt, backoff_factor, tool_name)
            continue

        # ── Non-transient error: propagate immediately ─────────────────────────
        # (e.g. "Customer not found" — no point retrying)
        return result

    # ── Budget exhausted ──────────────────────────────────────────────────────
    return log_dead_failure(tool_name=tool_name, total_attempts=retries, last_error=last_error)


# ── Private helpers ────────────────────────────────────────────────────────────

def _backoff(attempt: int, backoff_factor: int, tool_name: str) -> None:
    """Sleep for backoff_factor^attempt seconds and print a notice."""
    wait_seconds: float = backoff_factor ** attempt          # 1 → 2 → 4 → 8 …
    print(
        f"  [wait] '{tool_name}' -- backing off {wait_seconds:.1f}s "
        f"before attempt {attempt + 2} ..."
    )
    time.sleep(wait_seconds)
