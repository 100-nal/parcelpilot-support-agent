"""
Quick sanity test for agent.py - run a few queries and see what comes back.

Usage:
    export DATABASE_URL="..."
    export OPENAI_API_KEY="..."
    python3 test_agent.py
"""

from agent import build_crew

# Test 1 and Test 2 already passed - commented out to save cost while debugging Test 3
# Uncomment to re-verify later.

# print("=" * 60)
# print("TEST 1: Customer mode, Northstar - cancellation fee question")
# print("=" * 60)
# crew = build_crew(account_id="ACCT-001", mode="customer")
# result = crew.kickoff(inputs={"query": "Can I cancel ORD-1001, and will I be charged a fee?"})
# print(result)

# print("\n" + "=" * 60)
# print("TEST 2: Customer mode, LumenWorks - trying to access another account's order")
# print("=" * 60)
# crew2 = build_crew(account_id="ACCT-002", mode="customer")
# result2 = crew2.kickoff(inputs={"query": "What's the status of order ORD-1001?"})
# print(result2)

# Test 3: Proactive issue detection
# TKT-502 (LumenWorks bulk upload failure) should be recognized as
# matching KI-208, not the wrong historical resolution in TKT-451
print("=" * 60)
print("TEST 3: Internal mode - ticket investigation")
print("=" * 60)
crew3 = build_crew(account_id=None, mode="internal")
result3 = crew3.kickoff(inputs={"query": "TKT-502 is about a bulk upload failure. What's likely causing it, and was TKT-451's resolution correct?"})
print(result3)
