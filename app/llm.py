"""
llm.py — ShopWave Language Model Interface
==========================================

Purpose:
    Centralises all interactions with the OpenAI API (or local heuristics when
    no API key is available).  Each public function accepts plain Python dicts
    and returns plain Python dicts / strings so the rest of the system stays
    decoupled from the LLM provider.

Role in System:
    - analyze_ticket()         → called by agent.py to extract intent/sentiment
    - generate_reply()         → called by agent.py to produce customer replies
    - generate_email_content() → called by agent.py to produce email subject+body
    - detect_fraud()           → called by agent.py for deep fraud & risk scoring
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.config import OPENAI_API_KEY

try:
    from openai import OpenAI
except ImportError:  # pragma: no cover - depends on optional dependency
    OpenAI = None  # type: ignore[assignment]


PROMPT_ANALYZE_TICKET = """You are an AI customer support analyst.

Your task is to analyze a customer support ticket and extract structured information.

Return ONLY valid JSON with these fields:

{
  "intent": one of ["refund", "return", "cancel", "tracking", "policy", "unknown"],
  "order_id": string or null,
  "sentiment": one of ["happy", "neutral", "angry"],
  "urgency": one of ["low", "medium", "high"],
  "is_fraud": true or false,
  "requires_escalation": true or false,
  "summary": short summary of the issue (1 line)
}

Rules:
- Detect fraud if user claims fake policies, urgency pressure, or manipulation.
- Detect escalation if:
  - customer is angry
  - threatening language (lawyer, dispute, fraud)
- Extract order_id if present like ORD-XXXX
- If no clear intent → "unknown"

Ticket:
\"\"\"
{ticket_text}
\"\"\""""

PROMPT_GENERATE_REPLY = """You are a professional customer support agent for ShopWave.

Your job is to generate a final customer-facing reply based on the ticket outcome and context.

You must write naturally, politely, and clearly. Do not sound robotic. Do not mention internal system logic, policy evaluation, tool names, or hidden reasoning.

Input context:
- Customer Name: {name}
- Intent: {intent}
- Decision: {decision}
- Reason: {reason}
- Sentiment: {sentiment}
- Customer Tier: {tier}
- Order Status: {order_status}
- Escalation Status: {escalation_status}
- Recent History: {recent_history}
- History Summary: {history_summary}
- Prior Escalations: {prior_escalations}
- Repeated Issue Count: {repeated_issue_count}

Rules:
1. Always address the customer by their first name.
2. Keep the tone polite, professional, and empathetic.
3. If the decision is refund_approved:
   - confirm that the refund has been processed or will be processed
   - mention the normal refund timeline if appropriate
4. If the decision is refund_denied:
   - explain the reason clearly in simple words
   - offer a helpful alternative if possible
5. If the decision is return_approved:
   - confirm the return approval and next step
6. If the decision is return_denied:
   - explain the reason clearly and politely
7. If the decision is escalate:
   - tell the customer their case has been sent to a specialist
   - do not mention internal escalation rules
8. If the decision is ask_clarification:
   - ask for the missing details in a short, helpful way
9. If sentiment is angry:
   - use extra empathy and calm wording
10. If customer tier is vip or premium:
   - sound slightly more attentive and considerate
11. Use recent history when helpful:
   - acknowledge repeated issues if the customer contacted support before
   - avoid sounding like this is the first interaction when history exists
   - if there were prior escalations, reassure the customer appropriately
12. Do not mention code, tools, JSON, models, or internal analysis.
13. Do not make promises that are not supported by the decision.
14. Keep the reply concise, human, and useful.

Output requirements:
- Return ONLY the final reply text.
- No JSON.
- No markdown.
- No bullet points.
- No explanation.
- No quotation marks around the answer.

Write the reply now."""


# ──────────────────────────────────────────────────────────────────────────────
# FRAUD DETECTION PROMPT
# ──────────────────────────────────────────────────────────────────────────────

PROMPT_FRAUD_DETECTION = """You are an advanced AI fraud detection system for an e-commerce customer support platform.

Your job is to analyze a customer support ticket and detect suspicious or fraudulent behavior.

Return ONLY valid JSON with this structure:

{
  "is_fraud": true or false,
  "fraud_score": number between 0 and 100,
  "risk_level": "low" | "medium" | "high",
  "fraud_reason": short explanation (1 line),
  "signals": [list of detected fraud signals],
  "requires_escalation": true or false
}

----------------------------
ANALYSIS RULES
----------------------------

Detect fraud if ANY of the following patterns exist:

1. THREAT / PRESSURE LANGUAGE
   - "I will file a complaint"
   - "I will go to court"
   - "refund immediately"
   - "legal action", "consumer court"

2. SUSPICIOUS CLAIMS
   - Claims contradict order status
   - "I never received it" but system says delivered
   - Repeated refund attempts

3. HIGH VALUE ABUSE
   - Expensive orders + refund pressure
   - VIP customers abusing policy

4. PATTERN ABUSE
   - Frequent refunds
   - Same issue repeated

5. AGGRESSIVE / ABUSIVE LANGUAGE
   - rude tone, threats, manipulation

----------------------------
SCORING LOGIC
----------------------------

- Low Risk  (0-30):  Normal behavior
- Medium Risk (31-70): Suspicious
- High Risk  (71-100): Likely fraud

----------------------------
ESCALATION RULE
----------------------------

requires_escalation = true IF:
- risk_level = high
OR
- threat language detected
OR
- fraud_score > 70

----------------------------
INPUT
----------------------------

Ticket:
\"\"\"
{ticket_text}
\"\"\"

Order Data:
{order_data}

Customer Data:
{customer_data}"""


def _build_client() -> Any | None:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    return OpenAI(api_key=OPENAI_API_KEY)


client = _build_client()


# ──────────────────────────────────────────────────────────────────────────────
# HEURISTIC HELPERS (used as fallback for ALL LLM functions)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_order_id(text: str) -> str | None:
    match = re.search(r"\bORD-\d+\b", text, flags=re.IGNORECASE)
    return match.group(0).upper() if match else None


def _detect_intent(text: str) -> str:
    lowered = text.lower()

    if "refund" in lowered:
        return "refund"
    if "return" in lowered:
        return "return"
    if "cancel" in lowered or "cancellation" in lowered:
        return "cancel"
    if any(phrase in lowered for phrase in ["where is my order", "not received", "tracking", "track my order"]):
        return "tracking"
    if "policy" in lowered or "how does" in lowered or "what is your" in lowered:
        return "policy"

    return "unknown"


def _detect_sentiment(text: str) -> str:
    lowered = text.lower()

    angry_terms = [
        "angry",
        "ridiculous",
        "worst",
        "unacceptable",
        "fraud",
        "chargeback",
        "lawyer",
        "dispute",
        "scam",
        "terrible",
        "immediately",
    ]
    happy_terms = ["thanks", "thank you", "appreciate", "glad", "happy"]

    if any(term in lowered for term in angry_terms):
        return "angry"
    if any(term in lowered for term in happy_terms):
        return "happy"
    return "neutral"


def _detect_urgency(text: str) -> str:
    lowered = text.lower()

    high_terms = [
        "immediately",
        "asap",
        "urgent",
        "right now",
        "today",
        "now",
        "or else",
    ]
    medium_terms = ["soon", "please respond", "follow up", "waiting", "when"]

    if any(term in lowered for term in high_terms):
        return "high"
    if any(term in lowered for term in medium_terms):
        return "medium"
    return "low"


def _detect_fraud(text: str) -> bool:
    lowered = text.lower()

    fake_policy_claims = [
        "fake policy",
        "made up policy",
        "your policy is fake",
        "this policy is fake",
    ]
    manipulation_terms = [
        "or else",
        "do it now",
        "refund me right now",
        "you must refund me",
        "i know your policy is fake",
    ]

    return any(term in lowered for term in fake_policy_claims + manipulation_terms)


def _requires_escalation(sentiment: str, text: str) -> bool:
    lowered = text.lower()
    threatening_terms = ["lawyer", "dispute", "fraud", "chargeback", "legal action"]

    return sentiment == "angry" or any(term in lowered for term in threatening_terms)


def _build_summary(intent: str, order_id: str | None, text: str) -> str:
    clean_text = " ".join(text.strip().split())
    if intent == "unknown":
        base = "Customer needs help but the request is unclear."
    else:
        base = f"Customer requested {intent} support"
        if order_id:
            base += f" for {order_id}"
        base += "."

    if clean_text:
        snippet = clean_text[:80]
        if len(clean_text) > 80:
            snippet += "..."
        return f"{base} {snippet}"

    return base


def _heuristic_analysis(ticket_text: str) -> dict[str, Any]:
    intent = _detect_intent(ticket_text)
    order_id = _extract_order_id(ticket_text)
    sentiment = _detect_sentiment(ticket_text)
    urgency = _detect_urgency(ticket_text)
    is_fraud = _detect_fraud(ticket_text)
    requires_escalation = _requires_escalation(sentiment, ticket_text)

    return {
        "intent": intent,
        "order_id": order_id,
        "sentiment": sentiment,
        "urgency": urgency,
        "is_fraud": is_fraud,
        "requires_escalation": requires_escalation,
        "summary": _build_summary(intent, order_id, ticket_text),
    }


# ──────────────────────────────────────────────────────────────────────────────
# HEURISTIC FRAUD DETECTION (fallback when OpenAI is unavailable)
# ──────────────────────────────────────────────────────────────────────────────

_THREAT_SIGNALS: list[tuple[str, str]] = [
    ("file a complaint",    "Threat: filing a complaint"),
    ("go to court",         "Threat: legal court action"),
    ("legal action",        "Threat: legal action"),
    ("consumer court",      "Threat: consumer court"),
    ("consumer forum",      "Threat: consumer forum"),
    ("i will sue",          "Threat: lawsuit"),
    ("lawyer",              "Threat: lawyer involvement"),
    ("chargeback",          "Threat: chargeback"),
]

_PRESSURE_SIGNALS: list[tuple[str, str]] = [
    ("refund immediately",  "Pressure: immediate refund demand"),
    ("refund me right now", "Pressure: immediate refund demand"),
    ("money back now",      "Pressure: immediate refund demand"),
    ("or else",             "Pressure: ultimatum language"),
    ("do it now",           "Pressure: ultimatum language"),
    ("you must refund",     "Pressure: coercive demand"),
    ("asap",                "Pressure: urgent demand"),
]

_SUSPICIOUS_SIGNALS: list[tuple[str, str]] = [
    ("never received",      "Claim: non-delivery (verify against order status)"),
    ("didn't receive",      "Claim: non-delivery (verify against order status)"),
    ("not delivered",       "Claim: non-delivery (verify against order status)"),
    ("fake policy",         "Manipulation: policy challenged"),
    ("made up policy",      "Manipulation: policy challenged"),
    ("this is fraud",       "Accusation: customer calling fraud"),
    ("scam",                "Accusation: scam allegation"),
]

_AGGRESSIVE_SIGNALS: list[tuple[str, str]] = [
    ("ridiculous",          "Tone: aggressive"),
    ("unacceptable",        "Tone: aggressive"),
    ("worst service",       "Tone: aggressive"),
    ("terrible",            "Tone: aggressive"),
    ("pathetic",            "Tone: aggressive"),
]


def _heuristic_fraud_detection(
    ticket_text: str,
    order_data: dict[str, Any],
    customer_data: dict[str, Any],
) -> dict[str, Any]:
    """Rule-based fraud scoring used when the OpenAI client is unavailable."""
    lowered = ticket_text.lower()
    signals: list[str] = []
    score = 0

    # --- threat language (heavy weight) ---
    for phrase, label in _THREAT_SIGNALS:
        if phrase in lowered:
            signals.append(label)
            score += 25

    # --- pressure language ---
    for phrase, label in _PRESSURE_SIGNALS:
        if phrase in lowered:
            signals.append(label)
            score += 15

    # --- suspicious claims ---
    for phrase, label in _SUSPICIOUS_SIGNALS:
        if phrase in lowered:
            signals.append(label)
            score += 15

    # --- aggressive tone ---
    for phrase, label in _AGGRESSIVE_SIGNALS:
        if phrase in lowered:
            signals.append(label)
            score += 10

    # --- delivery contradiction ---
    order_status = str(order_data.get("status", "")).lower()
    if order_status == "delivered" and any(
        p in lowered for p in ["never received", "didn't receive", "not delivered"]
    ):
        signals.append("Contradiction: order marked delivered but customer claims non-delivery")
        score += 20

    # --- high-value order with refund pressure ---
    order_amount = float(order_data.get("amount", 0))
    customer_tier = str(customer_data.get("tier", "standard")).lower()
    if order_amount > 5000 and any(p in lowered for p, _ in _PRESSURE_SIGNALS):
        signals.append(f"High-value order (₹{order_amount:.0f}) with refund pressure")
        score += 15

    # --- VIP abusing policy ---
    if customer_tier == "vip" and score > 30:
        signals.append("VIP customer with elevated fraud risk")
        score += 10

    # cap at 100
    score = min(score, 100)

    # deduplicate signals while preserving order
    seen: set[str] = set()
    unique_signals: list[str] = []
    for s in signals:
        if s not in seen:
            seen.add(s)
            unique_signals.append(s)

    # determine risk level
    if score >= 71:
        risk_level = "high"
    elif score >= 31:
        risk_level = "medium"
    else:
        risk_level = "low"

    is_fraud = score >= 71
    requires_escalation = score > 70 or any(
        phrase in lowered for phrase, _ in _THREAT_SIGNALS
    )

    fraud_reason = (
        unique_signals[0] if unique_signals
        else "No fraud signals detected"
    )

    return {
        "is_fraud": is_fraud,
        "fraud_score": score,
        "risk_level": risk_level,
        "fraud_reason": fraud_reason,
        "signals": unique_signals,
        "requires_escalation": requires_escalation,
    }


def detect_fraud(
    ticket_text: str,
    order_data: dict[str, Any],
    customer_data: dict[str, Any],
) -> dict[str, Any]:
    """Run the fraud & risk analysis pipeline on a support ticket.

    When the OpenAI client is available the full LLM prompt is used
    (PROMPT_FRAUD_DETECTION) which produces richer, context-aware signals.
    When the client is unavailable (no API key / import error) the
    keyword-based heuristic fallback is used so the agent still has a
    fraud verdict on every ticket.

    Parameters
    ----------
    ticket_text   : str  — Raw body text of the support ticket.
    order_data    : dict — Data returned by get_order() (or empty dict).
    customer_data : dict — Data returned by get_customer() (or empty dict).

    Returns
    -------
    dict
        {is_fraud, fraud_score, risk_level, fraud_reason, signals,
         requires_escalation}
    """
    _SAFE_FALLBACK = {
        "is_fraud": False,
        "fraud_score": 0,
        "risk_level": "low",
        "fraud_reason": "Parsing failed — defaulting to safe",
        "signals": [],
        "requires_escalation": False,
    }

    if client is None:
        return _heuristic_fraud_detection(ticket_text, order_data, customer_data)

    prompt = (
        PROMPT_FRAUD_DETECTION
        .replace("{ticket_text}", ticket_text)
        .replace("{order_data}", str(order_data))
        .replace("{customer_data}", str(customer_data))
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences if the model wraps output in ```json … ```
        if content.startswith("```"):
            content = re.sub(r"^```[a-z]*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        parsed = json.loads(content)

        return {
            "is_fraud":            bool(parsed.get("is_fraud", False)),
            "fraud_score":         int(parsed.get("fraud_score", 0)),
            "risk_level":          str(parsed.get("risk_level", "low")),
            "fraud_reason":        str(parsed.get("fraud_reason", "N/A")),
            "signals":             list(parsed.get("signals", [])),
            "requires_escalation": bool(parsed.get("requires_escalation", False)),
        }

    except Exception:
        # LLM unavailable or JSON parse error → fall back to heuristic
        try:
            return _heuristic_fraud_detection(ticket_text, order_data, customer_data)
        except Exception:
            return _SAFE_FALLBACK


def analyze_ticket(ticket_text: str) -> dict[str, Any]:
    prompt = PROMPT_ANALYZE_TICKET.replace("{ticket_text}", ticket_text)

    if client is None:
        return _heuristic_analysis(ticket_text)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
        parsed = json.loads(content)

        return {
            "intent": parsed.get("intent", "unknown"),
            "order_id": parsed.get("order_id"),
            "sentiment": parsed.get("sentiment", "neutral"),
            "urgency": parsed.get("urgency", "low"),
            "is_fraud": bool(parsed.get("is_fraud", False)),
            "requires_escalation": bool(parsed.get("requires_escalation", False)),
            "summary": parsed.get("summary", _build_summary("unknown", None, ticket_text)),
        }
    except Exception:
        return _heuristic_analysis(ticket_text)


def _first_name(name: str | None) -> str:
    if not name:
        return "Customer"
    return str(name).strip().split()[0] or "Customer"


def _fallback_reply(context: dict[str, Any]) -> str:
    name = _first_name(context.get("name"))
    intent = context.get("intent") or "request"
    decision = context.get("decision") or "ask_clarification"
    reason = context.get("reason") or ""
    sentiment = context.get("sentiment") or "neutral"
    tier = str(context.get("tier") or "standard").lower()
    order_status = context.get("order_status") or "unknown"
    escalation_status = context.get("escalation_status") or "not_escalated"
    history_summary = context.get("history_summary") or "No prior support history."
    prior_escalations = int(context.get("prior_escalations") or 0)
    repeated_issue_count = int(context.get("repeated_issue_count") or 0)

    apology = "I’m sorry for the frustration. " if sentiment == "angry" else ""
    attentiveness = "I appreciate your patience. " if tier in {"vip", "premium"} else ""
    history_ack = ""
    if repeated_issue_count > 0:
        history_ack = "I can see you've contacted us about this before. "
    elif history_summary != "No prior support history.":
        history_ack = "I can see you've been in touch with us before. "

    if decision in {"missing_order_id", "ask_clarification", "needs_clarification"}:
        detail = reason or f"please share your order ID so I can help with your {intent} request."
        return f"Hi {name}, {apology}{attentiveness}{history_ack}{detail}"

    if decision == "refund_approved":
        timeline = " It should appear in your original payment method within 5 to 7 business days."
        return f"Hi {name}, {attentiveness}{history_ack}your refund has been processed successfully.{timeline}"

    if decision == "refund_denied":
        detail = f" because {reason}" if reason else ""
        return (
            f"Hi {name}, {apology}{attentiveness}{history_ack}I’m unable to approve the refund{detail}. "
            "If you'd like, I can help review other available options."
        )

    if decision == "return_approved":
        next_step = f" Next step: {reason}" if reason else " We’ll share the next return steps shortly."
        return f"Hi {name}, {attentiveness}{history_ack}your return has been approved.{next_step}"

    if decision == "return_denied":
        detail = f" because {reason}" if reason else ""
        return (
            f"Hi {name}, {apology}{attentiveness}{history_ack}I’m unable to approve the return{detail}. "
            "If you have more details to share, I can review the case again."
        )

    if decision == "cancel_approved":
        return f"Hi {name}, {attentiveness}{history_ack}your order has been cancelled successfully."

    if decision == "tracking_update":
        detail = reason or f"your order is currently {order_status}."
        return f"Hi {name}, {attentiveness}{history_ack}{detail}"

    if decision == "policy_answer":
        return f"Hi {name}, {attentiveness}{history_ack}{reason or 'Here is the information you requested.'}"

    if decision == "escalate" or escalation_status == "escalated":
        escalation_ack = ""
        if prior_escalations > 0:
            escalation_ack = "I understand this has needed extra attention before. "
        return (
            f"Hi {name}, {apology}{attentiveness}{history_ack}{escalation_ack}"
            "your case has been sent to a specialist for review. "
            "They’ll follow up with you as soon as possible."
        )

    return f"Hi {name}, {apology}{attentiveness}{history_ack}please share a few more details so I can help with your request."


def generate_reply(context: dict[str, Any]) -> str:
    prompt = PROMPT_GENERATE_REPLY.format(
        name=context.get("name", "Customer"),
        intent=context.get("intent", "unknown"),
        decision=context.get("decision", "unknown"),
        reason=context.get("reason", ""),
        sentiment=context.get("sentiment", "neutral"),
        tier=context.get("tier", "standard"),
        order_status=context.get("order_status", "unknown"),
        escalation_status=context.get("escalation_status", "not_escalated"),
        recent_history=context.get("recent_history", []),
        history_summary=context.get("history_summary", "No prior support history."),
        prior_escalations=context.get("prior_escalations", 0),
        repeated_issue_count=context.get("repeated_issue_count", 0),
    )

    if client is None:
        return _fallback_reply(context)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        return (response.choices[0].message.content or "").strip() or _fallback_reply(context)
    except Exception:
        return _fallback_reply(context)


# ──────────────────────────────────────────────────────────────────────────────
# EMAIL CONTENT GENERATION
# ──────────────────────────────────────────────────────────────────────────────

PROMPT_EMAIL_CONTENT = """You are a professional customer support agent for ShopWave.

Write a polite, warm, and professional resolution confirmation email for a customer.

Context:
- Customer Name: {customer_name}
- Issue Summary: {issue_summary}
- Final Decision: {final_decision}
- Support Reply Already Sent: {reply_message}

Requirements:
1. The subject line should be specific, clear, and friendly (not generic).
2. The email body must:
   - Begin with a warm greeting using the customer's first name.
   - Reference the specific issue (e.g. "regarding your refund request for order ORD-XXXX").
   - Clearly confirm the outcome without restating technical decisions verbatim.
   - Include a short, human next-steps sentence where relevant.
   - Close warmly (e.g. "Warm regards, ShopWave Support Team").
3. Do NOT use markdown formatting (no **, no bullet points).
4. Do NOT mention internal tools, LLMs, scores, or system names.
5. Keep the tone conversational, not stiff or corporate.

Return ONLY valid JSON in this exact format:
{{
  "subject": "...",
  "body": "..."
}}

No explanation. No markdown. Just the JSON."""


def _fallback_email_content(context: dict[str, Any]) -> dict[str, Any]:
    """Produce a heuristic email subject and body when the LLM is unavailable.

    Parameters
    ----------
    context : dict
        Keys used: customer_name, issue_summary, final_decision, reply_message.

    Returns
    -------
    dict
        {"subject": str, "body": str}
    """
    name = str(context.get("customer_name") or "Customer").strip().split()[0]
    decision = str(context.get("final_decision") or "resolved").replace("_", " ")
    reply = str(context.get("reply_message") or "")
    summary = str(context.get("issue_summary") or "your recent support request")

    subject = f"Your ShopWave Support Request Has Been {decision.title()}"

    body = (
        f"Dear {name},\n\n"
        f"Thank you for reaching out to ShopWave Support regarding {summary}.\n\n"
        f"{reply}\n\n"
        "If you have any further questions or need additional assistance, "
        "please don't hesitate to contact us — we're always happy to help.\n\n"
        "Warm regards,\n"
        "ShopWave Customer Support Team"
    )

    return {"subject": subject, "body": body}


def generate_email_content(context: dict[str, Any]) -> dict[str, Any]:
    """Use the LLM to craft a personalised resolution email (subject + body).

    Falls back to a heuristic template when the OpenAI client is not
    configured or the API call fails, so the system always produces a
    deliverable email even in offline / test environments.

    Parameters
    ----------
    context : dict
        Required keys:

        - ``customer_name``  (str)  — Full name of the customer.
        - ``issue_summary``  (str)  — One-line description of the issue.
        - ``final_decision`` (str)  — Agent decision label, e.g. "refund_approved".
        - ``reply_message``  (str)  — The reply already sent to the customer.

    Returns
    -------
    dict
        {"subject": str, "body": str}

    Example usage
    -------------
    >>> content = generate_email_content({
    ...     "customer_name": "Alice Smith",
    ...     "issue_summary": "Refund request for ORD-1001",
    ...     "final_decision": "refund_approved",
    ...     "reply_message": "Hi Alice, your refund has been processed …",
    ... })
    >>> print(content["subject"])
    'Your ShopWave Refund for ORD-1001 Has Been Approved'
    """
    # Build the LLM prompt by injecting context values
    prompt = PROMPT_EMAIL_CONTENT.format(
        customer_name=context.get("customer_name", "Customer"),
        issue_summary=context.get("issue_summary", "your recent support request"),
        final_decision=context.get("final_decision", "resolved"),
        reply_message=context.get("reply_message", ""),
    )

    # If no OpenAI client is available, skip the API call entirely
    if client is None:
        return _fallback_email_content(context)

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.6,   # slightly lower temp for consistent formatting
        )
        content_str = (response.choices[0].message.content or "").strip()

        # Parse the JSON the LLM returned
        parsed = json.loads(content_str)

        # Validate that both keys are present and non-empty strings
        subject = str(parsed.get("subject", "")).strip()
        body = str(parsed.get("body", "")).strip()

        if subject and body:
            return {"subject": subject, "body": body}

        # Partial / empty response — use fallback
        return _fallback_email_content(context)

    except (json.JSONDecodeError, KeyError, Exception):
        # Any LLM or parsing error → degrade gracefully to heuristic
        return _fallback_email_content(context)
