# System Design — ShopWave AI Support Agent

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        USER INTERFACE                           │
│                   Streamlit  ·  ui/app.py                       │
│   [Ticket Form]  [Analysis Cards]  [Response Box]  [History]    │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP (REST)
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         API LAYER                               │
│                  FastAPI  ·  app/api.py                         │
│   POST /process-ticket                                          │
│   GET  /customer-history/{email}                                │
│   GET  /health                                                  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ function call
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       AGENT LAYER                               │
│                  app/agent.py  ·  process_ticket()              │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐    │
│  │ Memory Read  │  │ LLM Analysis │  │  Decision Engine   │    │
│  │ get_history()│  │ analyze_     │  │  (intent routing)  │    │
│  └──────┬───────┘  │ ticket()     │  └────────┬───────────┘    │
│         │          └──────┬───────┘           │                │
│         └──────────────────►──────────────────►                │
│                           │                   │                │
│                     ┌─────▼───────┐    ┌──────▼──────────┐    │
│                     │ Tool Layer  │    │  LLM Reply Gen  │    │
│                     │ app/tools.py│    │  generate_reply()│   │
│                     └─────┬───────┘    └──────┬──────────┘    │
│                           │                   │                │
│                     ┌─────▼───────────────────▼──────┐        │
│                     │      Memory Write               │        │
│                     │      save_interaction()         │        │
│                     └─────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Full Data Flow

```
Customer Ticket
      │
      ▼
[1] Memory Retrieval
    └─ get_history(email)
    └─ Returns prior tickets, escalations, repeated issues

      │
      ▼
[2] LLM Analysis  (app/llm.py → analyze_ticket)
    └─ Intent:      refund | return | cancel | tracking | policy | unknown
    └─ Order ID:    extracted from message (ORD-XXXX)
    └─ Sentiment:   happy | neutral | angry
    └─ Urgency:     low | medium | high
    └─ Fraud flag:  true | false
    └─ Escalation:  true | false
    └─ Summary:     one-line description

      │
      ▼
[3] Tool Execution  (app/tools.py)
    ├─ get_customer(email)           → verify customer exists
    ├─ get_order(order_id)           → fetch order details
    ├─ check_refund_eligibility()    → return window / VIP rules / damage
    ├─ issue_refund()                → mark order as refunded
    ├─ escalate()                    → flag for human review
    └─ search_knowledge_base()       → policy lookup

      │
      ▼
[4] Decision Engine  (agent.py logic)
    ├─ fraud_blocked
    ├─ refund_approved / refund_denied
    ├─ return_approved / return_denied
    ├─ cancel_approved
    ├─ tracking_update
    ├─ policy_answer
    ├─ escalate
    └─ ask_clarification

      │
      ▼
[5] LLM Reply Generation  (app/llm.py → generate_reply)
    └─ Personalised with: name, intent, decision, reason, sentiment,
       tier, history summary, prior escalations, repeated issue count

      │
      ▼
[6] Memory Save  (app/memory.py → save_interaction)
    └─ Persists to outputs/memory_store.json

      │
      ▼
[7] Structured Response  (returned to API → UI)
    └─ { ticket_id, analysis, decision, reason, response, escalated, memory_saved }
```

---

## 3. Component Breakdown

### 3.1 LLM Layer — `app/llm.py`

| Function | Purpose |
|----------|---------|
| `analyze_ticket(text)` | Extract intent, sentiment, urgency, fraud flag, escalation signal |
| `generate_reply(context)` | Write a personalised, empathetic reply |
| `_heuristic_analysis(text)` | Offline fallback (regex-based) when no API key |
| `_fallback_reply(context)` | Offline fallback reply generator |

The module works **with or without** an OpenAI API key. Without a key it uses
the built-in heuristic engine so demos always work even offline.

### 3.2 Tool Layer — `app/tools.py`

The tool layer simulates a real production backend. It includes:
- **Random failures** (10% timeout, 10% malformed) to demonstrate resilience.
- **Retry logic** in the agent via `safe_call()`.
- **Business rules**: VIP extended returns, damage claims, non-returnable products.

### 3.3 Memory Layer — `app/memory.py`

| Function | Description |
|----------|-------------|
| `get_history(email)` | Return past interactions (oldest first) |
| `save_interaction(email, data)` | Append record and persist to JSON |
| `format_history_for_llm(history)` | Render history as a text block for the LLM |
| `clear_history(email)` | Remove one customer's records |
| `clear_all_memory()` | Wipe entire store (useful for tests) |

**Storage**: `outputs/memory_store.json`  
**Limit**: last 10 interactions per customer (configurable)  
**Persistence**: survives server restarts

### 3.4 Agent Layer — `app/agent.py`

Orchestrates the full pipeline. Every code path returns:

```python
{
  "ticket_id":    str,
  "analysis":     dict,   # LLM analysis output
  "decision":     str,    # e.g. "refund_denied"
  "reason":       str,
  "response":     str,    # customer-facing reply
  "escalated":    bool,
  "memory_saved": bool,
}
```

### 3.5 API Layer — `app/api.py`

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Liveness check |
| `POST` | `/process-ticket` | Run the full agent pipeline |
| `GET` | `/customer-history/{email}` | Retrieve customer memory |

Built with **FastAPI** + **Pydantic** for automatic validation, OpenAPI docs
at `/docs`, and CORS headers for the Streamlit UI.

### 3.6 UI Layer — `ui/app.py`

Built with **Streamlit**. Features:
- Dark-mode theme with gradient banner
- 6 sample ticket buttons (one-click demo)
- Color-coded metric cards (green = approved, red = denied, orange = escalated)
- Escalation and fraud alert banners
- Raw JSON analysis expander
- Customer history panel with visual timeline
- API health indicator in the sidebar

---

## 4. Why This Architecture Is Scalable

| Concern | Current (hackathon) | Production path |
|---------|---------------------|-----------------|
| Storage | JSON file | Replace `load_memory` / `save_memory` with PostgreSQL / Redis |
| LLM | GPT-4o-mini / heuristic | Swap model in `app/config.py`; add streaming |
| API | Single FastAPI process | Add workers: `uvicorn --workers 4`; add rate limiting |
| UI | Streamlit | Replace with React + TypeScript frontend |
| Tool calls | Simulated with random failures | Connect to real order management system |
| Auth | None | Add JWT middleware to FastAPI |

The key design decision is that **each layer only knows about the layer
below it** (UI → API → Agent → Tools / LLM / Memory). Replacing any one
component does not break the others.

---

## 5. Running the System

### Install dependencies
```bash
pip install -r requirements.txt
```

### Start the backend API (Terminal 1)
```bash
uvicorn app.api:app --reload --port 8000
```

- Swagger UI: http://localhost:8000/docs
- Health check: http://localhost:8000/health

### Start the Streamlit UI (Terminal 2)
```bash
streamlit run ui/app.py
```

- Opens at: http://localhost:8501

---

## 6. API Reference

### `POST /process-ticket`

**Request body:**
```json
{
  "customer_email": "alice.turner@email.com",
  "body": "I want a refund for order ORD-1001",
  "subject": "Refund request",
  "source": "web"
}
```

**Response:**
```json
{
  "ticket_id": "TKT-A1B2C3",
  "analysis": {
    "intent": "refund",
    "order_id": "ORD-1001",
    "sentiment": "neutral",
    "urgency": "medium",
    "is_fraud": false,
    "requires_escalation": false,
    "summary": "Customer requested refund support for ORD-1001."
  },
  "decision": "refund_denied",
  "reason": "Return window expired",
  "response": "Hi Alice, I'm unable to approve the refund because the return window has expired...",
  "escalated": false,
  "memory_saved": true
}
```

### `GET /customer-history/{email}`

**Response:**
```json
{
  "email": "alice.turner@email.com",
  "total_interactions": 2,
  "history": [
    {
      "ticket_id": "TKT-001",
      "intent": "refund",
      "decision": "refund_denied",
      "reason": "Return window expired",
      "sentiment": "neutral",
      "escalation_status": "not_escalated",
      "timestamp": "2026-04-19T10:00:00Z"
    }
  ]
}
```

---

## 7. Future Improvements

1. **Streaming replies** — Stream the LLM response token-by-token to the UI
   for a more interactive feel.
2. **Authentication** — Add JWT tokens to protect the API in production.
3. **Database persistence** — Replace the JSON memory store with PostgreSQL
   for multi-instance deployments.
4. **Analytics dashboard** — Track decision distribution, escalation rate, and
   sentiment trends over time.
5. **Multi-language support** — Detect ticket language and reply in kind.
6. **Webhook integration** — POST results to a real ticketing system
   (Zendesk, Freshdesk) instead of printing to stdout.
7. **A/B testing** — Route a fraction of tickets to different LLM prompts and
   compare reply quality.

---

## 8. File Structure

```
KSolvees Hack/
├── app/
│   ├── __init__.py
│   ├── agent.py          # Orchestration + decision engine
│   ├── api.py            # FastAPI endpoints          ← Step 7 NEW
│   ├── config.py         # Paths, API keys
│   ├── data_loader.py    # JSON dataset loader
│   ├── llm.py            # LLM calls + heuristic fallback
│   ├── memory.py         # Interaction memory layer    ← Step 6
│   ├── schemas.py        # Pydantic data models
│   ├── test_agent.py     # Agent integration tests
│   ├── test_memory.py    # Memory layer tests          ← Step 6
│   └── tools.py          # Simulated backend tools
│
├── data/
│   ├── customers.json
│   ├── orders.json
│   ├── products.json
│   └── tickets.json
│
├── docs/
│   ├── failure_modes.md
│   ├── memory_layer.md   # Memory architecture         ← Step 6
│   └── system_design.md  # This document              ← Step 7 NEW
│
├── outputs/
│   └── memory_store.json # Persistent memory (auto-created)
│
├── ui/
│   └── app.py            # Streamlit UI               ← Step 7 NEW
│
├── requirements.txt       # Updated with Step 7 deps  ← Step 7 UPDATED
└── README.md
```
