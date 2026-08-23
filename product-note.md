# ParcelPilot Support Agent — Product Note

## Which additional client problem I chose and how I addressed it
I chose **Proactive Issue Detection** over the trust/reliability framing because the supplied data pack contains a concrete version of the failure mode: TKT-451 and TKT-502, three weeks apart, same customer, same underlying bug (KI-208) — but the first ticket was closed with a resolution that wrongly told the customer a temporary bug was a permanent plan limit. The agent never treats a ticket's `historical_resolution` as fact, and is explicitly instructed to distinguish "known issue, temporary" from "documented capability, permanent" before answering. To check the fix generalized rather than just matching the one example, I added a second, deliberately different mishandled ticket (a wrongly-denied service credit, different domain entirely) as part of extra dummy data used during testing — and verified the agent correctly caught that one too, without it being specifically test-cased in the prompt.

## Anything else I would build for ParcelPilot
In priority order:
1. **Proactive SLA-breach escalation** — today the agent only escalates when asked; a P1 ticket breaching its response target should trigger escalation on its own.
2. **Server-side confirmation tokens** for state-changing actions, replacing the current model-supplied `confirmed=true` flag, which is a real trust-boundary gap.
3. **AI-drafted, human-approved account changes via a PR-review workflow** — the AI proposes a change as a reviewable diff, a human approves or rejects, and only on merge does an automated pipeline apply it. This gets a full audit trail for free from PR history and a genuine human approval gate, and is especially well suited to higher-risk changes like credentials, where a slower, reviewed pace is a feature, not a limitation.
4. **Extend the document/precedence system to privacy and data-processing agreements** — architecturally identical to how customer contracts already override the default SOP; just a new document category.
5. **An internal/ops-facing UI** — the backend already supports an unrestricted internal mode; it's just not exposed. This unlocks legitimate internal questions that customer mode correctly refuses (e.g. "which known issue affects the most customers," "prioritize tickets for the team") — good questions, wrong audience in the current build.
6. **An automated regression test suite** — testing so far is manual; a `pytest` suite with mocked DB/OpenAI calls would catch regressions systematically (one fix — citing sources by type, not filename — was observed to silently regress during later testing).
7. **Real integrations and an adversarial test harness** — replace mocked DB writes with real carrier/payment/ticketing systems, and add dedicated red-teaming for prompt injection and access-control bypass, since the real bugs found here came from deliberately trying to break the system, not from systematic coverage.

## What I intentionally left out of the submission
- An internal/ops-facing UI (backend supports it; deliberately not wired into the Streamlit app for this submission)
- Real payment/carrier/ticketing integrations — actions write to the database but never call an external system
- An automated test suite — testing was manual and scenario-based, driven by my own read of the data pack's edge cases
- Server-side confirmation tokens — the current confirmation flow is prompt-enforced, not cryptographically enforced; I judged this an acceptable gap for a take-home assessment but not for production

## One metric I would use to judge whether the product is useful
**Correctly-resolved containment rate**: the percentage of customer conversations the agent fully resolves — a correct answer accepted, or an action correctly completed — without needing human escalation, measured *only* among conversations that pass a periodic accuracy spot-check against the source documents/database. I'd deliberately pair containment with an accuracy gate rather than tracking either alone: containment alone rewards confidently wrong answers, and accuracy alone doesn't tell you if the product is actually saving the support team work. A version of this is directly testable with this build's own data — e.g. the TKT-451/TKT-502 scenario is exactly a case that should count as a *failure* to contain correctly if the agent had repeated the wrong resolution instead of catching it.
