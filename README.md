# ParcelPilot Support Agent

A customer-facing AI support chatbot for ParcelPilot, built for the CalQuity AI Engineer take-home assessment.

**Live app:** https://parcelpilot-support.streamlit.app/

## What this is

An agentic support chatbot that answers customer questions about shipments, cancellations, service credits, and account terms — using only the supplied policy documents, SOPs, and customer/order/ticket data. It:

- Retrieves and cites the correct policy/SOP/contract, respecting source precedence (signed agreement > current policy > product docs > historical tickets)
- Enforces account access control at both the tool layer and the database layer (Postgres Row-Level Security)
- Performs state-changing actions (cancel an order, issue a service credit, escalate a ticket, create a new ticket, add a note) only after explicit confirmation
- Proactively catches a mishandled historical ticket rather than repeating its incorrect resolution — the chosen "additional problem" from the assessment brief

See [`architecture-note.md`](./architecture-note.md), [`product-note.md`](./product-note.md), and [`ai-tools-note.md`](./ai-tools-note.md) for the full write-up, including bugs found and fixed during testing and ideas for future development.

## Stack

CrewAI (agent/tool orchestration) · OpenAI (`text-embedding-3-small` + chat model) · Neon Postgres with `pgvector` · Streamlit (UI + hosting)

## Repo contents

| File | Purpose |
|---|---|
| `app.py` | Streamlit chat UI |
| `agent.py` | Agent, tools, and system prompt |
| `load_data.py` | Loads the supplied xlsx (accounts/orders/tickets) into Postgres |
| `embed_docs.py` | Chunks, embeds, and loads the supplied PDFs into Postgres |
| `enable_rls.sql` | Row-Level Security policies (defense-in-depth access control) |
| `create_restricted_role.sql` | Creates the non-privileged DB role RLS requires |
| `additional_dummy_data.sql` | Extra test accounts/orders/tickets used during testing |
| `test_agent.py` | Manual smoke-test script (not an automated test suite — see `AGENTS.md`) |
| `01–06_*.pdf`, `ParcelPilot_Assessment_Data.xlsx` | Supplied source data |
| `AGENTS.md` | Working guidance for AI coding assistants on this repo |

## Running locally

```bash
python -m venv venv
venv\Scripts\Activate.ps1   # Windows; source venv/bin/activate on Mac/Linux
pip install -r requirements.txt

# Set environment variables
$env:DATABASE_URL="<your Postgres connection string>"
$env:OPENAI_API_KEY="<your OpenAI key>"

streamlit run app.py
```

Data setup (one-time, if starting from a fresh database): run the schema + `enable_rls.sql` + `create_restricted_role.sql` in your Postgres instance, then `python load_data.py` and `python embed_docs.py` to load the supplied data.

## Note on AI tool use

Built with Claude as a coding collaborator; see [`ai-tools-note.md`](./ai-tools-note.md) for what that did and didn't cover.
