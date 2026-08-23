# ParcelPilot support agent guidance

## Project intent

This repository is a hiring-assessment implementation of a customer-facing ParcelPilot support agent. Preserve the assessment's core requirements: natural-language chat, document retrieval, structured-data lookup, state-changing actions, tool transparency, customer data isolation, and explicit confirmation before mutations.

The supplied PDFs, workbook, and assessment document are the domain source of truth. Do not hard-code answers for the example IDs; implementations and tests must work across the supplied records.

## Repository map

- `app.py`: Streamlit customer chat UI and conversation state.
- `agent.py`: CrewAI agent, source-precedence prompt, and the three tool families.
- `embed_docs.py`: PDF extraction, chunking, embedding, and document ingestion.
- `load_data.py`: workbook-to-Postgres loading for accounts, orders, and tickets.
- `01_*.pdf` through `06_*.pdf`: policies, SOP, product guidance, and customer agreements.
- `ParcelPilot_Assessment_Data.xlsx`: synthetic account, order, and ticket data.
- `test_agent.py`: live smoke script; it is not an isolated automated test suite.

## Domain invariants

Apply source authority in this order:

1. The signed agreement for the relevant customer account.
2. Current support policy or current SOP.
3. Current product documentation and known-issue guidance.
4. Historical tickets and resolutions as context only.

Never use a document marked `DEPRECATED` as current guidance. When sources conflict, state which source controls and why. Use `2026-08-16 11:00 Asia/Kolkata`, from the workbook README, for snapshot-based time calculations.

Keep policy decisions deterministic where practical. Retrieval may supply evidence, but code should enforce access control, action eligibility, approval thresholds, confirmation, and other safety-critical rules.

## Security and action safety

- Enforce customer account scoping in SQL or the tool layer, never only in the model prompt or UI.
- Do not reveal whether another customer's entity exists. Cross-account missing and denied responses should not enable ID enumeration.
- Treat internal mode as privileged and add role checks before exposing it through an interface.
- Never mutate state from an unverified entity ID. Verify existence, account ownership, entity type, and current status immediately before the mutation.
- Require a server-side pending-action record or confirmation token for production-style flows. A model-supplied `confirmed=True` flag alone is not a sufficient trust boundary.
- Make mutations idempotent and auditable. Report success only when the literal tool result confirms the committed change.
- Validate service-credit eligibility, amount, contractual override, monthly cap, and manager-approval threshold in code before recording a credit.
- Keep database URLs and API keys in environment variables or Streamlit secrets. Never commit `.env` or `.streamlit/secrets.toml`.
- The current actions are mocked in the assessment database. Keep that limitation explicit in code and user-facing copy.

## Local development

Use Python 3.12.

```text
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
streamlit run app.py
```

The app requires `DATABASE_URL` and `OPENAI_API_KEY`. Do not run live smoke tests or ingestion scripts unless those services are intentionally in scope; they can incur API usage and change the shared assessment database.

## Testing expectations

New behavior should be covered by automated `pytest` tests with injected or mocked database and OpenAI dependencies. Default tests must not require network access, paid API calls, or a shared database.

At minimum, cover:

- contract overrides, current-vs-deprecated policy, and known-issue precedence;
- exact account isolation for single-record and list queries;
- no mutation before confirmation, ambiguous confirmation handling, replay/idempotency, and tool-failure truthfulness;
- cancellation boundaries for `BOOKED`, `PICKED_UP`, and `DELIVERED` orders;
- default and customer-specific service-credit thresholds, caps, and approval rules;
- snapshot-time, timezone, and exact-threshold calculations;
- KI-208 and KI-211 behavior, including incorrect historical resolutions;
- empty retrieval, low relevance, malformed data, database errors, API timeouts, and concurrent status changes.

Before handing off a change, run the relevant isolated tests and at least a syntax check such as:

```text
python -m py_compile agent.py app.py embed_docs.py load_data.py
python -m pytest -q
```

If live end-to-end tests were not run, say so explicitly.

## Change discipline

- Keep SQL parameterized and close or roll back connections reliably.
- Make ingestion rerunnable without duplicating documents or silently ignoring source updates.
- Pin or constrain production dependencies to avoid deployment drift.
- Prefer structured tool results and typed fields over stringified rows and free-form action details.
- Preserve tool-use visibility in the UI, but do not expose secrets, hidden reasoning, or unnecessary customer data.
- Update setup, architecture, product decisions, and test instructions when behavior changes.
