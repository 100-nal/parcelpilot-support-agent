# ParcelPilot Support Agent — Product Note

## Who this is for
Built as a **customer-facing** chatbot: a ParcelPilot customer signs in as their account and asks about shipments, cancellations, service credits, or their account terms. The backend also supports an "internal" mode (unrestricted account scope, sees internal-only fields), but the UI built for this submission surfaces only the customer-facing path.

## Chosen problem: Proactive Issue Detection
I chose this over the trust/reliability framing because the supplied data pack contains a concrete version of the failure mode: TKT-451 and TKT-502, three weeks apart, same customer, same underlying bug (KI-208) — but the first ticket was closed with a wrong resolution that misattributed an active bug to a permanent plan limit. The system never treats a ticket's `historical_resolution` as fact, and is instructed to distinguish "known issue, temporary" from "documented capability, permanent" before answering. To check whether this reasoning generalized rather than just matching the one example, I added a second, deliberately different mishandled ticket (a wrongly-denied service credit, not a bulk-upload issue) as part of the extra dummy data — a genuinely useful check, since a fix that only works on the literal example question wouldn't demonstrate much.

## What a customer-facing tone actually requires
One thing I only caught by using the deployed app myself, not by reasoning about it in advance: the agent's answers were citing raw internal filenames ("Support_Policy_v3_CURRENT.pdf") in customer-facing prose. That's a real product problem, not just a cosmetic one — a customer doesn't need to see ParcelPilot's internal document-versioning scheme, and a real support agent wouldn't talk that way. I had the agent switch to describing sources by type ("your signed service agreement," "our current support policy") in what it says out loud, while keeping the literal filename in the "Tools used" panel, where a technical reviewer can still verify it. Transparency and a natural customer-facing tone aren't actually in tension if you separate what's shown where.

## Design priorities, in order
1. **Never state something as fact without a source**, and never let the agent claim an action succeeded without verifying the tool's actual result — this second one was a real bug I found: the agent told a customer a service credit was "proceeding" in one turn, then admitted in the next turn it had actually failed. Trust in a support bot depends on this never happening, so it's now a hard rule to check the tool's literal return value before claiming anything.
2. **Access control that doesn't rely on the model behaving well.** Enforced in two places: the tool code (SQL-level scoping, tested repeatedly) and, as an added layer, Postgres Row-Level Security in Neon itself — so even a direct database connection outside the app is scoped.
3. **Confirm before acting, and don't nag.** Confirmation is required and enforced by the tool itself, not just prompted for — but early testing surfaced a real usability problem: the agent kept re-asking "could you confirm..." in slightly different words across several turns, which felt robotic and eroded trust rather than building it. I asked for that to be fixed directly, and separately caught a deeper bug behind some of the repetition: for a genuinely new issue with no existing ticket, none of the action tools could actually complete the request, so the agent got stuck looping. Adding a `create_ticket` action fixed the root cause, not just the symptom.
4. **Be honest about uncertainty, including "I don't have a policy for this."** Verified with a deliberately out-of-scope test (a large, undocumented damages claim) and, in the dummy data, a genuinely novel question (a chargeable-weight dispute) with no matching SOP at all — the agent is expected to say so and offer to escalate to a human rather than invent a rule.

## What's out of scope for this build
- Internal/ops-facing UI (backend supports it; not wired into the Streamlit app)
- Real payment/carrier integrations
- Automated regression testing / eval harness — testing so far is manual and scenario-based, driven by my own read of the data pack's edge cases rather than an automated suite

## Tradeoffs I'd revisit with more time
- IVFFlat vector index recall needed manual tuning at this small data scale; worth automating as the corpus grows.
- Conversation history is passed as plain text context each turn rather than a structured memory mechanism — works, but won't scale to long conversations.
- Testing coverage is necessarily incomplete — I found and fixed real bugs by actually using the deployed app the way an assessor would (including a security-relevant one, a cross-account information leak, that I caught by directly probing it), but scenario-based testing by definition can't guarantee everything is covered.

## Future development
If I kept building this, in priority order:

1. **Proactive SLA-breach escalation.** The agent currently only escalates when a customer explicitly asks. A P1 ticket that breaches its response-time target should trigger escalation on its own — the natural extension of the proactive-issue-detection theme this build is already centered on.

2. **Server-side confirmation tokens for state-changing actions.** Today, the only thing preventing a premature action is the LLM correctly passing `confirmed=True`. A production version should have the tool issue a one-time token on the first call and require that exact token back on the second — so a prompt-injection attempt or a model mistake can't skip straight to execution. This is a real gap, not a hypothetical one.

3. **AI-drafted, human-approved account changes via a PR-review workflow.** Rather than the AI mutating account data directly, it drafts the proposed change as a Pull Request (a structured, reviewable diff) — a human reviews and approves or rejects it, and only on merge does an automated pipeline apply the change to the actual database. This is a genuinely solid pattern (the same "GitOps" approach used for infrastructure and config changes elsewhere): it gets a full audit trail for free from PR history (who proposed it, who approved it, exactly what changed, when), and a real human approval gate before anything takes effect — well suited to account-detail changes, and especially appropriate for higher-risk changes like credentials, where the slower, reviewed pace is a feature rather than a limitation. It fits less naturally for things that need fast turnaround (e.g. live order status), where the existing double-confirmation-in-chat pattern is more appropriate.

4. **Extend the document/precedence system to privacy and data-processing agreements.** Real B2B contracts often carry separate privacy riders or DPAs beyond the main SOP. This is architecturally identical to how customer-specific contracts already override the default SOP in this build — just a new document category with its own precedence rules, not a new concept.

5. **Internal/ops-facing UI.** The backend already supports `mode="internal"`; it's just not exposed. This unlocks legitimate internal use cases that customer mode deliberately blocks (e.g. "which known issue affects the most customers," "prioritize tickets for the team to work through") — good questions, just for the wrong audience in the current build.

6. **Automated regression test suite.** Testing so far is manual — I re-ask the same questions after every fix to check nothing broke. A `pytest` suite with mocked DB/OpenAI calls would catch regressions systematically; this would have caught at least one fix (source citations by type, not filename) silently regressing during later testing.

7. **Real integrations and an adversarial test harness.** Replace mocked DB writes with actual carrier/payment/ticketing systems once past prototype stage; add a dedicated red-team suite for prompt injection and access-control bypass attempts, since the real bugs found in this build (a cross-account leak, a scope violation) came from deliberately trying to break it, not from systematic coverage.

