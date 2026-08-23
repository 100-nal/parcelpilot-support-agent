# ParcelPilot Support Agent — Architecture Note

## Agent design
A single CrewAI agent (not a multi-agent crew) with native tool-calling, backed by an OpenAI chat model. One agent was enough because the workflow is fundamentally linear per request — retrieve context, look up data, optionally act — rather than needing specialized agents to collaborate. The agent's system prompt encodes source precedence, access-control expectations, and a growing set of explicit behavioral rules added in response to bugs found during testing (see below). Conversation history is passed back into each turn as plain-text context, which is what lets multi-turn flows work (e.g. asking for confirmation, then executing on the next turn).

## Tool design
Three tool families, six total actions:
- **`doc_search(query)`** — vector retrieval (`text-embedding-3-small`, pgvector) over policy/SOP/product/contract documents, filtered by the caller's account before ranking.
- **`get_structured_data(query_type, entity_id)`** — lookups and account-scoped aggregates over accounts/orders/tickets. Strips internal-only fields (e.g. a ticket's `historical_resolution`) from customer-facing results.
- **`perform_action(action_type, entity_id, confirmed, details)`** — `cancel_order`, `issue_service_credit`, `create_followup_task`, `create_escalation`, `update_ticket`, `create_ticket`. Every action requires `confirmed=true`, which the tool only accepts after the agent has separately asked and the customer has agreed. `create_ticket` was added after testing showed the other five all assumed an existing ticket — a genuinely new issue had nowhere to go, causing the agent to loop.

Access control is enforced **in the tools themselves**, not left to the model's judgment: customer-mode calls cannot reach another account's data regardless of what `entity_id` the model passes, and cross-account attempts return an explicit, non-committal refusal rather than a silent substitution (an earlier version's silent substitution gave the model room to fabricate an explanation — a real bug found in testing).

## Document and structured-data handling
Four Postgres tables: `accounts`, `orders`, `tickets` (structured, loaded from the supplied xlsx) and `documents` (RAG chunks from the six supplied PDFs, each tagged with `doc_name`, `doc_status`, `effective_date`, and `account_id` — NULL for general policy documents, set for customer-specific contracts). The data pack was extended with additional dummy accounts/orders/tickets during testing to check that fixes generalized rather than just patching the literal example scenarios.

An IVFFlat index on the embedding column under-recalls at small row counts (a query can land near an empty cluster and return nothing, even though a full scan would find a match) — fixed by raising `ivfflat.probes` at query time.

## Source reliability and conflict handling
The agent's prompt encodes the supplied precedence order — signed customer agreement > current policy/SOP > current product documentation > historical tickets (context only) — and never treats a document marked DEPRECATED as current guidance. Two rules were added specifically because testing surfaced real failures: the agent must check the caller's actual account plan before answering a plan-gated question (it initially didn't), and it must distinguish a known-issue bug's failure threshold (temporary) from a documented product capability (permanent) — it initially conflated the two and validated an incorrect historical ticket resolution as a result. In customer-facing prose, sources are described by type ("your signed service agreement," "our current support policy") rather than by raw filename — an earlier version leaked internal document-naming/versioning to customers.

## Major technical trade-offs
- **Access control: tool-layer enforcement plus Postgres Row-Level Security as a second layer**, rather than relying on either alone. Adding RLS surfaced a Neon-specific gotcha — the default `neondb_owner` role has `BYPASSRLS` set, which silently defeats RLS regardless of `FORCE ROW LEVEL SECURITY` — so the app connects as a separate, deliberately unprivileged role.
- **A model-supplied `confirmed=true` flag is the only gate on state-changing actions.** This is a real, acknowledged limitation, not a solved problem — a production version should use a server-side, single-use confirmation token issued by the tool itself, so a model mistake or prompt injection can't skip straight to execution.
- **Single agent over a multi-agent crew** — simpler to reason about and debug given the mostly-linear workflow; would revisit if the scope grew to genuinely parallel or specialized sub-tasks.
- **Manual, scenario-based testing rather than an automated suite.** This caught real bugs (including a security-relevant cross-account leak) but is not exhaustive, and at least one fix (source-by-type citation) was observed to regress silently during later testing — exactly the kind of thing an automated regression suite would catch and this build doesn't have.
