ShopWave AI Support Agent - Architecture Documentation
================================================================================

1. PROJECT OVERVIEW
--------------------------------------------------------------------------------
A production-ready AI-powered customer support system for ShopWave e-commerce.
Processes support tickets end-to-end:
- LLM-powered analysis (intent, sentiment, fraud, escalation)
- Tool execution (customer/order lookup, refunds, escalations)
- Decision engine (approve/deny/clarify/escalate)
- Personalized replies + memory persistence
- Automatic email notifications on resolution

Key Features:
* Offline-capable (heuristic fallbacks, no OpenAI key required)
* Resilience: Retry budgets, DLQ, non-crashing email
* Memory: Per-customer interaction history (JSON store)
* UI: Streamlit dashboard with history/timeline
* API: FastAPI with OpenAPI docs (/docs)
* Testing: pytest suite (agent, data, memory)

2. ARCHITECTURE DIAGRAM (ASCII)
--------------------------------------------------------------------------------
                           +-------------------+
                           |    Streamlit UI   |
                           |   ui/app.py       |
                           +---------+---------+
                                     |
                              HTTP/REST
                                     |
                           +---------v---------+
                           |    FastAPI API    |
                           |  app/api.py       |
                           | /process-ticket   |
                           +---------+---------+
 s                            | function call
                                     |
                           +---------v---------+
                           |     AGENT         |
                           |  app/agent.py     |
                           | process_ticket()  |
                           +---------+---------+
                                    / | \
                                   /  |  \
                                  /   |   \
                       +---------+  +v+  +---------+
                       | LLM    |  |Tools| |Memory  |
                       |llm.py  |  |     | |memory.py|
                       +---------+  +----+ +---------+
                                   tools.py
                                       |
                                 Data JSONs
                              data/*.json

3. DATA FLOW (Ticket Processing Pipeline)
--------------------------------------------------------------------------------
1. API receives ticket (email, body)
2. Memory read: get_history(email) -> prior interactions/escalations
3. LLM analysis: analyze_ticket() -> {intent, order_id, sentiment, fraud?, escalate?}
4. Tool execution (retry-wrapped):
   - get_customer(email)
   - get_order(order_id) [if present]
   - check_refund_eligibility() [refund/return]
5. Decision routing:
   | Fraud -> block
   | Escalate (VIP/high-value/angry) -> escalate()
   | Refund/Return -> check/issue
   | Cancel/Tracking/Policy -> handle
   | Unknown -> ask_clarification
6. LLM reply: generate_reply(context w/ history/tier/sentiment)
7. send_reply(ticket_id, reply)
8. Memory save: save_interaction()
9. Email: generate_email_content() -> send_email() [fire-and-forget]
10. Return: {analysis, decision, reason, response, escalated, memory_saved, email_sent}

Every path returns structured dict; failures -> DLQ + safe message.

4. COMPONENT BREAKDOWN
--------------------------------------------------------------------------------
Component      | Files                  | Purpose
---------------|------------------------|---------------------------------
UI             | ui/app.py             | Streamlit: forms, metrics, history
API            | app/api.py            | FastAPI endpoints + Pydantic
Agent          | app/agent.py          | Orchestrator/decision engine
LLM            | app/llm.py            | Prompts + heuristics (fallback)
Tools          | app/tools.py          | Backend sim (20% failures for testing)
Memory         | app/memory.py         | JSON store: get/save/format history
Email          | app/email_service.py  | SMTP delivery (Gmail/etc.)
Data           | data/*.json, data_loader.py | Datasets + pydantic validation
Config         | app/config.py         | dotenv paths/OpenAI/EMAIL_*
Resilience     | retry.py, dlq.py      | safe_call(retries), DLQ logging
Tests          | tests/, app/test_*.py | pytest: agent/email/data

5. KEY DESIGN DECISIONS & RESILIENCE
--------------------------------------------------------------------------------
- Layered: UI->API->Agent->(LLM/Tools/Memory) [easy to swap]
- Resilience:
  * Tools: safe_call() - 3 retries + exp backoff
  * DLQ: log_to_dlq() on exhaustion/critical errors
  * Email: fire-and-forget (logs failures, never crashes)
  * LLM: heuristic fallback (regex/rules when no API key)
- Memory: outputs/memory_store.json (last 10/customer)
- Scalability: JSON->PostgreSQL/Redis path; add workers/auth
- Testing: 100% offline/mocked; covers email edge cases

6. FILE STRUCTURE
--------------------------------------------------------------------------------
d:/KSolvees Hack/
├── app/                 # Core Python package
│   ├── __init__.py
│   ├── agent.py        # Orchestrator
│   ├── api.py          # FastAPI
│   ├── config.py       # Env/paths
│   ├── data_loader.py
│   ├── dlq.py
│   ├── email_service.py
│   ├── llm.py
│   ├── logger.py
│   ├── main.py         # Data smoke-test
│   ├── memory.py
│   ├── retry.py
│   ├── schemas.py      # Pydantic
│   ├── tools.py
│   └── utils.py
├── data/               # JSON datasets
│   ├── customers.json
│   ├── orders.json
│   ├── products.json
│   └── tickets.json
├── docs/               # Markdown docs
│   ├── architecture.png
│   ├── failure_modes.md
│   ├── memory_layer.md
│   └── system_design.md
├── outputs/            # Runtime (memory_store.json auto-created)
├── tests/              # pytest
│   ├── test_agent.py
│   └── test_data_loader.py
├── ui/                 # Streamlit
│   └── app.py
├── requirements.txt    # 114 deps (fastapi, openai, streamlit, pytest...)
├── Dockerfile
├── sample.env          # Template
├── README.md           # Setup guide
├── README.txt          # This file
└── TODO.md

7. QUICKSTART
--------------------------------------------------------------------------------
# Install
pip install -r requirements.txt

# Copy env template
cp sample.env .env
# Edit .env: OPENAI_API_KEY (opt), EMAIL_USER/PASSWORD (for notifications)

# Backend API
uvicorn app.api:app --reload  # http://localhost:8000/docs

# Frontend
streamlit run ui/app.py       # http://localhost:8501

# Tests
pytest tests/ -v

# Data check
python app/main.py

8. API REFERENCE
--------------------------------------------------------------------------------
POST /process-ticket
- Body: {customer_email, body, subject?, ticket_id?}
- Returns: {ticket_id, analysis, decision, reason, response, escalated, memory_saved, email_sent}

GET /customer-history/{email}
- Returns: {email, total_interactions, history[]}

GET /health -> {"status": "ok"}

Ext: http://localhost:8000/docs (Swagger)

Future: Streaming, auth (JWT), DB, webhooks (Zendesk), multi-lang.

Generated by BLACKBOXAI. Diagram prompt with full tech stack: prompts/architecture_diagram_prompt.txt (copy to Midjourney/DALL-E/Draw.io for PNG/PDF).

