"""
api.py — FastAPI REST layer for the ShopWave AI Support Agent
=============================================================

Endpoints:
    GET  /health                      → system liveness check
    POST /process-ticket              → run the full agent pipeline
    GET  /customer-history/{email}    → retrieve memory for one customer

Run with:
    uvicorn app.api:app --reload --port 8000

Interactive docs:
    http://localhost:8000/docs
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent import process_ticket
from app.memory import get_history

# ──────────────────────────────────────────────────────────────
# APP SETUP
# ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="ShopWave AI Support Agent",
    description=(
        "A production-style AI customer support system with LLM analysis, "
        "tool execution, fraud detection, escalation logic, and memory."
    ),
    version="1.0.0",
)

# Allow the Streamlit UI (running on a different port) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ──────────────────────────────────────────────────────────────
# REQUEST / RESPONSE SCHEMAS
# ──────────────────────────────────────────────────────────────

class TicketRequest(BaseModel):
    """
    Incoming ticket payload.

    All fields except ``customer_email`` and ``body`` are optional and will
    be filled with sensible defaults so the UI can send minimal payloads.
    """
    ticket_id: Optional[str] = Field(
        default=None,
        description="Auto-generated if not supplied.",
        examples=["TKT-001"],
    )
    customer_email: str = Field(..., examples=["alice.turner@email.com"])
    subject: Optional[str] = Field(default="Support Request", examples=["Refund issue"])
    body: str = Field(..., examples=["I want a refund for order ORD-1001."])
    source: Optional[str] = Field(default="api", examples=["web", "email", "chat"])
    created_at: Optional[str] = Field(default=None)


class AnalysisOutput(BaseModel):
    intent: str
    order_id: Optional[str]
    sentiment: str
    urgency: str
    is_fraud: bool
    requires_escalation: bool
    summary: str


class ProcessTicketResponse(BaseModel):
    """Structured response returned after processing a ticket."""
    ticket_id: str
    analysis: Dict[str, Any]
    decision: str
    reason: str
    response: str
    escalated: bool
    memory_saved: bool


class HealthResponse(BaseModel):
    status: str
    service: str


class HistoryItem(BaseModel):
    ticket_id: str
    intent: str
    decision: str
    reason: str
    sentiment: str
    escalation_status: str
    timestamp: str
    order_id: Optional[str] = None
    reply: Optional[str] = None


class CustomerHistoryResponse(BaseModel):
    email: str
    total_interactions: int
    history: List[Dict[str, Any]]


# ──────────────────────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────────────────────

@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["System"],
)
def health_check() -> HealthResponse:
    """
    Quick liveness probe.  Returns 200 OK when the service is ready.
    """
    return HealthResponse(status="ok", service="ShopWave AI Support Agent")


@app.post(
    "/process-ticket",
    response_model=ProcessTicketResponse,
    summary="Process a support ticket",
    tags=["Agent"],
)
def api_process_ticket(request: TicketRequest) -> ProcessTicketResponse:
    """
    Run the full AI agent pipeline on the submitted ticket.

    The pipeline steps are:
    1. Retrieve customer memory (prior interactions)
    2. LLM analysis — intent, sentiment, fraud, escalation signals
    3. Tool execution — customer lookup, order lookup, refund eligibility
    4. Decision engine — approve / deny / escalate / clarify
    5. LLM reply generation — context-aware, personalised
    6. Memory save — persist this interaction for future tickets
    """
    # Build a ticket dict that the agent expects.
    ticket: Dict[str, Any] = {
        "ticket_id": request.ticket_id or f"TKT-{uuid.uuid4().hex[:6].upper()}",
        "customer_email": request.customer_email.strip().lower(),
        "subject": request.subject or "Support Request",
        "body": request.body,
        "source": request.source or "api",
        "created_at": request.created_at or "",
    }

    try:
        result = process_ticket(ticket)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Agent error: {exc}") from exc

    return ProcessTicketResponse(**result)


@app.get(
    "/customer-history/{email}",
    response_model=CustomerHistoryResponse,
    summary="Get customer interaction history",
    tags=["Memory"],
)
def api_customer_history(email: str) -> CustomerHistoryResponse:
    """
    Retrieve all stored interactions for a customer email.

    Returns an empty list (not 404) when the customer has no history so
    the UI can display a "no history" message gracefully.
    """
    normalized = email.strip().lower()
    history = get_history(normalized)

    return CustomerHistoryResponse(
        email=normalized,
        total_interactions=len(history),
        history=history,
    )
