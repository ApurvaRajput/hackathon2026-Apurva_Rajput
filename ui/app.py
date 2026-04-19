"""
ui/app.py — Streamlit UI for the ShopWave AI Support Agent
===========================================================

Run with:
    streamlit run ui/app.py

Make sure the FastAPI backend is running first:
    uvicorn app.api:app --reload --port 8000
"""

import json
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional

import requests
import streamlit as st

# ──────────────────────────────────────────────────────────────
# CONFIGURATION
# ──────────────────────────────────────────────────────────────

API_BASE = "http://localhost:8000"
PAGE_TITLE = "ShopWave AI Support Agent"

# ──────────────────────────────────────────────────────────────
# PAGE SETUP
# ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title=PAGE_TITLE,
    page_icon="🛍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────────────────────
# CUSTOM CSS
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
    /* Global font */
    html, body, [class*="css"] { font-family: 'Segoe UI', sans-serif; }

    /* Page background */
    .stApp { background-color: #0f1117; color: #e0e0e0; }

    /* Header gradient */
    .hero-banner {
        background: linear-gradient(135deg, #1a237e 0%, #4a148c 100%);
        border-radius: 12px;
        padding: 28px 36px;
        margin-bottom: 24px;
        color: white;
    }
    .hero-banner h1 { margin: 0; font-size: 2rem; font-weight: 700; }
    .hero-banner p  { margin: 6px 0 0; opacity: 0.85; font-size: 1rem; }

    /* Metric cards */
    .metric-card {
        background: #1e2130;
        border-radius: 10px;
        padding: 18px 22px;
        border-left: 4px solid #5c6bc0;
        margin-bottom: 12px;
    }
    .metric-label { font-size: 0.72rem; color: #90a4ae; text-transform: uppercase; letter-spacing: 0.08em; }
    .metric-value { font-size: 1.35rem; font-weight: 700; color: #e8eaf6; margin-top: 4px; }

    /* Decision colours */
    .decision-approved { border-left-color: #66bb6a !important; }
    .decision-denied   { border-left-color: #ef5350 !important; }
    .decision-escalate { border-left-color: #ffa726 !important; }
    .decision-clarify  { border-left-color: #42a5f5 !important; }
    .decision-fraud    { border-left-color: #ff7043 !important; }

    /* Alert banners */
    .banner {
        border-radius: 8px;
        padding: 14px 20px;
        margin: 12px 0;
        font-weight: 600;
        font-size: 1rem;
    }
    .banner-escalate { background: #bf360c22; border: 1px solid #ff7043; color: #ff8a65; }
    .banner-fraud    { background: #e65100AA;  border: 1px solid #ff5722; color: #ffccbc; }
    .banner-ok       { background: #1b5e2022; border: 1px solid #66bb6a; color: #a5d6a7; }

    /* Response box */
    .response-box {
        background: #1e2130;
        border: 1px solid #3949ab;
        border-radius: 10px;
        padding: 20px 24px;
        font-size: 1rem;
        line-height: 1.7;
        color: #e8eaf6;
        white-space: pre-wrap;
    }

    /* History table */
    .history-row {
        background: #1e2130;
        border-radius: 8px;
        padding: 12px 16px;
        margin-bottom: 8px;
        border-left: 3px solid #5c6bc0;
        font-size: 0.9rem;
    }
    .history-row code { color: #80cbc4; font-size: 0.82rem; }

    /* Sidebar */
    .css-1d391kg { background-color: #13151f; }

    /* Submit button */
    .stButton > button {
        background: linear-gradient(135deg, #3949ab, #7b1fa2);
        color: white;
        border: none;
        border-radius: 8px;
        padding: 10px 28px;
        font-size: 1rem;
        font-weight: 600;
        width: 100%;
        cursor: pointer;
        transition: opacity 0.2s;
    }
    .stButton > button:hover { opacity: 0.85; }

    /* Retry Budget Monitor */
    .retry-banner {
        border-radius: 8px;
        padding: 10px 16px;
        margin: 8px 0;
        font-size: 0.88rem;
        font-weight: 600;
        border: 1px solid;
    }
    .retry-ok   { background:#1b3a1b; border-color:#66bb6a; color:#a5d6a7; }
    .retry-warn { background:#3a2a0a; border-color:#ffa726; color:#ffcc80; }
    .retry-dead { background:#3a0a0a; border-color:#ef5350; color:#ef9a9a; }

    .log-entry {
        font-family: 'Courier New', monospace;
        font-size: 0.78rem;
        padding: 6px 12px;
        border-radius: 6px;
        margin-bottom: 4px;
        border-left: 3px solid;
    }
    .log-retrying  { background:#1e2a1e; border-color:#66bb6a; color:#c8e6c9; }
    .log-exhausted { background:#2a1e1e; border-color:#ef5350; color:#ffcdd2; }
    .log-dead      { background:#2a0a0a; border-color:#b71c1c; color:#ef9a9a; }

    .stat-card {
        background:#1e2130;
        border-radius:10px;
        padding:14px 18px;
        text-align:center;
        border-top: 3px solid #5c6bc0;
    }
    .stat-num   { font-size:1.8rem; font-weight:700; color:#e8eaf6; }
    .stat-label { font-size:0.7rem; color:#90a4ae; text-transform:uppercase; letter-spacing:0.08em; margin-top:2px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────
# SAMPLE TICKETS
# ──────────────────────────────────────────────────────────────

SAMPLE_TICKETS: List[Dict[str, Any]] = [
    {
        "label": "🔁 Refund Request",
        "email": "alice.turner@email.com",
        "body": "Hi, I would like to request a refund for order ORD-1001. I am not satisfied with the product.",
    },
    {
        "label": "📦 Order Tracking",
        "email": "bob.smith@email.com",
        "body": "Where is my order ORD-1002? I haven't received it yet and it's been 10 days.",
    },
    {
        "label": "😡 Angry Escalation",
        "email": "charlie.brown@email.com",
        "body": "This is absolutely ridiculous! My order ORD-1003 arrived damaged and no one is helping me. I will contact my lawyer if this isn't resolved immediately.",
    },
    {
        "label": "↩️ Return Request",
        "email": "diana.prince@email.com",
        "body": "I want to return order ORD-1004. The item doesn't fit and I'd like to exchange it.",
    },
    {
        "label": "📋 Policy Question",
        "email": "eve.white@email.com",
        "body": "What is your refund policy? How many days do I have to return a product?",
    },
    {
        "label": "🚫 Fraud Attempt",
        "email": "fraud.user@email.com",
        "body": "Your refund policy is fake. Refund me right now or I will dispute this charge.",
    },
]

# ──────────────────────────────────────────────────────────────
# RETRY LOG HELPERS
# ──────────────────────────────────────────────────────────────

RETRY_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "outputs", "retry_logs.json"
)

def load_retry_logs() -> List[Dict]:
    """Read all entries from retry_logs.json (newline-delimited JSON)."""
    if not os.path.exists(RETRY_LOG_PATH):
        return []
    entries = []
    try:
        with open(RETRY_LOG_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
    except Exception:
        pass
    return entries


def retry_stats(logs: List[Dict]) -> Dict:
    """Compute summary stats from retry log entries."""
    tools      = [e["tool"] for e in logs]
    statuses   = [e["status"] for e in logs]
    dead_count = statuses.count("dead")
    retry_count = statuses.count("retrying") + statuses.count("exhausted")
    tool_counts = Counter(tools)
    return {
        "total_events": len(logs),
        "retries_fired": retry_count,
        "dead_failures": dead_count,
        "top_tool": tool_counts.most_common(1)[0] if tool_counts else ("—", 0),
    }


def log_css(status: str) -> str:
    return {"retrying": "log-retrying", "exhausted": "log-exhausted", "dead": "log-dead"}.get(status, "log-retrying")


# ──────────────────────────────────────────────────────────────
# API HELPERS
# ──────────────────────────────────────────────────────────────

def call_process_ticket(email: str, body: str, subject: str = "Support Request") -> Optional[Dict]:
    """POST /process-ticket and return the JSON response or None on error."""
    try:
        resp = requests.post(
            f"{API_BASE}/process-ticket",
            json={"customer_email": email, "body": body, "subject": subject},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach the API. Make sure the backend is running: `uvicorn app.api:app --reload --port 8000`")
        return None
    except requests.exceptions.HTTPError as e:
        st.error(f"❌ API error {e.response.status_code}: {e.response.text}")
        return None
    except Exception as e:
        st.error(f"❌ Unexpected error: {e}")
        return None


def call_customer_history(email: str) -> Optional[Dict]:
    """GET /customer-history/{email} and return JSON or None on error."""
    try:
        resp = requests.get(f"{API_BASE}/customer-history/{email}", timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def check_api_health() -> bool:
    """Return True if the backend is reachable."""
    try:
        resp = requests.get(f"{API_BASE}/health", timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────
# UI HELPERS
# ──────────────────────────────────────────────────────────────

def decision_css_class(decision: str) -> str:
    """Map decision string to a CSS class for colour-coding."""
    decision = decision.lower()
    if "approved" in decision:
        return "decision-approved"
    if "denied" in decision or "fraud" in decision or "error" in decision:
        return "decision-denied"
    if "escalate" in decision:
        return "decision-escalate"
    if "clarification" in decision or "clarify" in decision:
        return "decision-clarify"
    return ""


def sentiment_emoji(sentiment: str) -> str:
    return {"angry": "😡", "happy": "😊", "neutral": "😐"}.get(sentiment.lower(), "😐")


def intent_emoji(intent: str) -> str:
    return {
        "refund": "💸", "return": "↩️", "cancel": "❌",
        "tracking": "📦", "policy": "📋", "unknown": "❓",
    }.get(intent.lower(), "❓")


def render_metric(label: str, value: str, css_extra: str = "") -> None:
    st.markdown(
        f"""<div class="metric-card {css_extra}">
            <div class="metric-label">{label}</div>
            <div class="metric-value">{value}</div>
        </div>""",
        unsafe_allow_html=True,
    )


# ──────────────────────────────────────────────────────────────
# SIDEBAR
# ──────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🛍️ ShopWave Demo")
    st.markdown("---")

    # API status indicator
    api_ok = check_api_health()
    if api_ok:
        st.markdown("🟢 **API Connected**")
    else:
        st.markdown("🔴 **API Offline**")
        st.info("Start backend:\n```\nuvicorn app.api:app --reload --port 8000\n```")

    st.markdown("---")
    st.markdown("### 📋 Sample Tickets")
    st.markdown("Click a button to pre-fill the form:")

    for sample in SAMPLE_TICKETS:
        if st.button(sample["label"], use_container_width=True):
            st.session_state["prefill_email"] = sample["email"]
            st.session_state["prefill_body"] = sample["body"]
            st.rerun()

    st.markdown("---")
    st.markdown(
        """
        **Pipeline:**
        ```
        Ticket → LLM Analysis
               → Retry Budget
               → Tools (safe_call)
               → Decision
               → LLM Reply
               → Memory Save
               → UI Display
        ```
        """
    )
    st.markdown("**v2.0 · Retry Budget · Hackathon 2026**")


# ──────────────────────────────────────────────────────────────
# HERO BANNER
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <div class="hero-banner">
        <h1>🛒 ShopWave AI Support Agent</h1>
        <p>Production-style AI system · LLM · Memory · Escalation · Fraud Detection · <b>Retry Budget System</b></p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────
# INPUT PANEL
# ──────────────────────────────────────────────────────────────

col_input, col_output = st.columns([1, 1.6], gap="large")

with col_input:
    st.markdown("### ✍️ Submit a Ticket")

    default_email = st.session_state.get("prefill_email", "")
    default_body  = st.session_state.get("prefill_body", "")

    email = st.text_input(
        "Customer Email",
        value=default_email,
        placeholder="alice.turner@email.com",
        help="The customer's registered email address.",
    )

    subject = st.text_input(
        "Subject (optional)",
        value="",
        placeholder="e.g. Refund request for ORD-1001",
    )

    body = st.text_area(
        "Ticket Body",
        value=default_body,
        height=200,
        placeholder="Describe the customer's issue here...",
        help="The full text of the customer support ticket.",
    )

    submitted = st.button("🚀 Process Ticket", use_container_width=True)

    # Clear prefill after rendering so pressing the same sample again works
    if "prefill_email" in st.session_state:
        del st.session_state["prefill_email"]
        del st.session_state["prefill_body"]


# ──────────────────────────────────────────────────────────────
# OUTPUT PANEL
# ──────────────────────────────────────────────────────────────

with col_output:
    if submitted:
        if not email.strip() or not body.strip():
            st.warning("⚠️ Please fill in both the email and ticket body.")
        elif not api_ok:
            st.error("❌ API is offline. Start the backend first.")
        else:
            # Show a spinner while the agent processes the ticket
            with st.spinner("🤖 AI agent is processing the ticket…"):
                start_time = time.time()
                result = call_process_ticket(email.strip(), body.strip(), subject or "Support Request")
                elapsed = time.time() - start_time

            if result:
                analysis = result.get("analysis", {})
                decision = result.get("decision", "unknown")
                response_text = result.get("response", "")
                escalated = result.get("escalated", False)
                memory_saved = result.get("memory_saved", False)

                email_sent = result.get("email_sent", False)

                # ── STATUS BANNERS ────────────────────────────────────
                if escalated:
                    st.markdown(
                        '<div class="banner banner-escalate">⚠️ ESCALATED — This ticket has been sent to a specialist.</div>',
                        unsafe_allow_html=True,
                    )
                elif analysis.get("is_fraud"):
                    st.markdown(
                        '<div class="banner banner-fraud">🚫 FRAUD DETECTED — Request blocked by policy.</div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        '<div class="banner banner-ok">✅ Ticket processed successfully.</div>',
                        unsafe_allow_html=True,
                    )

                # ── ANALYSIS METRICS ─────────────────────────────────
                st.markdown("### 🔍 AI Analysis")
                mc1, mc2, mc3 = st.columns(3)

                intent_val    = analysis.get("intent", "unknown")
                sentiment_val = analysis.get("sentiment", "neutral")
                urgency_val   = analysis.get("urgency", "low")

                with mc1:
                    render_metric("Intent", f"{intent_emoji(intent_val)} {intent_val.upper()}")
                with mc2:
                    render_metric("Sentiment", f"{sentiment_emoji(sentiment_val)} {sentiment_val.capitalize()}")
                with mc3:
                    render_metric("Urgency", f"🔔 {urgency_val.capitalize()}")

                mc4, mc5, mc6, mc7 = st.columns(4)
                with mc4:
                    fraud_val = "🚫 YES" if analysis.get("is_fraud") else "✅ NO"
                    render_metric("Fraud", fraud_val)
                with mc5:
                    esc_val = "⚠️ YES" if escalated else "✅ NO"
                    css = "decision-escalate" if escalated else "decision-approved"
                    render_metric("Escalated", esc_val, css)
                with mc6:
                    mem_val = "💾 Saved" if memory_saved else "⚠️ Skipped"
                    render_metric("Memory", mem_val)
                with mc7:
                    email_val = "📧 Sent" if email_sent else "⚠️ Skipped"
                    render_metric("Email", email_val)

                # ── DECISION ─────────────────────────────────────────
                st.markdown("### 🎯 Decision")
                render_metric("Decision", decision.replace("_", " ").upper(), decision_css_class(decision))

                reason = result.get("reason", "")
                if reason:
                    st.caption(f"**Reason:** {reason}")

                # ── AI RESPONSE ──────────────────────────────────────
                st.markdown("### 💬 AI Response to Customer")
                st.markdown(
                    f'<div class="response-box">{response_text}</div>',
                    unsafe_allow_html=True,
                )

                # ── RAW ANALYSIS EXPANDER ────────────────────────────
                with st.expander("📊 Raw LLM Analysis (JSON)"):
                    st.json(analysis)

                # ── RETRY BUDGET INDICATOR ───────────────────────────
                fresh_logs = load_retry_logs()
                # Only show logs from the last ~10 seconds (this call)
                now_ts = time.time()
                recent = [
                    e for e in fresh_logs
                    if e.get("status") in ("retrying", "exhausted", "dead")
                ]
                # Show last N events that appeared during this request
                ticket_retries = recent[-10:] if recent else []

                if ticket_retries:
                    dead = any(e["status"] == "dead" for e in ticket_retries)
                    css_cls = "retry-dead" if dead else "retry-warn"
                    label   = "BUDGET EXHAUSTED on one or more tools" if dead else f"{len(ticket_retries)} retry event(s) fired"
                    st.markdown(
                        f'<div class="retry-banner {css_cls}">&#9889; RETRY SYSTEM: {label}</div>',
                        unsafe_allow_html=True,
                    )
                    with st.expander("🔁 Retry Events (this session)"):
                        for e in reversed(ticket_retries):
                            tool = e.get("tool", "?")
                            attempt = e.get("attempt", e.get("total_attempts", "?"))
                            err = e.get("error", e.get("last_error", ""))
                            ts  = e.get("timestamp", "")
                            st.markdown(
                                f'<div class="log-entry {log_css(e["status"])}">'  
                                f'[{ts}] &nbsp;<b>{tool}</b> &nbsp;| attempt {attempt} &nbsp;| {e["status"].upper()} &nbsp;| {err}'  
                                f'</div>',
                                unsafe_allow_html=True,
                            )
                else:
                    st.markdown(
                        '<div class="retry-banner retry-ok">&#10003; RETRY SYSTEM: All tools succeeded on first attempt</div>',
                        unsafe_allow_html=True,
                    )

                st.caption(f"⏱️ Processed in {elapsed:.2f}s · Ticket ID: {result.get('ticket_id', 'N/A')}")

    else:
        # Placeholder when nothing has been submitted yet
        st.markdown("### 📥 Waiting for Ticket")
        st.markdown(
            """
            <div style='color:#546e7a; padding: 60px 20px; text-align:center; font-size:1rem;'>
                <div style='font-size:3rem; margin-bottom:12px;'>🤖</div>
                Fill in the form and click <strong>Process Ticket</strong><br>
                or pick a sample from the sidebar.
            </div>
            """,
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────────────────────────
# CUSTOMER HISTORY PANEL (below main columns)
# ──────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### 🧠 Customer Interaction History")

history_email = st.text_input(
    "Look up history by email",
    value=email if submitted and email else "",
    placeholder="customer@example.com",
    key="history_email_input",
)

if history_email.strip():
    with st.spinner("Fetching history…"):
        hist_data = call_customer_history(history_email.strip())

    if hist_data is None:
        st.error("Could not fetch history — is the API running?")
    elif hist_data["total_interactions"] == 0:
        st.info(f"No prior interactions found for **{history_email}**.")
    else:
        st.success(f"Found **{hist_data['total_interactions']}** interaction(s) for **{history_email}**.")

        for item in reversed(hist_data["history"]):
            intent_i    = item.get("intent", "unknown")
            decision_i  = item.get("decision", "unknown")
            sentiment_i = item.get("sentiment", "neutral")
            escalated_i = item.get("escalation_status", "not_escalated") == "escalated"
            ts_i        = item.get("timestamp", "unknown")
            tid_i       = item.get("ticket_id", "—")
            reason_i    = item.get("reason", "")

            escalation_badge = " ⚠️ ESCALATED" if escalated_i else ""

            st.markdown(
                f"""<div class="history-row">
                    <code>{ts_i}</code> &nbsp;|&nbsp; <b>{tid_i}</b> &nbsp;|&nbsp;
                    {intent_emoji(intent_i)} {intent_i.upper()} &nbsp;→&nbsp;
                    <b>{decision_i.replace("_", " ").upper()}</b>
                    {escalation_badge} &nbsp;|&nbsp; {sentiment_emoji(sentiment_i)} {sentiment_i}
                    {"<br><small style='color:#90a4ae;'>" + reason_i + "</small>" if reason_i else ""}
                </div>""",
                unsafe_allow_html=True,
            )
else:
    st.caption("Enter an email above to view a customer's support history.")

# ──────────────────────────────────────────────────────────────
# RETRY BUDGET MONITOR (full panel)
# ──────────────────────────────────────────────────────────────

st.markdown("---")
st.markdown("### 🔁 Retry Budget Monitor")

all_logs = load_retry_logs()

if not all_logs:
    st.info("No retry events recorded yet. Run a ticket to generate data.")
else:
    stats = retry_stats(all_logs)

    # ── Stats row ──────────────────────────────────────────────
    sc1, sc2, sc3, sc4 = st.columns(4)
    with sc1:
        st.markdown(
            f'<div class="stat-card"><div class="stat-num">{stats["total_events"]}</div>'
            f'<div class="stat-label">Total Log Events</div></div>',
            unsafe_allow_html=True,
        )
    with sc2:
        color = "#ffa726" if stats["retries_fired"] > 0 else "#66bb6a"
        st.markdown(
            f'<div class="stat-card" style="border-top-color:{color}">'
            f'<div class="stat-num" style="color:{color}">{stats["retries_fired"]}</div>'
            f'<div class="stat-label">Retry Attempts</div></div>',
            unsafe_allow_html=True,
        )
    with sc3:
        color = "#ef5350" if stats["dead_failures"] > 0 else "#66bb6a"
        st.markdown(
            f'<div class="stat-card" style="border-top-color:{color}">'
            f'<div class="stat-num" style="color:{color}">{stats["dead_failures"]}</div>'
            f'<div class="stat-label">Dead Failures</div></div>',
            unsafe_allow_html=True,
        )
    with sc4:
        top_tool, top_count = stats["top_tool"]
        st.markdown(
            f'<div class="stat-card"><div class="stat-num" style="font-size:1rem;padding-top:6px">{top_tool}</div>'
            f'<div class="stat-label">Most Retried Tool ({top_count}x)</div></div>',
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Filter controls ────────────────────────────────────────
    fcol1, fcol2 = st.columns([1, 1])
    with fcol1:
        filter_status = st.selectbox(
            "Filter by status",
            ["all", "retrying", "exhausted", "dead"],
            key="retry_filter_status",
        )
    with fcol2:
        filter_tool = st.selectbox(
            "Filter by tool",
            ["all"] + sorted({e["tool"] for e in all_logs}),
            key="retry_filter_tool",
        )

    filtered = [
        e for e in reversed(all_logs)
        if (filter_status == "all" or e.get("status") == filter_status)
        and (filter_tool == "all" or e.get("tool") == filter_tool)
    ]

    st.markdown(f"**{len(filtered)} entries** matching filter:")

    # ── Log entries ────────────────────────────────────────────
    for e in filtered[:60]:   # cap at 60 rows for performance
        tool    = e.get("tool", "?")
        status  = e.get("status", "?")
        attempt = e.get("attempt", e.get("total_attempts", "?"))
        err     = e.get("error", e.get("last_error", ""))
        ts      = e.get("timestamp", "")
        st.markdown(
            f'<div class="log-entry {log_css(status)}">'
            f'<b>[{ts}]</b> &nbsp;'
            f'<b>{tool}</b> &nbsp;| &nbsp;'
            f'attempt&nbsp;{attempt} &nbsp;| &nbsp;'
            f'<b>{status.upper()}</b> &nbsp;| &nbsp;'
            f'{err}'
            f'</div>',
            unsafe_allow_html=True,
        )

    if st.button("Clear Retry Logs", key="clear_retry_logs"):
        try:
            open(RETRY_LOG_PATH, "w").close()
            st.success("Retry logs cleared.")
            st.rerun()
        except Exception as ex:
            st.error(f"Could not clear logs: {ex}")

# ──────────────────────────────────────────────────────────────
# FOOTER
# ──────────────────────────────────────────────────────────────

st.markdown(
    """
    <div style='text-align:center; color:#37474f; font-size:0.8rem; margin-top:48px; padding-top:16px; border-top: 1px solid #1e2130;'>
        ShopWave AI Support Agent · Retry Budget System · Hackathon 2026 · Built with FastAPI + Streamlit
    </div>
    """,
    unsafe_allow_html=True,
)
