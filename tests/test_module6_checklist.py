import sys
import json
import urllib.request
import urllib.error

# Force stdout to UTF-8 to prevent Windows CP1252 charmap encoding errors
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

API_URL = "http://localhost:8000/api/v6a/chat/turn"

def send_request(user_query: str, history=None, tenant_id="tenant_enterprise_01"):
    payload = {
        "user_query": user_query,
        "history": history or [],
        "tenant_id": tenant_id,
        "persona": "CTO",
        "mode": "ARCHITECTURE_REVIEW"
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            raw = data.get("response_text", data.get("response", ""))
            if isinstance(raw, dict):
                return raw.get("text_content", "")
            return str(raw)
    except Exception as ex:
        return f"ERROR: {str(ex)}"


def run_checklist_suite():
    print("\n==========================================================================")
    print("      MODULE 6A / 6B CORRECTED REGRESSION & CHECKLIST TEST SUITE           ")
    print("==========================================================================\n")

    results = []

    # ──────────────────────────────────────────────────────────────────────────
    # 1. QUERY ROUTING TESTS (Unseen Phrasings & Edge Cases)
    # ──────────────────────────────────────────────────────────────────────────
    
    # 1.1 Memory Recall Alternate 1
    q1_1 = "can you remind me what I asked before this"
    hist1_1 = [
        {"role": "user", "content": "give the hr file"},
        {"role": "assistant", "content": "HR Policy Manual v4.2"}
    ]
    resp1_1 = send_request(q1_1, history=hist1_1)
    pass1_1 = "Session Memory Recall" in resp1_1 and "give the hr file" in resp1_1
    results.append(("1.1 Memory Recall Alternate 1", q1_1, resp1_1, pass1_1))

    # 1.2 Memory Recall Alternate 2
    q1_2 = "go back to my first question"
    hist1_2 = [
        {"role": "user", "content": "give the software design of this project"},
        {"role": "assistant", "content": "System Architecture Specification v3.0"}
    ]
    resp1_2 = send_request(q1_2, history=hist1_2)
    pass1_2 = "Session Memory Recall" in resp1_2 and "give the software design" in resp1_2
    results.append(("1.2 Memory Recall Alternate 2", q1_2, resp1_2, pass1_2))

    # 1.3 World Knowledge (No Signal Words)
    q1_3 = "how many people live in Hyderabad"
    resp1_3 = send_request(q1_3)
    pass1_3 = any(w in resp1_3.lower() for w in ["million", "hyderabad", "population", "10."]) and "couldn't find" not in resp1_3.lower()
    results.append(("1.3 World Knowledge (No Signals)", q1_3, resp1_3, pass1_3))

    # 1.4 Ambiguous Case (Grounded vs World Knowledge)
    q1_4 = "what's a competitive SaaS pricing model"
    resp1_4 = send_request(q1_4)
    pass1_4 = "sales_contract_template.txt" in resp1_4 and "120,000" in resp1_4 and "Per-Seat" in resp1_4
    results.append(("1.4 Ambiguous Grounded vs World", q1_4, resp1_4, pass1_4))

    # 1.5 Plausible Fake Company Query (Q4 Revenue Forecast)
    q1_5 = "what's our Q4 revenue forecast"
    resp1_5 = send_request(q1_5)
    pass1_5 = "couldn't find" in resp1_5.lower() and not any(char.isdigit() for char in resp1_5 if char in "123456789")
    results.append(("1.5 Plausible Fake Query (Revenue)", q1_5, resp1_5, pass1_5))

    # 1.6 Ungrounded Internal Codename (Project Titan)
    q1_6 = "what is Project Titan's deployment date"
    resp1_6 = send_request(q1_6)
    pass1_6 = "couldn't find" in resp1_6.lower()
    results.append(("1.6 Ungrounded Internal Codename", q1_6, resp1_6, pass1_6))

    # ──────────────────────────────────────────────────────────────────────────
    # 2. SECTION 2: REAL INGESTION PIPELINE INTEGRATION
    # ──────────────────────────────────────────────────────────────────────────
    q2_1 = "When is Project Apollo releasing?"
    resp2_1 = send_request(q2_1)
    pass2_1 = "project_apollo_roadmap.txt" in resp2_1 and "October 2026" in resp2_1
    results.append(("2.1 Real Ingestion Pipeline (Project Apollo)", q2_1, resp2_1, pass2_1))

    # ──────────────────────────────────────────────────────────────────────────
    # 3. TEST 3.1 CORRECTED: NEUTRAL CONFLICT SURFACING (No "conflict" in query)
    # ──────────────────────────────────────────────────────────────────────────
    q3_1a = "what is the probation period"
    resp3_1a = send_request(q3_1a)
    pass3_1a = "Sources Disagree" in resp3_1a and "90 Days" in resp3_1a and "180 Days" in resp3_1a
    results.append(("3.1a Proactive Conflict (Neutral Query 1)", q3_1a, resp3_1a, pass3_1a))

    q3_1b = "how long is the probation period"
    resp3_1b = send_request(q3_1b)
    pass3_1b = "Sources Disagree" in resp3_1b and "90 Days" in resp3_1b and "180 Days" in resp3_1b
    results.append(("3.1b Proactive Conflict (Neutral Query 2)", q3_1b, resp3_1b, pass3_1b))

    q3_1c = "what's our probation policy"
    resp3_1c = send_request(q3_1c)
    pass3_1c = "Sources Disagree" in resp3_1c and "90 Days" in resp3_1c and "180 Days" in resp3_1c
    results.append(("3.1c Proactive Conflict (Neutral Query 3)", q3_1c, resp3_1c, pass3_1c))

    # ──────────────────────────────────────────────────────────────────────────
    # 4. TEST 4.1 CORRECTED: REAL TENANT ISOLATION & RETRIEVAL SCOPING
    # ──────────────────────────────────────────────────────────────────────────
    # 4.1a Tenant Alpha querying Tenant Beta's data (Project Falcon)
    q4_1a = "What is Project Falcon and when does it launch?"
    resp4_1a = send_request(q4_1a, tenant_id="tenant_alpha")
    pass4_1a = "couldn't find" in resp4_1a.lower()
    results.append(("4.1a Cross-Tenant Leakage Check (Alpha -> Beta)", q4_1a, resp4_1a, pass4_1a))

    # 4.1b Tenant Beta querying Tenant Beta's own data (Project Falcon)
    q4_1b = "What is Project Falcon and when does it launch?"
    resp4_1b = send_request(q4_1b, tenant_id="tenant_beta")
    pass4_1b = "Project Falcon" in resp4_1b and "March 2026" in resp4_1b
    results.append(("4.1b Authorized Tenant Access (Beta -> Beta)", q4_1b, resp4_1b, pass4_1b))

    # 4.1c Tenant Beta querying Tenant Alpha's data (Project Sunrise)
    q4_1c = "What is Project Sunrise and when does it launch?"
    resp4_1c = send_request(q4_1c, tenant_id="tenant_beta")
    pass4_1c = "couldn't find" in resp4_1c.lower()
    results.append(("4.1c Cross-Tenant Leakage Check (Beta -> Alpha)", q4_1c, resp4_1c, pass4_1c))

    # 4.1d Memory Isolation Across Tenants
    q4_1d = "can you remind me what I asked before this"
    resp4_1d = send_request(q4_1d, history=[], tenant_id="tenant_beta")
    pass4_1d = "No prior turns were recorded" in resp4_1d
    results.append(("4.1d Cross-Tenant Memory Isolation", q4_1d, resp4_1d, pass4_1d))

    # ──────────────────────────────────────────────────────────────────────────
    # 5. SECTION 5: CITATION ACCURACY & EXCERPT MATCHING
    # ──────────────────────────────────────────────────────────────────────────
    q5_1 = "give the hr file"
    resp5_1 = send_request(q5_1)
    pass5_1 = "hr_policy_v4.2.txt" in resp5_1 and ("24 paid" in resp5_1) and ("90 days" in resp5_1)
    results.append(("5.1 Citation Accuracy & Excerpt Match", q5_1, resp5_1, pass5_1))

    # ──────────────────────────────────────────────────────────────────────────
    # OUTPUT UNFILTERED RAW TEST LOGS
    # ──────────────────────────────────────────────────────────────────────────
    total_passed = 0
    for title, q, resp, is_pass in results:
        status_str = "PASS" if is_pass else "FAIL"
        if is_pass: total_passed += 1
        print(f"[{status_str}] Test: {title}")
        print(f"       Raw Query: \"{q}\"")
        print(f"       Raw Output Snippet:\n{resp[:240].strip()}\n")
        print("--------------------------------------------------------------------------")

    print(f"\nFinal Test Summary: {total_passed}/{len(results)} Tests Passed.\n")
    return total_passed == len(results)

if __name__ == "__main__":
    success = run_checklist_suite()
    sys.exit(0 if success else 1)
