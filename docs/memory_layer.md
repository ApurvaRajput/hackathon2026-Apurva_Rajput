# Memory Layer — ShopWave AI Support Agent

## 1. Purpose

A standard stateless AI agent treats every ticket as if it were the first
contact. That means:

- It cannot notice that a customer asked about the same issue before.
- It cannot tell when someone has been escalated multiple times.
- It generates the same generic opener every time.

The **memory layer** fixes this by giving the agent a running log of every
interaction it has completed. Before generating a reply the agent reads the
customer's history and passes it to the LLM. This produces replies that:

- Acknowledge past contact ("I can see you reached out to us before...")
- Notice repeated issues ("This is the second time you've contacted us about a refund...")
- Sound more empathetic after a prior escalation
- Feel personal rather than robotic

---

## 2. Design

### Storage format

Memory is stored in a single JSON file:

```
outputs/memory_store.json
```

The file is a dict keyed by customer e-mail address (lowercase). Each value
is an ordered list of interaction records — oldest first.

```json
{
  "alice.turner@email.com": [
    {
      "ticket_id":         "TKT-001",
      "intent":            "refund",
      "decision":          "refund_denied",
      "reason":            "Return window expired",
      "reply":             "Hi Alice, I'm unable to approve the refund...",
      "sentiment":         "neutral",
      "order_id":          "ORD-1001",
      "escalation_status": "not_escalated",
      "timestamp":         "2026-04-19T10:00:00Z"
    },
    {
      "ticket_id":         "TKT-003",
      "intent":            "refund",
      "decision":          "escalate",
      "reason":            "Repeated refund issue; sent to specialist.",
      "reply":             "Hi Alice, your case has been escalated...",
      "sentiment":         "angry",
      "order_id":          "ORD-1001",
      "escalation_status": "escalated",
      "timestamp":         "2026-04-19T12:00:00Z"
    }
  ]
}
```

### Why JSON and not a database?

- Zero setup — no connection strings, no migrations.
- Human-readable for demos.
- The agent only handles a few hundred customers in this hackathon context.
- Switching to SQLite or Redis later requires only replacing the read/write
  functions in `memory.py`.

### Caching

An in-memory Python dict (`_memory_cache`) is used as the primary store while
the agent is running. The JSON file is read **once** and cached. Every write
flushes the cache to disk immediately. This keeps the module simple and fast
without introducing a dependency on a database.

```
First load     ─► read JSON file ─► populate _memory_cache
Every save     ─► update _memory_cache + write JSON file
get_history()  ─► read from _memory_cache (no disk access)
```

### Record limit

Each customer is capped at **10 interactions** (configurable via
`MAX_HISTORY_PER_CUSTOMER`). Older entries are pruned automatically so the
file never grows without bound.

---

## 3. Workflow

```
Ticket received
     │
     ▼
get_history(email)          ← read past records from memory_store.json
     │
     ▼
analyze_ticket(text)        ← LLM / heuristic: intent, sentiment, fraud, etc.
     │
     ▼
format_history_for_llm()    ← render history as a short text block
     │
     ▼
build_reply_context()       ← merge ticket analysis + history context
     │
     ▼
generate_reply(context)     ← LLM writes a personalised reply
     │
     ▼
send_reply()                ← deliver reply to the customer
     │
     ▼
save_interaction()          ← append record to memory and flush to disk
```

---

## 4. Files Added / Changed

| File | Status | What changed |
|------|--------|--------------|
| `app/memory.py` | **Added / Rewritten** | Complete memory module with all public API functions, caching, persistence, and LLM helper |
| `app/agent.py` | **Unchanged** | Already integrated — imports `get_history`, `save_interaction`, `format_history_for_llm` |
| `app/llm.py` | **Unchanged** | Already uses all memory context fields in `PROMPT_GENERATE_REPLY` and `_fallback_reply()` |
| `app/test_memory.py` | **Added / Rewritten** | 10 test sections with assertions, edge cases, and live LLM reply demo |
| `docs/memory_layer.md` | **Added** | This document |

---

## 5. Public API Reference

All functions live in `app/memory.py`.

### `load_memory(force_reload=False) → dict`

Load the full memory store. Cached after the first call. Pass
`force_reload=True` to read the file again (useful in tests).

### `save_memory(memory=None) → dict`

Persist the given memory dict to disk. If `memory` is `None` the current
cache is flushed back unchanged.

### `get_history(email, limit=None) → list`

Return past interactions for one customer. Returns `[]` for unknown
customers (no errors, no crashes). Pass `limit=N` to get only the most
recent N records.

### `save_interaction(email, interaction, max_items=10) → list`

Append one interaction record and persist to disk. Automatically:
- Adds a UTC timestamp if one is not provided.
- Prunes to `max_items` records.

### `clear_history(email) → dict`

Delete all records for a single customer. Other customers are not affected.

### `clear_all_memory() → dict`

Wipe the entire store (file + cache). Useful at the start of tests.

### `format_history_for_llm(history, max_items=3) → str`

Format the customer's last `max_items` interactions as a readable text block
ready to be inserted into the LLM prompt. Returns `"No prior support
history."` for new customers.

---

## 6. How Memory Improves the Agent

### Without memory
```
Customer: "This is the third time I'm asking about a refund!"
Agent:    "Hi Alice, I'm unable to approve the refund because the return
           window has expired. Please let us know if we can help further."
```
The reply is correct but tone-deaf. It sounds like a first contact.

### With memory
The agent detects:
- `repeated_issue_count = 2` (two previous refund tickets)
- `prior_escalations = 1` (one earlier escalation)
- `sentiment = "angry"`

The LLM is given all this context and produces:
```
Hi Alice, I'm truly sorry for the repeated frustration — I can see you've
reached out to us about this refund before. I understand how stressful this
must be. I've escalated your case to a specialist who will be in touch with
you as soon as possible. Thank you for your patience.
```

---

## 7. Testing

### Run the memory demo

From the project root:

```bash
python -m app.test_memory
```

### What the test suite covers

| # | Test | Description |
|---|------|-------------|
| 1 | Empty history | New customer returns `[]` and sentinel text |
| 2 | Save + retrieve | Three records saved and retrieved in order |
| 3 | JSON persistence | Force-reload from disk confirms data survived |
| 4 | Limit parameter | `get_history(limit=2)` returns only last 2 records |
| 5 | Repeated issue detection | Counts refund and escalation records correctly |
| 6 | LLM history formatting | `format_history_for_llm()` output is correct |
| 7 | History-aware reply | Full reply generation demo with all context fields |
| 8 | `clear_history()` | Clears one customer without affecting others |
| 9 | `clear_all_memory()` | Completely empties the store |
| 10 | `save_memory()` round-trip | Explicit dict survives a force-reload |

Expected output ends with:

```
All memory layer tests PASSED.
```

---

## 8. Example — Full Interaction Lifecycle

### Step 1 — Alice's first ticket (no history)

**Ticket:**
> Hi, I want a refund for order ORD-1001.

**History retrieved:** `[]`

**LLM context:**
- `history_summary`: `"No prior support history."`
- `repeated_issue_count`: `0`
- `prior_escalations`: `0`

**Reply generated:**
> Hi Alice, I'm sorry to hear you'd like to return your order. Unfortunately
> the return window for ORD-1001 has expired, so we're unable to process a
> refund at this time. If you have any other questions, we're happy to help.

**Record saved to memory:**
```json
{
  "ticket_id":         "TKT-001",
  "intent":            "refund",
  "decision":          "refund_denied",
  "reason":            "Return window expired",
  "sentiment":         "neutral",
  "escalation_status": "not_escalated",
  "timestamp":         "2026-04-19T10:00:00Z"
}
```

---

### Step 2 — Alice contacts support again (history present)

**Ticket:**
> I asked about this refund before and I'm very unhappy. This is completely
> unacceptable. I need this resolved immediately.

**History retrieved:**
```
[TKT-001 | intent=refund | decision=refund_denied | escalation=not_escalated]
```

**LLM context:**
- `history_summary`: previous refund denial
- `repeated_issue_count`: `1`
- `prior_escalations`: `0`
- `sentiment`: `"angry"`

**Reply generated:**
> Hi Alice, I sincerely apologise for the frustration — I can see you
> contacted us about this refund before. I completely understand how
> upsetting this must be. I've escalated your case to a senior specialist
> who will review it personally and follow up with you as soon as possible.
> Thank you for your patience.

**Record saved to memory:**
```json
{
  "ticket_id":         "TKT-003",
  "intent":            "refund",
  "decision":          "escalate",
  "reason":            "Repeated refund issue — escalated to specialist.",
  "sentiment":         "angry",
  "escalation_status": "escalated",
  "timestamp":         "2026-04-19T12:00:00Z"
}
```

---

## 9. Configuration

| Constant | Default | Where |
|----------|---------|-------|
| `MEMORY_FILE` | `outputs/memory_store.json` | `app/memory.py` |
| `MAX_HISTORY_PER_CUSTOMER` | `10` | `app/memory.py` |
| LLM history window | last `3` interactions | `format_history_for_llm(max_items=3)` |
| Agent recent history | last `3` interactions | `build_reply_context()` in `agent.py` |

---

## 10. Extending the Memory Layer

If you want to go beyond the hackathon:

- **Swap JSON for SQLite** — Replace `load_memory()` / `save_memory()` with
  SQLite reads/writes. The public API stays the same.
- **Add TTL / expiry** — Filter records older than N days in `get_history()`.
- **Sentiment trends** — Count negative sentiments over the last 5 tickets to
  flag customers at risk of churning.
- **Cross-channel memory** — Store channel (email / chat / phone) per record
  so agents can reference "your chat last week".
