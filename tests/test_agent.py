"""
test_agent.py — Tests for the ShopWave AI Support Agent
========================================================

Purpose:
    Verifies the core process_ticket() pipeline including LLM analysis,
    tool execution, reply generation, memory persistence, and the email
    notification integration added in the Email Notification Module.

Role in System:
    Runs as part of the test suite (``pytest tests/``).  Every test fully
    monkeypatches external dependencies so the suite executes offline,
    deterministically, and without real SMTP or OpenAI calls.
"""

import pytest

from app.agent import process_ticket


# ──────────────────────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def sample_ticket(**overrides):
    """Return a minimal ticket dict, optionally overriding any key."""
    ticket = {
        "ticket_id": "T-100",
        "customer_email": "alice@example.com",
        "body": "I want a refund for ORD-1001",
    }
    ticket.update(overrides)
    return ticket


def customer_response(name="Alice"):
    """Simulated successful get_customer tool response."""
    return {
        "status": "success",
        "data": {
            "customer_id": "C001",
            "name": name,
            "email": "alice@example.com",
            "tier": "regular",
        },
    }


def order_response(order_id="ORD-1001", amount=129.99):
    """Simulated successful get_order tool response."""
    return {
        "status": "success",
        "data": {
            "order_id": order_id,
            "amount": amount,
            "product_id": "P001",
            "customer_id": "C001",
        },
    }


def _stub_email_content(context):
    """Stub for generate_email_content — returns a fixed subject + body."""
    return {
        "subject": "Your Support Ticket Has Been Resolved",
        "body": f"Dear {context.get('customer_name', 'Customer')}, your issue has been resolved.",
    }


def _stub_send_email_success(to_email, subject, body):
    """Stub for send_email — always succeeds."""
    return {"status": "success", "message": f"Email delivered to {to_email}"}


def _stub_send_email_failure(to_email, subject, body):
    """Stub for send_email — always fails (SMTP error)."""
    return {"status": "error", "message": "SMTP connection refused"}


def _apply_common_email_mocks(monkeypatch):
    """Patch send_email + generate_email_content with success stubs.

    Call this in every test that exercises send_and_remember() so the email
    integration code path doesn't attempt a real SMTP connection.
    """
    monkeypatch.setattr("app.agent.generate_email_content", _stub_email_content)
    monkeypatch.setattr("app.agent.send_email", _stub_send_email_success)


# ──────────────────────────────────────────────────────────────────────────────
# EXISTING TESTS (updated to include email mocks)
# ──────────────────────────────────────────────────────────────────────────────

def test_process_ticket_blocks_fraudulent_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fraud-flagged tickets are blocked immediately and email is sent."""
    sent = {}
    saved = {}

    monkeypatch.setattr("app.agent.get_history", lambda email: [])
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "No prior support history.")
    monkeypatch.setattr(
        "app.agent.save_interaction",
        lambda email, interaction: saved.update({"email": email, "interaction": interaction}) or [interaction],
    )
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": "ORD-1001",
            "sentiment": "angry",
            "urgency": "high",
            "is_fraud": True,
            "requires_escalation": False,
            "summary": "Suspicious refund demand.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: pytest.fail("get_customer should not be called"))
    monkeypatch.setattr("app.agent.send_reply", lambda ticket_id, message: sent.update({"ticket_id": ticket_id, "message": message}) or {"status": "success"})

    # Email mocks
    _apply_common_email_mocks(monkeypatch)

    result = process_ticket(sample_ticket())

    assert result["status"] == "success"
    assert sent["ticket_id"] == "T-100"
    assert sent["message"] == "We could not process your request due to a policy violation."
    assert saved["email"] == "alice@example.com"
    assert saved["interaction"]["decision"] == "fraud_blocked"
    # Email should have been triggered after successful reply
    assert result["email_sent"] is True


def test_process_ticket_uses_generated_reply_for_refund_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    """Refund denial uses the LLM-generated reply and sends an email."""
    sent = {}
    saved = {}
    generated_context = {}
    prior_history = [
        {
            "ticket_id": "OLD-1",
            "intent": "refund",
            "decision": "refund_denied",
            "reason": "Return window expired",
            "reply": "Earlier reply",
            "timestamp": "2026-04-18T10:00:00Z",
            "escalation_status": "not_escalated",
        }
    ]

    def history_append(lst, item):
        lst.append(item)
        return lst

    monkeypatch.setattr("app.agent.get_history", lambda email: prior_history)
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "Previous refund request found.")
    monkeypatch.setattr(
        "app.agent.save_interaction",
        lambda email, interaction: saved.update({"email": email, "interaction": interaction}),
    )
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": "ORD-1001",
            "sentiment": "neutral",
            "urgency": "medium",
            "is_fraud": False,
            "requires_escalation": False,
            "summary": "Refund request for ORD-1001.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr("app.agent.get_order", lambda order_id: order_response(order_id=order_id))
    monkeypatch.setattr(
        "app.agent.check_refund_eligibility",
        lambda order_id: {
            "status": "success",
            "data": {
                "eligible": False,
                "reason": "Return window expired",
            },
        },
    )
    monkeypatch.setattr(
        "app.agent.generate_reply",
        lambda context: generated_context.update(context) or "Custom refund denial reply",
    )
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: sent.update({"ticket_id": ticket_id, "message": message}) or {"status": "success"},
    )

    # Email mocks
    _apply_common_email_mocks(monkeypatch)

    result = process_ticket(sample_ticket())

    assert result["status"] == "success"
    assert generated_context == {
        "name": "Alice",
        "intent": "refund",
        "decision": "refund_denied",
        "reason": "Return window expired",
        "sentiment": "neutral",
        "tier": "regular",
        "order_status": "unknown",
        "escalation_status": "not_escalated",
        "recent_history": prior_history[-3:],
        "history_summary": "Previous refund request found.",
        "prior_escalations": 0,
        "repeated_issue_count": 1,
    }
    assert sent["message"] == "Custom refund denial reply"
    assert saved["interaction"]["decision"] == "refund_denied"
    assert result["email_sent"] is True


def test_process_ticket_escalates_when_analysis_requires_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """Escalation sends the ticket to a specialist and triggers email."""
    escalated = {}
    sent = {}
    saved = {}
    generated_context = {}
    prior_history = [
        {
            "ticket_id": "OLD-2",
            "intent": "refund",
            "decision": "escalate",
            "reason": "Earlier specialist review",
            "reply": "Earlier escalation reply",
            "timestamp": "2026-04-18T10:00:00Z",
            "escalation_status": "escalated",
        }
    ]

    def history_append(lst, item):
        lst.append(item)
        return lst

    monkeypatch.setattr("app.agent.get_history", lambda email: prior_history)
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "Prior escalation found.")
    monkeypatch.setattr(
        "app.agent.save_interaction",
        lambda email, interaction: saved.update({"email": email, "interaction": interaction}),
    )
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": "ORD-1001",
            "sentiment": "angry",
            "urgency": "high",
            "is_fraud": False,
            "requires_escalation": True,
            "summary": "Customer threatened a dispute over refund handling.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr("app.agent.get_order", lambda order_id: order_response(order_id=order_id))
    monkeypatch.setattr(
        "app.agent.escalate",
        lambda ticket_id, summary, priority: escalated.update(
            {"ticket_id": ticket_id, "summary": summary, "priority": priority}
        )
        or {"status": "success"},
    )
    monkeypatch.setattr(
        "app.agent.generate_reply",
        lambda context: generated_context.update(context) or "A specialist will review your case.",
    )
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: sent.update({"ticket_id": ticket_id, "message": message}) or {"status": "success"},
    )

    # Email mocks
    _apply_common_email_mocks(monkeypatch)

    result = process_ticket(sample_ticket())

    assert result["status"] == "success"
    assert escalated == {
        "ticket_id": "T-100",
        "summary": "Customer threatened a dispute over refund handling.",
        "priority": "HIGH",
    }
    assert generated_context == {
        "name": "Alice",
        "intent": "refund",
        "decision": "escalate",
        "reason": "Customer threatened a dispute over refund handling. We can see there was a previous escalated interaction on this account.",
        "sentiment": "angry",
        "tier": "regular",
        "order_status": "unknown",
        "escalation_status": "escalated",
        "recent_history": prior_history[-3:],
        "history_summary": "Prior escalation found.",
        "prior_escalations": 1,
        "repeated_issue_count": 1,
    }
    assert sent == {
        "ticket_id": "T-100",
        "message": "A specialist will review your case.",
    }
    assert saved["interaction"]["escalation_status"] == "escalated"
    assert result["email_sent"] is True


def test_process_ticket_requests_order_id_with_generated_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    """Missing order ID triggers an ask_clarification reply + email."""
    sent = {}
    saved = {}
    generated_context = {}
    prior_history = [
        {
            "ticket_id": "OLD-3",
            "intent": "tracking",
            "decision": "tracking_update",
            "reason": "Previous tracking request",
            "reply": "Earlier reply",
            "timestamp": "2026-04-18T10:00:00Z",
            "escalation_status": "not_escalated",
        }
    ]

    def history_append(lst, item):
        lst.append(item)
        return lst

    monkeypatch.setattr("app.agent.get_history", lambda email: prior_history)
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "Customer contacted support previously.")
    monkeypatch.setattr(
        "app.agent.save_interaction",
        lambda email, interaction: saved.update({"email": email, "interaction": interaction}),
    )
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": None,
            "sentiment": "neutral",
            "urgency": "low",
            "is_fraud": False,
            "requires_escalation": False,
            "summary": "Refund request without an order ID.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr(
        "app.agent.generate_reply",
        lambda context: generated_context.update(context) or "Please share your order ID.",
    )
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: sent.update({"ticket_id": ticket_id, "message": message}) or {"status": "success"},
    )

    # Email mocks
    _apply_common_email_mocks(monkeypatch)

    result = process_ticket(sample_ticket(body="I need a refund"))

    assert result["status"] == "success"
    assert generated_context == {
        "name": "Alice",
        "intent": "refund",
        "decision": "ask_clarification",
        "reason": "Please share your order ID so I can review your request.",
        "sentiment": "neutral",
        "tier": "regular",
        "order_status": "unknown",
        "escalation_status": "not_escalated",
        "recent_history": prior_history[-3:],
        "history_summary": "Customer contacted support previously.",
        "prior_escalations": 0,
        "repeated_issue_count": 0,
    }
    assert sent["message"] == "Please share your order ID."
    assert saved["interaction"]["decision"] == "ask_clarification"
    assert result["email_sent"] is True


# ──────────────────────────────────────────────────────────────────────────────
# EMAIL NOTIFICATION TESTS
# ──────────────────────────────────────────────────────────────────────────────

def test_email_sent_on_successful_refund(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """
    End-to-end: refund approved → reply sent → email generated → email sent.
    Verifies the 📧 log line is printed and the result dict contains email_sent=True.
    """
    email_calls = {}

    monkeypatch.setattr("app.agent.get_history", lambda email: [])
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "No prior support history.")
    monkeypatch.setattr("app.agent.save_interaction", lambda email, interaction: None)
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": "ORD-1001",
            "sentiment": "neutral",
            "urgency": "medium",
            "is_fraud": False,
            "requires_escalation": False,
            "summary": "Refund request for ORD-1001.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr("app.agent.get_order", lambda order_id: order_response(order_id=order_id))
    monkeypatch.setattr(
        "app.agent.check_refund_eligibility",
        lambda order_id: {"status": "success", "data": {"eligible": True, "reason": "Within return window"}},
    )
    monkeypatch.setattr(
        "app.agent.issue_refund",
        lambda order_id, amount: {"status": "success", "data": {"message": "Refund of $129.99 processed."}},
    )
    monkeypatch.setattr("app.agent.generate_reply", lambda ctx: "Your refund has been processed.")
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: {"status": "success"},
    )

    # Mock email content generation and delivery — capture calls
    monkeypatch.setattr(
        "app.agent.generate_email_content",
        lambda ctx: {
            "subject": f"Refund Confirmed for {ctx.get('customer_name', 'Customer')}",
            "body": f"Dear {ctx.get('customer_name', 'Customer')}, your refund is on its way.",
        },
    )
    monkeypatch.setattr(
        "app.agent.send_email",
        lambda to_email, subject, body: email_calls.update(
            {"to": to_email, "subject": subject, "body": body}
        )
        or {"status": "success", "message": f"Email delivered to {to_email}"},
    )

    result = process_ticket(sample_ticket())

    # Core assertions
    assert result["status"] == "success"
    assert result["decision"] == "refund_approved"
    assert result["email_sent"] is True

    # Verify send_email was called with the right recipient
    assert email_calls["to"] == "alice@example.com"
    assert "Refund Confirmed" in email_calls["subject"]

    # Verify the 📧 log line was printed
    captured = capsys.readouterr()
    assert "📧 Email sent to alice@example.com" in captured.out


def test_email_failure_does_not_crash_agent(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """
    When send_email returns an error, the agent should:
    - Log the failure
    - Continue execution
    - Return email_sent=False
    - NOT raise any exception
    """
    monkeypatch.setattr("app.agent.get_history", lambda email: [])
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "No prior support history.")
    monkeypatch.setattr("app.agent.save_interaction", lambda email, interaction: None)
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "cancel",
            "order_id": None,
            "sentiment": "neutral",
            "urgency": "low",
            "is_fraud": False,
            "requires_escalation": False,
            "summary": "Cancellation request.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr("app.agent.generate_reply", lambda ctx: "Your order has been cancelled.")
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: {"status": "success"},
    )

    # Email content generation succeeds, but delivery fails
    monkeypatch.setattr("app.agent.generate_email_content", _stub_email_content)
    monkeypatch.setattr("app.agent.send_email", _stub_send_email_failure)

    result = process_ticket(sample_ticket(body="Cancel my order please"))

    # Agent should succeed even though email failed
    assert result["status"] == "success"
    assert result["decision"] == "cancel_approved"
    assert result["email_sent"] is False
    assert result["memory_saved"] is True

    # Failure should be logged
    captured = capsys.readouterr()
    assert "Email failed" in captured.out


def test_email_exception_does_not_crash_agent(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    """
    When generate_email_content or send_email raises an unexpected exception,
    the agent must catch it, log it, and continue.
    """
    monkeypatch.setattr("app.agent.get_history", lambda email: [])
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "No prior support history.")
    monkeypatch.setattr("app.agent.save_interaction", lambda email, interaction: None)
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "tracking",
            "order_id": "ORD-2002",
            "sentiment": "neutral",
            "urgency": "low",
            "is_fraud": False,
            "requires_escalation": False,
            "summary": "Tracking request for ORD-2002.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())
    monkeypatch.setattr("app.agent.get_order", lambda order_id: order_response(order_id=order_id))
    monkeypatch.setattr("app.agent.generate_reply", lambda ctx: "Your order is in transit.")
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: {"status": "success"},
    )

    # Simulate an unexpected crash inside generate_email_content
    def _exploding_email_content(ctx):
        raise ConnectionError("DNS resolution failed")

    monkeypatch.setattr("app.agent.generate_email_content", _exploding_email_content)
    monkeypatch.setattr("app.agent.send_email", _stub_send_email_success)

    result = process_ticket(sample_ticket(body="Where is my order ORD-2002?"))

    # Agent should succeed — the exception is swallowed
    assert result["status"] == "success"
    assert result["decision"] == "tracking_update"
    assert result["email_sent"] is False
    assert result["memory_saved"] is True

    # The caught exception should be logged
    captured = capsys.readouterr()
    assert "Email notification error" in captured.out


def test_no_email_sent_when_reply_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Email must ONLY be sent after a successful send_reply().
    If send_reply fails, no email should be attempted.
    """
    email_attempted = {"called": False}

    monkeypatch.setattr("app.agent.get_history", lambda email: [])
    monkeypatch.setattr("app.agent.format_history_for_llm", lambda history: "No prior support history.")
    monkeypatch.setattr("app.agent.save_interaction", lambda email, interaction: None)
    monkeypatch.setattr(
        "app.agent.analyze_ticket",
        lambda text: {
            "intent": "refund",
            "order_id": "ORD-1001",
            "sentiment": "neutral",
            "urgency": "low",
            "is_fraud": True,
            "requires_escalation": False,
            "summary": "Fraud attempt.",
        },
    )
    monkeypatch.setattr("app.agent.get_customer", lambda email: customer_response())

    # send_reply FAILS
    monkeypatch.setattr(
        "app.agent.send_reply",
        lambda ticket_id, message: {"status": "error", "message": "Service unavailable"},
    )

    # Track whether send_email is called — it should NOT be
    def _tracking_send_email(to_email, subject, body):
        email_attempted["called"] = True
        return {"status": "success", "message": "delivered"}

    monkeypatch.setattr("app.agent.generate_email_content", _stub_email_content)
    monkeypatch.setattr("app.agent.send_email", _tracking_send_email)

    result = process_ticket(sample_ticket())

    assert result["email_sent"] is False
    assert result["memory_saved"] is False
    assert email_attempted["called"] is False, "send_email should NOT be called when send_reply fails"
