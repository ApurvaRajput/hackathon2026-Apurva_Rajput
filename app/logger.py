"""
logger.py — Retry Event Logger
================================

Provides structured, human-readable, and file-persisted logging for the
Retry Budget System.

Each log entry is a JSON-compatible dict:

    {
        "tool":      "check_refund_eligibility",
        "attempt":   2,
        "error":     "timeout",
        "status":    "retrying",          # "retrying" | "exhausted" | "dead"
        "timestamp": "2026-04-19T12:00:00"
    }

Logs are written to:
  - stdout      (always, for demo visibility)
  - outputs/retry_logs.json  (optional file sink, append mode)

Public API
----------
    log_retry_event(tool_name, attempt, error, status) -> None
    log_dead_failure(tool_name, total_attempts, last_error) -> dict
"""

import json
import os
from datetime import datetime
from typing import Dict, Any


# ── Configuration ──────────────────────────────────────────────────────────────

# Path to the persistent retry log file (relative to project root).
_LOG_FILE: str = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "outputs",
    "retry_logs.json",
)

# Set to False to disable file logging (useful during unit tests).
FILE_LOGGING_ENABLED: bool = True


# ── Internal helpers ───────────────────────────────────────────────────────────

def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format (second precision)."""
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _write_to_file(entry: Dict[str, Any]) -> None:
    """Append *entry* as a JSON line to the retry log file."""
    if not FILE_LOGGING_ENABLED:
        return
    try:
        os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError as exc:
        # Never let file-I/O crash the agent.
        print(f"  ⚠️  [LOGGER] Could not write to log file: {exc}")


def _status_icon(status: str) -> str:
    """Return a text icon that matches the log status for stdout."""
    return {
        "retrying":  "[~]",
        "exhausted": "[x]",
        "dead":      "[DEAD]",
        "success":   "[ok]",
    }.get(status, "[i]")


# ── Public API ─────────────────────────────────────────────────────────────────

def log_retry_event(
    tool_name: str,
    attempt: int,
    error: str,
    status: str = "retrying",
) -> None:
    """
    Log a single retry attempt.

    Parameters
    ----------
    tool_name : str  — Name of the tool being called (e.g. "get_customer").
    attempt   : int  — 1-based attempt number that just failed.
    error     : str  — The error message or exception text.
    status    : str  — One of "retrying" | "exhausted".
    """
    entry: Dict[str, Any] = {
        "tool":      tool_name,
        "attempt":   attempt,
        "error":     error,
        "status":    status,
        "timestamp": _now_iso(),
    }

    icon = _status_icon(status)
    print(
        f"  {icon} [RETRY LOG] tool={tool_name!r}  "
        f"attempt={attempt}  status={status.upper()}  "
        f"error={error!r}"
    )

    _write_to_file(entry)


def log_dead_failure(
    tool_name: str,
    total_attempts: int,
    last_error: str = "unknown",
) -> Dict[str, Any]:
    """
    Log a dead (budget-exhausted) failure and return the structured error dict
    that will propagate back to the agent.

    Parameters
    ----------
    tool_name      : str — Name of the failing tool.
    total_attempts : int — Number of attempts that were made.
    last_error     : str — Last error message observed.

    Returns
    -------
    dict
        {"status": "error", "message": "Retry budget exhausted", "tool": tool_name}
    """
    entry: Dict[str, Any] = {
        "tool":           tool_name,
        "total_attempts": total_attempts,
        "last_error":     last_error,
        "status":         "dead",
        "timestamp":      _now_iso(),
    }

    print(
        f"\n  [DEAD FAILURE] Retry budget EXHAUSTED for tool={tool_name!r}"
        f"\n     Total attempts : {total_attempts}"
        f"\n     Last error     : {last_error!r}"
        f"\n     Timestamp      : {entry['timestamp']}\n"
    )

    _write_to_file(entry)

    # Structured error propagated back to the agent caller.
    return {
        "status":  "error",
        "message": "Retry budget exhausted",
        "tool":    tool_name,
    }
