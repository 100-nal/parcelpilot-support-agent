"""
ParcelPilot Support - customer-facing chat UI.

Run with:
    streamlit run app.py

Requires DATABASE_URL and OPENAI_API_KEY set as environment variables
(locally) or in Streamlit Secrets (when deployed).
"""

import os
import psycopg2
import streamlit as st

from agent import build_crew

st.set_page_config(page_title="ParcelPilot Support", page_icon="📦")


def get_database_url():
    # Prefer Streamlit Secrets when deployed, fall back to env var locally.
    # st.secrets raises if no secrets.toml exists at all (local dev), so
    # catch broadly instead of just checking membership.
    try:
        if "DATABASE_URL" in st.secrets:
            return st.secrets["DATABASE_URL"]
    except Exception:
        pass
    return os.environ["DATABASE_URL"]


def get_openai_key():
    try:
        if "OPENAI_API_KEY" in st.secrets:
            return st.secrets["OPENAI_API_KEY"]
    except Exception:
        pass
    return os.environ["OPENAI_API_KEY"]


# Make sure agent.py's OpenAI client and DATABASE_URL pick up secrets too
os.environ.setdefault("DATABASE_URL", get_database_url())
os.environ.setdefault("OPENAI_API_KEY", get_openai_key())


@st.cache_data(ttl=300)
def get_accounts():
    conn = psycopg2.connect(get_database_url())
    cur = conn.cursor()
    cur.execute("SELECT account_id, account_name FROM accounts ORDER BY account_name")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


st.title("📦 ParcelPilot Support")
st.caption("Ask about your shipments, cancellations, service credits, or account terms.")

accounts = get_accounts()
account_options = {name: acct_id for acct_id, name in accounts}
selected_name = st.sidebar.selectbox("Signed in as:", list(account_options.keys()))
account_id = account_options[selected_name]

st.sidebar.markdown(f"**Account ID:** `{account_id}`")
st.sidebar.divider()
st.sidebar.caption(
    "This is a demo chatbot for ParcelPilot support. "
    "Switching accounts resets the conversation."
)

# Reset conversation if the account changes
if "account_id" not in st.session_state or st.session_state.account_id != account_id:
    st.session_state.account_id = account_id
    st.session_state.messages = []

# Render existing conversation
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("tools_used"):
            with st.expander("Tools used"):
                for t in msg["tools_used"]:
                    st.markdown(f"- **{t['tool']}**: `{t['input']}`")

# Chat input
if prompt := st.chat_input("How can we help you today?"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Include prior turns as context so the agent has conversation memory
    # (needed for the confirm-before-action flow to work across turns)
    history_lines = [
        f"{m['role'].capitalize()}: {m['content']}"
        for m in st.session_state.messages[:-1]
    ]
    history_text = "\n".join(history_lines)
    full_query = (
        f"Conversation so far:\n{history_text}\n\nLatest customer message: {prompt}"
        if history_text
        else prompt
    )

    with st.chat_message("assistant"):
        with st.spinner("Looking into it..."):
            tool_log = []
            crew = build_crew(account_id=account_id, mode="customer", tool_log=tool_log)
            result = crew.kickoff(inputs={"query": full_query})
            answer = str(result)
            st.markdown(answer)
            if tool_log:
                with st.expander("Tools used"):
                    for t in tool_log:
                        st.markdown(f"- **{t['tool']}**: `{t['input']}`")

    st.session_state.messages.append(
        {"role": "assistant", "content": answer, "tools_used": tool_log}
    )
