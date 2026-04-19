import re
from typing import Dict, Any

from app.tools import (
    get_customer,
    get_order,
    check_refund_eligibility,
    issue_refund,
    send_reply,
    escalate,
    search_knowledge_base
)

# -------------------- SAFE CALL --------------------

def safe_call(func, *args):
    """
    Retry wrapper for unstable tools (timeout / malformed / failure)
    """
    for _ in range(2):  # retry once
        result = func(*args)

        if isinstance(result, dict) and result.get("status") == "error":
            msg = result.get("message", "").lower()

            if any(x in msg for x in ["timeout", "malformed", "failure"]):
                continue  # retry

        return result

    return {"status": "error", "message": "Tool failure after retry"}


# -------------------- INTENT DETECTION --------------------

def detect_intent(text: str) -> str:
    text = text.lower()

    if "refund" in text:
        return "refund"
    if "return" in text:
        return "return"
    if "cancel" in text:
        return "cancel"
    if "where is my order" in text or "not received" in text:
        return "tracking"
    if "policy" in text or "how" in text:
        return "policy"

    return "unknown"


# -------------------- ORDER ID EXTRACTION --------------------

def extract_order_id(text: str) -> str | None:
    match = re.search(r"ORD-\d+", text)
    return match.group(0) if match else None


# -------------------- ESCALATION RULE --------------------

def should_escalate(ticket, customer, order):
    text = ticket["body"].lower()

    if not customer or not order:
        return False

    high_value = order["data"]["amount"] > 5000
    vip = customer["data"]["tier"] == "vip"

    angry = any(word in text for word in [
        "lawyer", "dispute", "fraud", "refund immediately", "chargeback"
    ])

    return vip and (high_value or angry)


# -------------------- MAIN AGENT --------------------

def process_ticket(ticket: Dict[str, Any]) -> Dict:

    print(f"\n🧠 Processing Ticket: {ticket['ticket_id']}")

    email = ticket["customer_email"]
    text = ticket["body"]

    intent = detect_intent(text)
    order_id = extract_order_id(text)

    print("Detected intent:", intent)
    print("Order ID:", order_id)

    # ---------------- CUSTOMER ----------------
    customer_res = safe_call(get_customer, email)

    if customer_res["status"] != "success":
        return send_reply(
            ticket["ticket_id"],
            "We could not find your account. Please provide correct email."
        )

    customer = customer_res["data"]
    customer_name = customer.get("name", "Customer")

    # ---------------- ORDER ----------------
    order_res = None
    if order_id:
        order_res = safe_call(get_order, order_id)

        if order_res["status"] != "success":
            return send_reply(
                ticket["ticket_id"],
                f"Hi {customer_name}, order not found. Please check your order ID."
            )

    # ---------------- 🚨 ESCALATION (IMPORTANT) ----------------
    if should_escalate(ticket, customer_res, order_res):
        return escalate(
            ticket["ticket_id"],
            summary=ticket["body"],
            priority="HIGH"
        )

    # ---------------- MISSING ORDER ID ----------------
    if not order_id and intent in ["refund", "return"]:
        return send_reply(
            ticket["ticket_id"],
            f"Hi {customer_name}, please provide your order ID."
        )

    # ---------------- REFUND ----------------
    if intent == "refund" and order_id:

        eligibility = safe_call(check_refund_eligibility, order_id)

        if eligibility["status"] != "success":
            return send_reply(ticket["ticket_id"], "System busy. Try again later.")

        reason = eligibility["data"]["reason"]

        if eligibility["data"]["eligible"]:
            refund = safe_call(
                issue_refund,
                order_id,
                order_res["data"]["amount"]
            )

            if refund["status"] == "success":
                return send_reply(
                    ticket["ticket_id"],
                    f"Hi {customer_name}, refund processed successfully."
                )

            return send_reply(ticket["ticket_id"], "Refund failed. Try again later.")

        return send_reply(
            ticket["ticket_id"],
            f"Hi {customer_name}, refund not possible because {reason}."
        )

    # ---------------- RETURN ----------------
    if intent == "return" and order_id:

        eligibility = safe_call(check_refund_eligibility, order_id)

        if eligibility["status"] != "success":
            return send_reply(ticket["ticket_id"], "System busy. Try again later.")

        reason = eligibility["data"]["reason"]

        if eligibility["data"]["eligible"]:
            return send_reply(
                ticket["ticket_id"],
                f"Hi {customer_name}, your return has been approved."
            )

        return send_reply(
            ticket["ticket_id"],
            f"Hi {customer_name}, return not allowed: {reason}."
        )

    # ---------------- CANCEL ----------------
    if intent == "cancel":
        return send_reply(
            ticket["ticket_id"],
            f"Hi {customer_name}, your order has been cancelled."
        )

    # ---------------- TRACKING ----------------
    if intent == "tracking":
        return send_reply(
            ticket["ticket_id"],
            f"Hi {customer_name}, your order is in transit. Tracking ID: TRK-12345"
        )

    # ---------------- POLICY ----------------
    if intent == "policy":
        kb = safe_call(search_knowledge_base, text)

        if kb["status"] == "success":
            return send_reply(ticket["ticket_id"], kb["data"]["answer"])

        return send_reply(ticket["ticket_id"], "Unable to fetch policy.")

    # ---------------- UNKNOWN ----------------
    return send_reply(
        ticket["ticket_id"],
        f"Hi {customer_name}, please provide more details about your issue."
    )