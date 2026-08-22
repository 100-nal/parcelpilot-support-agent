"""
ParcelPilot support agent - CrewAI implementation.

Three tools:
  1. doc_search        - RAG over policy/SOP/contract PDFs (documents table)
  2. get_structured_data - lookups/calculations over accounts/orders/tickets
  3. perform_action     - state-changing action (cancel order, issue credit,
                           create follow-up task), gated behind confirmation

Access control: every tool call is scoped by the caller's account_id
(customer mode) or unrestricted (internal mode) - enforced here in the
tool layer, not just via prompting.

Usage (as a library):
    from agent import build_crew
    crew = build_crew(account_id="ACCT-001", mode="customer")
    result = crew.kickoff(inputs={"query": "Can I cancel ORD-1001?"})
"""

import os
import json
from datetime import datetime

import psycopg2
from openai import OpenAI
from crewai import Agent, Task, Crew
from crewai.tools import tool

DATABASE_URL = os.environ["DATABASE_URL"]
openai_client = OpenAI()

# Dataset snapshot time, per README sheet - used for "how many hours late" calcs
SNAPSHOT_TIME = datetime(2026, 8, 16, 11, 0)

SOURCE_PRECEDENCE = """
Source precedence when information conflicts (highest to lowest authority):
1. Signed customer agreement (contract) for this specific account
2. Current support policy / current SOP (status = CURRENT)
3. Current product documentation (known issues, capabilities)
4. Historical tickets / past resolutions - CONTEXT ONLY, may be incorrect,
   never treat as authoritative
Never use a document marked DEPRECATED as current guidance.
"""


def _get_conn():
    return psycopg2.connect(DATABASE_URL)


def _embed(text: str):
    resp = openai_client.embeddings.create(model="text-embedding-3-small", input=text)
    return resp.data[0].embedding


def _scoped_account_filter(account_id: str | None, mode: str):
    """Returns SQL fragment + params enforcing access control at the query layer."""
    if mode == "customer":
        # Customer can only ever see their own account's rows, or account_id IS NULL
        # (general policy docs with no account scoping)
        return "AND (account_id = %s OR account_id IS NULL)", (account_id,)
    return "", ()  # internal mode: unrestricted


# ---------------------------------------------------------------------------
# Tool 1: Document search (RAG)
# ---------------------------------------------------------------------------

def make_doc_search_tool(account_id: str | None, mode: str, tool_log: list | None = None):
    @tool("doc_search")
    def doc_search(query: str) -> str:
        """Search ParcelPilot policies, SOPs, product docs, and customer
        agreements for relevant information. Returns the most relevant
        chunks with their source document, status (CURRENT/DEPRECATED),
        and effective date."""
        if tool_log is not None:
            tool_log.append({"tool": "doc_search", "input": query})
        vec = _embed(query)
        filter_sql, filter_params = _scoped_account_filter(account_id, mode)

        last_error = None
        for attempt in range(3):
            try:
                conn = _get_conn()
                cur = conn.cursor()
                cur.execute("SET ivfflat.probes = 10;")  # search more clusters for better recall
                cur.execute(
                    f"""
                    SELECT content, doc_name, doc_status, effective_date, account_id,
                           1 - (embedding <=> %s::vector) AS similarity
                    FROM documents
                    WHERE 1=1 {filter_sql}
                    ORDER BY embedding <=> %s::vector
                    LIMIT 5
                    """,
                    (vec, *filter_params, vec),
                )
                rows = cur.fetchall()
                cur.close()
                conn.close()

                if not rows:
                    if attempt < 2:
                        continue  # retry - likely a transient connection issue
                    return "No relevant documents found after retries."

                results = []
                for content, doc_name, status, eff_date, acct, sim in rows:
                    results.append(
                        f"[{doc_name} | status={status} | effective={eff_date} "
                        f"| account={acct or 'general'} | relevance={sim:.2f}]\n{content}"
                    )
                return "\n\n---\n\n".join(results)

            except Exception as e:
                last_error = e
                continue

        return f"doc_search failed after retries: {last_error}"

    return doc_search


# ---------------------------------------------------------------------------
# Tool 2: Structured data lookup / calculation
# ---------------------------------------------------------------------------

def make_structured_data_tool(account_id: str | None, mode: str, tool_log: list | None = None):
    @tool("get_structured_data")
    def get_structured_data(query_type: str, entity_id: str = "") -> str:
        """Look up structured data: accounts, orders, or tickets.
        query_type must be one of: 'account', 'order', 'ticket',
        'orders_for_account', 'tickets_for_account'.
        entity_id is the specific ID (e.g. 'ORD-1001'), or the account_id
        for the '_for_account' query types. Leave entity_id empty when
        mode is 'customer' and you want the caller's own account."""
        if tool_log is not None:
            tool_log.append({"tool": "get_structured_data", "input": f"{query_type} {entity_id}".strip()})

        conn = _get_conn()
        cur = conn.cursor()

        # Enforce access: customer mode can only query their own account_id
        target_account = entity_id if entity_id and mode == "internal" else account_id
        cross_account_attempt = False
        if mode == "customer" and query_type in ("account", "orders_for_account", "tickets_for_account"):
            if entity_id and entity_id != account_id:
                cross_account_attempt = True
            target_account = account_id  # never actually query another account's data

        try:
            if query_type == "account":
                if cross_account_attempt:
                    return (
                        "Access denied: you can only view your own account's details. "
                        "I cannot confirm, deny, or provide any information about other "
                        "accounts, companies, or account IDs - including whether they "
                        "exist, their contacts, or any mapping between a company name "
                        "and an account ID."
                    )
                cur.execute("SELECT * FROM accounts WHERE account_id = %s", (target_account,))
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    return "Account not found."
                return json.dumps(dict(zip(cols, [str(v) for v in row])))

            elif query_type == "order":
                cur.execute("SELECT * FROM orders WHERE order_id = %s", (entity_id,))
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    return "Order not found."
                order = dict(zip(cols, [str(v) for v in row]))
                if mode == "customer" and order.get("account_id") != account_id:
                    return "Access denied: this order does not belong to your account."
                return json.dumps(order)

            elif query_type == "ticket":
                cur.execute("SELECT * FROM tickets WHERE ticket_id = %s", (entity_id,))
                cols = [d[0] for d in cur.description]
                row = cur.fetchone()
                if not row:
                    return "Ticket not found."
                ticket = dict(zip(cols, [str(v) for v in row]))
                if mode == "customer":
                    if ticket.get("account_id") != account_id:
                        return "Access denied: this ticket does not belong to your account."
                    ticket.pop("historical_resolution", None)  # internal-only field
                return json.dumps(ticket)

            elif query_type == "orders_for_account":
                cur.execute("SELECT * FROM orders WHERE account_id = %s", (target_account,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, [str(v) for v in r])) for r in cur.fetchall()]
                return json.dumps(rows)

            elif query_type == "tickets_for_account":
                cur.execute("SELECT * FROM tickets WHERE account_id = %s", (target_account,))
                cols = [d[0] for d in cur.description]
                rows = [dict(zip(cols, [str(v) for v in r])) for r in cur.fetchall()]
                if mode == "customer":
                    for r in rows:
                        r.pop("historical_resolution", None)
                return json.dumps(rows)

            else:
                return f"Unknown query_type: {query_type}"

        finally:
            cur.close()
            conn.close()

    return get_structured_data


# ---------------------------------------------------------------------------
# Tool 3: State-changing action (mocked - writes to Neon, no real carrier/payment call)
# ---------------------------------------------------------------------------

def make_action_tool(account_id: str | None, mode: str, tool_log: list | None = None):
    @tool("perform_action")
    def perform_action(action_type: str, entity_id: str, confirmed: bool, details: str = "") -> str:
        """Perform a state-changing action. action_type must be one of:
        'cancel_order', 'issue_service_credit', 'create_followup_task',
        'create_escalation'.
        entity_id is the order_id or ticket_id being acted on.
        confirmed MUST be true - if the user has not explicitly confirmed
        this action in the conversation, call this with confirmed=false
        first to get the confirmation prompt, and only call again with
        confirmed=true after the user has explicitly agreed.
        details is a free-text note (e.g. reason, credit amount)."""
        if tool_log is not None:
            tool_log.append({"tool": "perform_action", "input": f"{action_type} on {entity_id} (confirmed={confirmed})"})

        if not confirmed:
            return (
                f"CONFIRMATION REQUIRED before proceeding with '{action_type}' "
                f"on {entity_id}. Please ask the user to explicitly confirm, "
                f"then call this tool again with confirmed=true."
            )

        conn = _get_conn()
        cur = conn.cursor()

        try:
            if action_type == "cancel_order":
                cur.execute("SELECT account_id, status FROM orders WHERE order_id = %s", (entity_id,))
                row = cur.fetchone()
                if not row:
                    return "Order not found."
                order_account, status = row
                if mode == "customer" and order_account != account_id:
                    return "Access denied: cannot cancel an order that does not belong to your account."
                if status == "DELIVERED":
                    return "Cannot cancel: order already delivered."
                if status == "PICKED_UP":
                    return "Cannot cancel: order already picked up. Use return-to-origin workflow instead."
                cur.execute(
                    "UPDATE orders SET status = 'CANCELLED', notes = COALESCE(notes,'') || %s WHERE order_id = %s",
                    (f" | Cancelled via agent: {details}", entity_id),
                )
                conn.commit()
                return f"Order {entity_id} cancelled successfully."

            elif action_type == "issue_service_credit":
                # Mocked: logs the credit as a note; no real payment/ledger system exists
                cur.execute("SELECT account_id FROM orders WHERE order_id = %s", (entity_id,))
                row = cur.fetchone()
                if not row:
                    return "Order not found."
                order_account = row[0]
                if mode == "customer" and order_account != account_id:
                    return "Access denied."
                cur.execute(
                    "UPDATE orders SET notes = COALESCE(notes,'') || %s WHERE order_id = %s",
                    (f" | Service credit issued (mocked): {details}", entity_id),
                )
                conn.commit()
                return f"Service credit recorded for {entity_id}: {details}"

            elif action_type == "create_followup_task":
                # Mocked: no real ticketing system integration: logs as a note on the ticket
                cur.execute("SELECT account_id FROM tickets WHERE ticket_id = %s", (entity_id,))
                row = cur.fetchone()
                if not row:
                    return "Ticket not found."
                ticket_account = row[0]
                if mode == "customer" and ticket_account != account_id:
                    return "Access denied."
                cur.execute(
                    "UPDATE tickets SET description = COALESCE(description,'') || %s WHERE ticket_id = %s",
                    (f" | Follow-up task created (mocked): {details}", entity_id),
                )
                conn.commit()
                return f"Follow-up task created on {entity_id}: {details}"

            elif action_type == "create_escalation":
                # Mocked: no real paging/incident system - marks the ticket escalated
                # and logs the reason, e.g. for an SLA breach or urgent unresolved issue.
                cur.execute("SELECT account_id FROM tickets WHERE ticket_id = %s", (entity_id,))
                row = cur.fetchone()
                if not row:
                    return "Ticket not found."
                ticket_account = row[0]
                if mode == "customer" and ticket_account != account_id:
                    return "Access denied."
                cur.execute(
                    "UPDATE tickets SET status = 'escalated', "
                    "description = COALESCE(description,'') || %s WHERE ticket_id = %s",
                    (f" | ESCALATED (mocked): {details}", entity_id),
                )
                conn.commit()
                return f"Ticket {entity_id} escalated: {details}"

            else:
                return f"Unknown action_type: {action_type}"

        finally:
            cur.close()
            conn.close()

    return perform_action


# ---------------------------------------------------------------------------
# Crew assembly
# ---------------------------------------------------------------------------

def build_crew(account_id: str | None, mode: str = "customer", tool_log: list | None = None):
    """mode: 'customer' (scoped to account_id) or 'internal' (unrestricted).
    tool_log: optional list that gets appended with {'tool': ..., 'input': ...}
    entries as tools are called, for displaying tool usage in a UI."""

    tools = [
        make_doc_search_tool(account_id, mode, tool_log),
        make_structured_data_tool(account_id, mode, tool_log),
        make_action_tool(account_id, mode, tool_log),
    ]

    support_agent = Agent(
        role="ParcelPilot Support Agent",
        goal="Answer support questions accurately using only the supplied "
             "ParcelPilot data, respecting source precedence and account access rules.",
        backstory=(
            "You are a support agent for ParcelPilot, a B2B logistics platform. "
            f"Current dataset snapshot time: {SNAPSHOT_TIME.isoformat()} (Asia/Kolkata).\n"
            f"{SOURCE_PRECEDENCE}\n"
            "Always check whether a signed customer agreement overrides the "
            "default policy before answering.\n\n"
            "CRITICAL RULE ON OTHER ACCOUNTS: You must NEVER state, guess, or imply "
            "anything about another customer's account - not whether an account ID "
            "or company name exists, not any mapping between a company name and an "
            "account ID, not any other company's contacts, CSM, contract terms, "
            "orders, or tickets. If a customer (in customer mode) asks about any "
            "account, company, or account ID other than their own, respond only "
            "with a simple refusal (e.g. 'I can only help with your own account') "
            "and do not speculate further, even if you think you can infer an "
            "answer. Never invent a mapping like 'X actually refers to Y' - if you "
            "are not certain from a tool result, say you don't have that "
            "information rather than guessing.\n\n"
            "CRITICAL RULE ON PLAN-GATED QUESTIONS: Before answering ANY question "
            "about a plan-gated capability (e.g. bulk upload, support hours, "
            "response-time SLAs), you MUST first call get_structured_data with "
            "query_type='account' to find out the caller's actual plan (Standard, "
            "Growth, or Enterprise). Do not assume the plan or answer generically - "
            "the same question has a different correct answer depending on the "
            "caller's plan (e.g. Standard has NO bulk upload at all, regardless of "
            "row count, while Growth/Enterprise support up to 5,000 rows). Always "
            "check the account's plan before applying any plan-specific rule from "
            "the documentation.\n\n"
            "CRITICAL RULE ON STATUS/BEHAVIOR QUESTIONS: If the customer's message "
            "contains any of these signals - describes a status that seems stale, "
            "wrong, delayed, or stuck; says something happened in real life that "
            "doesn't match what the system shows; uses words like 'still shows', "
            "'stuck', 'not updating', 'delayed', 'mismatch', 'is something wrong' "
            "- calling doc_search for known issues is MANDATORY and NON-NEGOTIABLE "
            "before you write ANY part of your answer. Do not offer to "
            "'investigate further' or 'escalate' as a substitute for checking - "
            "check known issues FIRST, then answer using what you find. Never give "
            "a generic, unsourced explanation (e.g. guessing about 'processing "
            "delays' or 'connectivity issues') when a specific known issue may "
            "explain it. If a known issue matches, cite it by ID and explain the "
            "expected behavior (e.g. 'this is a known delay, KI-211, expected to "
            "resolve within 20 minutes'). If the customer didn't give a specific "
            "order ID, use get_structured_data with query_type='orders_for_account' "
            "to see their recent orders yourself rather than only asking for the ID.\n\n"
            "CRITICAL RULE ON HISTORICAL TICKETS: A ticket's historical_resolution "
            "field is NEVER authoritative and MUST NOT be cited, repeated, or relied "
            "upon as fact under any circumstances - it may describe incorrect past "
            "guidance. Before answering ANY question that touches a plan limit, "
            "known issue, bug, capability, or root cause, you MUST call doc_search "
            "against the product/policy documents FIRST, even if a ticket's "
            "historical_resolution already seems to answer the question.\n\n"
            "CRITICAL RULE ON KNOWN ISSUES vs PLAN LIMITS: A known issue (KI-xxx) "
            "with status 'Investigating' or 'Monitoring' describes an ACTIVE BUG - "
            "a temporary defect causing failures below the documented capability, "
            "NOT a permanent product limitation. The documented capability (e.g. "
            "'Bulk Upload supported up to 5,000 rows') remains the true product "
            "limit even while the bug exists. If a historical_resolution told a "
            "customer that a plan or product only supports a lower number (e.g. "
            "'Growth plan only supports 3,000 rows') and current documentation "
            "shows this is actually a known bug's failure threshold rather than "
            "the documented limit, you MUST say the historical resolution was "
            "INCORRECT (not 'partially correct' or 'aligned with a workaround') - "
            "it misrepresented a temporary bug as a permanent capability. State "
            "plainly which known issue (by ID) explains the real cause.\n\n"
            "Never take a state-changing action without explicit user confirmation. "
            "If you are uncertain about carrier fault, timing, or eligibility after "
            "checking all available sources, say so and do not guess."
        ),
        tools=tools,
        verbose=True,
    )

    task = Task(
        description="Answer the user's request: {query}",
        expected_output="A clear, accurate answer grounded in the retrieved "
                         "documents/data, citing which source (contract vs "
                         "policy vs product doc) the answer relies on when relevant. "
                         "If a state-changing action is requested, confirm before acting.",
        agent=support_agent,
    )

    return Crew(agents=[support_agent], tasks=[task], verbose=True)
