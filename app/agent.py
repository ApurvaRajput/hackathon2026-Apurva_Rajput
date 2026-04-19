"""
agent.py — ShopWave AI Support Agent
=====================================

This is the core decision engine. It orchestrates:
  1. Memory retrieval  (get past interactions for this customer)
  2. LLM analysis      (intent / sentiment / fraud / escalation)
  3. Tool execution    (get_customer, get_order, check_refund, …)
  4. Decision making   (approve / deny / escalate / clarify)
  5. Reply generation  (context-aware LLM reply)
  6. Memory saving     (persist this interaction for future tickets)
  7. Email notification (send resolution email to customer)

Return shape (every code-path returns this dict):
-------------------------------------------------
{
  "ticket_id":    str,
  "analysis":     dict,   # full analyze_ticket() output
  "decision":     str,    # e.g. "refund_denied", "escalate", …
  "reason":       str,
  "response":     str,    # final customer-facing reply
  "escalated":    bool,
  "memory_saved": bool,
  "email_sent":   bool,   # True if the resolution email was delivered
}
"""

from typing import Dict, Any

from app.dlq import log_to_dlq           # ← Dead Letter Queue
from app.email_service import send_email
from app.llm import analyze_ticket, generate_email_content, generate_reply
from app.memory import format_history_for_llm, get_history, save_interaction
from app.retry import safe_call          # ← Retry Budget System
from app.tools import (
    get_customer,
    get_order,
    check_refund_eligibility,
    issue_refund,
    send_reply,
    escalate,
    search_knowledge_base,
)

# Safe customer-facing message returned on any DLQ-logged failure.
_DLQ_SAFE_MSG = "Your request is being reviewed. Our team will get back to you shortly."


# ──────────────────────────────────────────────────────────────
# SAFE CALL — imported from app.retry (Retry Budget System)
# ──────────────────────────────────────────────────────────────
# safe_call(func, *args, tool_name=..., retries=3, backoff_factor=2)
#
# • Retries up to `retries` times on transient errors.
# • Applies exponential backoff: wait = backoff_factor ^ attempt.
# • Logs every retry attempt and dead failures to stdout + file.
# • Never retries non-transient errors (e.g. "Customer not found").


# ──────────────────────────────────────────────────────────────
# ESCALATION RULE
# ──────────────────────────────────────────────────────────────

def should_escalate(
    ticket: Dict[str, Any],
    customer_res: Dict[str, Any] | None,
    order_res: Dict[str, Any] | None,
    analysis: Dict[str, Any],
) -> bool:
    """
    Return True when the ticket should be sent to a human specialist.

    Escalation triggers:
    - LLM flagged requires_escalation (angry + threatening language)
    - VIP customer with a high-value order (> 5000)
    """
    if analysis.get("requires_escalation"):
        return True

    if not customer_res or customer_res.get("status") != "success":
        return False

    if not order_res or order_res.get("status") != "success":
        return False

    order = order_res["data"]
    customer = customer_res["data"]

    high_value = order.get("amount", 0) > 5000
    vip = customer.get("tier") == "vip"

    return vip and high_value


# ──────────────────────────────────────────────────────────────
# STRUCTURED RESULT BUILDER
# ──────────────────────────────────────────────────────────────

def _build_result(
    ticket_id: str,
    analysis: Dict[str, Any],
    decision: str,
    reason: str,
    response: str,
    escalated: bool = False,
    memory_saved: bool = False,
    email_sent: bool = False,
) -> Dict[str, Any]:
    """
    Every return path in process_ticket() calls this helper so the API
    always receives the same predictable shape.

    Parameters
    ----------
    ticket_id    : str   — Unique ticket identifier.
    analysis     : dict  — Full output of analyze_ticket().
    decision     : str   — Agent's final decision label.
    reason       : str   — Human-readable justification.
    response     : str   — Customer-facing reply text.
    escalated    : bool  — Whether the ticket was escalated to a human.
    memory_saved : bool  — Whether the interaction was persisted to memory.
    email_sent   : bool  — Whether the resolution email was delivered.

    Returns
    -------
    dict
        Structured result with status: 'success'.
    """
    return {
        "status": "success",
        "ticket_id": ticket_id,
        "analysis": analysis,
        "decision": decision,
        "reason": reason,
        "response": response,
        "escalated": escalated,
        "memory_saved": memory_saved,
        "email_sent": email_sent,
    }


# ──────────────────────────────────────────────────────────────
# MAIN AGENT
# ──────────────────────────────────────────────────────────────

def process_ticket(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """
    Process one support ticket end-to-end and return a structured result.

    Parameters
    ----------
    ticket : dict
        Must contain at least: ticket_id, customer_email, body.

    Returns
    -------
    dict
        {ticket_id, analysis, decision, reason, response, escalated, memory_saved}

    DLQ integration
    ---------------
    Any unhandled exception is caught by the top-level try/except, the ticket
    is written to the Dead Letter Queue, and a safe message is returned to the
    caller.  Individual sub-failures (tool exhaustion, schema errors, etc.) also
    call log_to_dlq() before returning their error results.
    """
    try:
        return _process_ticket_inner(ticket)
    except Exception as exc:
        # ── Case 5: Unknown / unexpected critical error ────────────────────────
        # ALWAYS log before returning so the ticket is never dropped silently.
        ticket_id = ticket.get("ticket_id", "UNKNOWN")
        print(f"\n  [AGENT] 🔴 CRITICAL UNHANDLED EXCEPTION for {ticket_id!r}: {exc}")
        log_to_dlq(
            ticket=ticket,
            reason=f"Unhandled exception: {exc}",
            stage="process_ticket_outer",
        )
        return {
            "status":       "error",
            "ticket_id":    ticket_id,
            "decision":     "critical_error",
            "reason":       str(exc),
            "response":     _DLQ_SAFE_MSG,
            "escalated":    False,
            "memory_saved": False,
            "email_sent":   False,
        }


def _process_ticket_inner(ticket: Dict[str, Any]) -> Dict[str, Any]:
    """Internal implementation — called by process_ticket() inside a safety net."""
    print(f"\n[AGENT] Processing Ticket: {ticket['ticket_id']}")

    ticket_id = ticket["ticket_id"]
    email = ticket["customer_email"]
    text = ticket["body"]

    # ── 1. MEMORY ────────────────────────────────────────────
    customer_history = get_history(email)
    history_summary = format_history_for_llm(customer_history)
    prior_escalations = sum(
        1 for item in customer_history if item.get("escalation_status") == "escalated"
    )

    # ── 2. LLM ANALYSIS ──────────────────────────────────────
    analysis = analyze_ticket(text)

    intent = analysis.get("intent")
    order_id = analysis.get("order_id")
    sentiment = analysis.get("sentiment")
    is_fraud = analysis.get("is_fraud")

    repeated_issue_count = sum(
        1 for item in customer_history if item.get("intent") == intent
    )

    print("[AGENT] Detected intent:", intent)
    print("[AGENT] Order ID:", order_id)
    print("[AGENT] Sentiment:", sentiment)
    print("[AGENT] Fraud flag:", is_fraud)
    print("[AGENT] Prior interactions:", len(customer_history))

    # mutable local state updated after customer / order lookups
    customer_name = "Customer"
    customer_tier = "standard"
    order_status = "unknown"

    # ── INNER HELPERS ─────────────────────────────────────────

    def build_reply_context(decision: str, reason: str, escalation_status: str = "not_escalated") -> Dict[str, Any]:
        """Assemble context dict for the LLM reply generator."""
        return {
            "name": customer_name,
            "intent": intent,
            "decision": decision,
            "reason": reason,
            "sentiment": sentiment,
            "tier": customer_tier,
            "order_status": order_status,
            "escalation_status": escalation_status,
            "recent_history": customer_history[-3:],
            "history_summary": history_summary,
            "prior_escalations": prior_escalations,
            "repeated_issue_count": repeated_issue_count,
        }

    def send_and_remember(
        decision: str,
        reason: str,
        message: str,
        escalation_status: str = "not_escalated",
    ) -> Dict[str, Any]:
        """
        Send the reply, save the interaction to memory, send a resolution
        email to the customer, and return a fully structured result dict.

        Email delivery is fire-and-forget: failures are logged but never
        raise so the main agent flow is never interrupted.
        """
        tool_result = send_reply(ticket_id, message)
        memory_saved = False
        email_sent = False

        if tool_result.get("status") == "success":
            save_interaction(
                email,
                {
                    "ticket_id": ticket_id,
                    "intent": intent or "unknown",
                    "decision": decision,
                    "reason": reason,
                    "reply": message,
                    "sentiment": sentiment or "neutral",
                    "order_id": order_id,
                    "escalation_status": escalation_status,
                },
            )
            memory_saved = True

            # ── EMAIL NOTIFICATION ────────────────────────────────────────
            # Generate a polished email subject+body via the LLM (or heuristic
            # fallback).  Then attempt SMTP delivery.  Any failure is caught,
            # logged, and does NOT propagate — email is best-effort.
            try:
                email_context = {
                    "customer_name": customer_name,
                    "issue_summary": analysis.get("summary", text[:120]),
                    "final_decision": decision,
                    "reply_message": message,
                }
                email_content = generate_email_content(email_context)

                email_result = send_email(
                    to_email=email,
                    subject=email_content["subject"],
                    body=email_content["body"],
                )

                if email_result["status"] == "success":
                    email_sent = True
                    print(f"📧 Email sent to {email}")
                else:
                    # Log the failure but continue — non-critical
                    print(f"[AGENT] Email failed: {email_result['message']}")

            except Exception as exc:
                # Catch-all: malformed email content, unexpected errors, etc.
                print(f"[AGENT] Email notification error (non-fatal): {exc}")

        return _build_result(
            ticket_id=ticket_id,
            analysis=analysis,
            decision=decision,
            reason=reason,
            response=message,
            escalated=(escalation_status == "escalated"),
            memory_saved=memory_saved,
            email_sent=email_sent,
        )

    # ── 3. FRAUD CHECK ────────────────────────────────────────
    if is_fraud:
        fraud_msg = "We could not process your request due to a policy violation."
        return send_and_remember(
            "fraud_blocked",
            "Policy violation detected in the request.",
            fraud_msg,
        )

    # ── 4. CUSTOMER LOOKUP ────────────────────────────────────
    customer_res = safe_call(get_customer, email, tool_name="get_customer")

    if customer_res["status"] != "success":
        # ── Case 1: Tool failure after retry budget exhausted ─────────────────
        if customer_res.get("message") == "Retry budget exhausted":
            log_to_dlq(
                ticket=ticket,
                reason=f"get_customer tool failed after retry budget exhausted: {customer_res.get('message')}",
                stage="customer_lookup",
            )
            send_reply(ticket_id, _DLQ_SAFE_MSG)
            return _build_result(
                ticket_id=ticket_id,
                analysis=analysis,
                decision="customer_lookup_failed",
                reason="get_customer retry budget exhausted.",
                response=_DLQ_SAFE_MSG,
            )
        error_msg = "We could not find your account. Please provide the correct email address."
        send_reply(ticket_id, error_msg)
        return _build_result(
            ticket_id=ticket_id,
            analysis=analysis,
            decision="customer_not_found",
            reason="Customer email not found in system.",
            response=error_msg,
        )

    customer = customer_res["data"]
    customer_name = customer.get("name", "Customer")
    customer_tier = customer.get("tier", "standard")

    # ── 5. ORDER LOOKUP ───────────────────────────────────────
    order_res = None
    order_status = "unknown"

    if order_id:
        order_res = safe_call(get_order, order_id, tool_name="get_order")

        if order_res["status"] != "success":
            # ── Case 1: Tool failure after retry budget exhausted ─────────────
            if order_res.get("message") == "Retry budget exhausted":
                log_to_dlq(
                    ticket=ticket,
                    reason=f"get_order tool failed after retry budget exhausted for order {order_id}",
                    stage="order_lookup",
                )
                send_reply(ticket_id, _DLQ_SAFE_MSG)
                return _build_result(
                    ticket_id=ticket_id,
                    analysis=analysis,
                    decision="order_lookup_failed",
                    reason="get_order retry budget exhausted.",
                    response=_DLQ_SAFE_MSG,
                )
            error_msg = f"Hi {customer_name}, order {order_id} was not found. Please check your order ID."
            send_reply(ticket_id, error_msg)
            return _build_result(
                ticket_id=ticket_id,
                analysis=analysis,
                decision="order_not_found",
                reason=f"Order {order_id} not found.",
                response=error_msg,
            )

        order_status = order_res["data"].get("status", "unknown")

    # ── 6. ESCALATION CHECK ───────────────────────────────────
    if should_escalate(ticket, customer_res, order_res, analysis):
        escalation_result = escalate(
            ticket_id,
            summary=analysis.get("summary", ticket["body"]),
            priority="HIGH",
        )

        if escalation_result["status"] == "success":
            escalation_reason = analysis.get("summary", "Your case needs specialist review.")

            if prior_escalations:
                escalation_reason += " We can see there was a previous escalated interaction on this account."
            elif repeated_issue_count > 1:
                escalation_reason += " We can see this issue has come up before."

            reply = generate_reply(
                build_reply_context("escalate", escalation_reason, escalation_status="escalated")
            )
            return send_and_remember(
                "escalate",
                escalation_reason,
                reply,
                escalation_status="escalated",
            )

        # Escalation tool itself failed — surface as error
        return _build_result(
            ticket_id=ticket_id,
            analysis=analysis,
            decision="escalation_failed",
            reason="Escalation tool returned an error.",
            response="We encountered an issue escalating your case. Our team will contact you shortly.",
        )

    # ── 7. MISSING ORDER ID ───────────────────────────────────
    if not order_id and intent in ["refund", "return"]:
        reply = generate_reply(
            build_reply_context("ask_clarification", "Please share your order ID so I can review your request.")
        )
        return send_and_remember(
            "ask_clarification",
            "Please share your order ID so I can review your request.",
            reply,
        )

    # ── 8. REFUND ─────────────────────────────────────────────
    if intent == "refund" and order_id:
        eligibility = safe_call(check_refund_eligibility, order_id, tool_name="check_refund_eligibility")

        if eligibility["status"] != "success":
            # ── Case 1: Tool failure after retry budget exhausted ─────────────
            log_to_dlq(
                ticket=ticket,
                reason=f"check_refund_eligibility failed for order {order_id}: {eligibility.get('message')}",
                stage="refund_eligibility_check",
            )
            return _build_result(
                ticket_id=ticket_id, analysis=analysis,
                decision="system_error", reason="Eligibility check failed.",
                response=_DLQ_SAFE_MSG,
            )

        reason = eligibility["data"]["reason"]

        if eligibility["data"]["eligible"]:
            refund = safe_call(issue_refund, order_id, order_res["data"]["amount"], tool_name="issue_refund")

            if refund["status"] == "success":
                reply = generate_reply(build_reply_context("refund_approved", refund["data"]["message"]))
                return send_and_remember("refund_approved", refund["data"]["message"], reply)

            # ── Case 1: issue_refund tool failure after retries ───────────────
            log_to_dlq(
                ticket=ticket,
                reason=f"issue_refund tool failed for order {order_id}: {refund.get('message')}",
                stage="refund_processing",
            )
            return _build_result(
                ticket_id=ticket_id, analysis=analysis,
                decision="refund_failed", reason="Refund processing error.",
                response=_DLQ_SAFE_MSG,
            )

        # Refund denied
        reply = generate_reply(build_reply_context("refund_denied", reason))
        denial_reason = reason
        if repeated_issue_count > 1:
            denial_reason += " The customer has contacted support about this issue before."
        return send_and_remember("refund_denied", denial_reason, reply)

    # ── 9. RETURN ─────────────────────────────────────────────
    if intent == "return" and order_id:
        eligibility = safe_call(check_refund_eligibility, order_id, tool_name="check_refund_eligibility")

        if eligibility["status"] != "success":
            # ── Case 1: Tool failure (return eligibility) ─────────────────────
            log_to_dlq(
                ticket=ticket,
                reason=f"check_refund_eligibility failed for return on order {order_id}: {eligibility.get('message')}",
                stage="return_eligibility_check",
            )
            return _build_result(
                ticket_id=ticket_id, analysis=analysis,
                decision="system_error", reason="Eligibility check failed.",
                response=_DLQ_SAFE_MSG,
            )

        reason = eligibility["data"]["reason"]

        if eligibility["data"]["eligible"]:
            reply = generate_reply(build_reply_context("return_approved", reason))
            return send_and_remember("return_approved", reason, reply)

        reply = generate_reply(build_reply_context("return_denied", reason))
        denial_reason = reason
        if repeated_issue_count > 1:
            denial_reason += " The customer has contacted support about this issue before."
        return send_and_remember("return_denied", denial_reason, reply)

    # ── 10. CANCEL ────────────────────────────────────────────
    if intent == "cancel":
        reply = generate_reply(build_reply_context("cancel_approved", "The cancellation has been recorded."))
        return send_and_remember("cancel_approved", "The cancellation has been recorded.", reply)

    # ── 11. TRACKING ──────────────────────────────────────────
    if intent == "tracking":
        tracking_reason = "Your order is in transit. Tracking ID: TRK-12345"
        if repeated_issue_count > 1:
            tracking_reason += " We can see you contacted us recently about this order."
        reply = generate_reply(build_reply_context("tracking_update", tracking_reason))
        return send_and_remember("tracking_update", tracking_reason, reply)

    # ── 12. POLICY ────────────────────────────────────────────
    if intent == "policy":
        kb = safe_call(search_knowledge_base, text, tool_name="search_knowledge_base")

        if kb["status"] == "success":
            reply = generate_reply(build_reply_context("policy_answer", kb["data"]["answer"]))
            return send_and_remember("policy_answer", kb["data"]["answer"], reply)

        # ── Case 1: Knowledge base tool failure after retries ─────────────────
        log_to_dlq(
            ticket=ticket,
            reason=f"search_knowledge_base tool failed: {kb.get('message')}",
            stage="knowledge_base_lookup",
        )
        return _build_result(
            ticket_id=ticket_id, analysis=analysis,
            decision="policy_fetch_failed", reason="Knowledge base unavailable.",
            response=_DLQ_SAFE_MSG,
        )

    # ── 13. UNKNOWN ───────────────────────────────────────────
    reply = generate_reply(
        build_reply_context("ask_clarification", "Please share a bit more detail so I can help with your request.")
    )
    return send_and_remember(
        "ask_clarification",
        "Please share a bit more detail so I can help with your request.",
        reply,
    )
