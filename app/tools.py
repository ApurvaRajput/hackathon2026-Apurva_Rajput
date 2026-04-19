import random
from datetime import datetime
from typing import Dict, Any

# ✅ Correct import
from app.data_loader import load_all_data

# ✅ Load data ONCE
data = load_all_data()

# ✅ Convert Pydantic models → dict
customers = [c.model_dump() for c in data.customers]
orders = [o.model_dump() for o in data.orders]
products = [p.model_dump() for p in data.products]
tickets = [t.model_dump() for t in data.tickets]


# -------------------- HELPER FUNCTIONS --------------------

def simulate_failure():
    """
    Simulates random failures:
    - 10% → timeout
    - 10% → malformed response
    """
    rand = random.random()

    if rand < 0.1:
        raise Exception("Tool timeout")

    elif rand < 0.2:
        return {"status": "error", "message": "Malformed tool output"}

    return None


def success_response(data: Any) -> Dict:
    return {
        "status": "success",
        "data": data
    }


def error_response(message: str) -> Dict:
    return {
        "status": "error",
        "message": message
    }


# -------------------- TOOL FUNCTIONS --------------------

def get_customer(email: str) -> Dict:
    try:
        failure = simulate_failure()
        if failure:
            return failure

        for c in customers:
            if c["email"] == email:
                return success_response(c)

        return error_response("Customer not found")

    except Exception as e:
        return error_response(str(e))


def get_order(order_id: str) -> Dict:
    try:
        failure = simulate_failure()
        if failure:
            return failure

        for o in orders:
            if o["order_id"] == order_id:
                return success_response(o)

        return error_response("Order not found")

    except Exception as e:
        return error_response(str(e))


def get_product(product_id: str) -> Dict:
    try:
        for p in products:
            if p["product_id"] == product_id:
                return success_response(p)

        return error_response("Product not found")

    except Exception as e:
        return error_response(str(e))


def check_refund_eligibility(order_id: str) -> Dict:
    try:
        failure = simulate_failure()
        if failure:
            return failure

        # Find order
        order = next((o for o in orders if o["order_id"] == order_id), None)
        if not order:
            return error_response("Order not found")

        # Already refunded
        if order.get("refund_status") == "refunded":
            return success_response({
                "eligible": False,
                "reason": "Already refunded"
            })

        # Find product
        product = next((p for p in products if p["product_id"] == order["product_id"]), None)

        # Find customer
        customer = next((c for c in customers if c["customer_id"] == order["customer_id"]), None)

        today = datetime.now().date()

        # ✅ DAMAGED CHECK
        notes = order.get("notes", "").lower()
        if "damaged" in notes or "cracked" in notes:
            return success_response({
                "eligible": True,
                "reason": "Item damaged"
            })

        # ✅ RETURN WINDOW CHECK
        if order.get("return_deadline"):
            deadline = datetime.strptime(order["return_deadline"], "%Y-%m-%d").date()
            if today <= deadline:
                return success_response({
                    "eligible": True,
                    "reason": "Within return window"
                })

        # ✅ VIP OVERRIDE
        if customer and customer.get("tier") == "vip":
            if "extended return" in customer.get("notes", "").lower():
                return success_response({
                    "eligible": True,
                    "reason": "VIP extended return"
                })

        # ✅ NON RETURNABLE
        if product and not product.get("returnable", True):
            return success_response({
                "eligible": False,
                "reason": "Product is non-returnable"
            })

        return success_response({
            "eligible": False,
            "reason": "Return window expired"
        })

    except Exception as e:
        return error_response(str(e))


def issue_refund(order_id: str, amount: float) -> Dict:
    try:
        failure = simulate_failure()
        if failure:
            return failure

        eligibility = check_refund_eligibility(order_id)

        if eligibility["status"] != "success":
            return eligibility

        if not eligibility["data"]["eligible"]:
            return error_response("Refund not eligible")

        for o in orders:
            if o["order_id"] == order_id:
                o["refund_status"] = "refunded"

                return success_response({
                    "message": f"Refund of {amount} issued for {order_id}"
                })

        return error_response("Order not found")

    except Exception as e:
        return error_response(str(e))


def send_reply(ticket_id: str, message: str) -> Dict:
    try:
        print(f"\n📩 Sending reply to Ticket {ticket_id}:")
        print(message)

        return success_response({"message": "Reply sent"})

    except Exception as e:
        return error_response(str(e))


def escalate(ticket_id: str, summary: str, priority: str) -> Dict:
    try:
        print(f"\n🚨 ESCALATION TRIGGERED")
        print(f"Ticket: {ticket_id}")
        print(f"Priority: {priority}")
        print(f"Summary: {summary}")

        return success_response({"message": "Escalated successfully"})

    except Exception as e:
        return error_response(str(e))


def search_knowledge_base(query: str) -> Dict:
    try:
        q = query.lower()

        if "refund" in q:
            return success_response({
                "answer": "Refunds are processed within 5–7 business days after approval."
            })

        elif "return" in q:
            return success_response({
                "answer": "Most products have a 30-day return window from delivery."
            })

        elif "warranty" in q:
            return success_response({
                "answer": "Warranty covers manufacturing defects only."
            })

        else:
            return success_response({
                "answer": "Please refer to the help center for more details."
            })

    except Exception as e:
        return error_response(str(e))


# -------------------- TEST BLOCK --------------------

if __name__ == "__main__":
    print("🔍 Testing get_customer:")
    print(get_customer("alice.turner@email.com"))

    print("\n📦 Testing get_order:")
    print(get_order("ORD-1001"))

    print("\n💰 Testing refund eligibility:")
    print(check_refund_eligibility("ORD-1001"))

    print("\n💸 Testing issue_refund:")
    print(issue_refund("ORD-1001", 129.99))