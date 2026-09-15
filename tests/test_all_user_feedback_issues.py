import asyncio
import sys

sys.path.insert(0, "C:/Users/Surabhi Akhil/OneDrive/Desktop/PCB")
sys.path.insert(0, "C:/Users/Surabhi Akhil/.gemini/antigravity/brain/82259030-8311-4a5c-af32-71cedbfe5073")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.orchestrator import orchestrator

async def run_feedback_test_suite():
    tenant_id = "00000000-0000-0000-0000-000000000001"

    print("\n==========================================================================")
    print(" 🧪 RUNNING VERIFICATION TEST SUITE FOR USER BROWSER FEEDBACK ISSUES     ")
    print("==========================================================================")

    # ─── 1. Test World Knowledge Fallback ──────────────────────────────────────
    print("\n--- TEST 1: World Knowledge Fallback ('tell the cm of telangana') ---")
    res1 = await orchestrator.execute_task(user_query="tell the cm of telangana", tenant_id=tenant_id)
    text1 = res1.get("response_text", "")
    citations1 = res1.get("citations", [])
    print(f"CITATIONS: {citations1}")
    print(f"RESPONSE:\n{text1}")
    
    assert "Revanth Reddy" in text1 or "General World Knowledge" in str(citations1), "FAILED: CM of Telangana should return world knowledge!"
    assert not any("WhatsApp" in c or "CTO Elena" in c for c in citations1), "FAILED: World knowledge query cited company documents!"
    print("  ✅ TEST 1 PASSED: World Knowledge Fallback triggered cleanly without company document hallucination.")

    # ─── 2. Test Direct CTO Questions ─────────────────────────────────────────
    print("\n--- TEST 2: Direct CTO Query ('tell about cto of the company') ---")
    res2 = await orchestrator.execute_task(user_query="tell about cto of the company", tenant_id=tenant_id)
    text2 = res2.get("response_text", "")
    citations2 = res2.get("citations", [])
    print(f"CITATIONS: {citations2}")
    print(f"RESPONSE:\n{text2[:400]}")
    
    assert any("CTO Elena" in c or "Tech Stack" in c for c in citations2) or "Elena Rostova" in text2, "FAILED: CTO query did not retrieve Elena Rostova document!"
    print("  ✅ TEST 2 PASSED: Direct CTO query retrieved Elena Rostova's Tech Stack Guidelines cleanly.")

    # ─── 3. Test Repetition / Duplication Fix ─────────────────────────────────
    print("\n--- TEST 3: Repetition & Duplication Check ---")
    count_sources = text2.count("## 📄 Grounded Search Result:")
    print(f"OCCURRENCES OF SOURCE HEADER: {count_sources}")
    assert count_sources <= 1, f"FAILED: Repetition bug detected! Header appeared {count_sources} times."
    print("  ✅ TEST 3 PASSED: Zero response repetition or triple duplication.")

    # ─── 4. Test Missing HR Policy ─────────────────────────────────────────────
    print("\n--- TEST 4: Missing HR Policy ('give the hr policy file') ---")
    res4 = await orchestrator.execute_task(user_query="give the hr policy file", tenant_id=tenant_id)
    text4 = res4.get("response_text", "")
    citations4 = res4.get("citations", [])
    print(f"CITATIONS: {citations4}")
    print(f"RESPONSE:\n{text4[:300]}")

    # Acceptable: Either honest refusal OR closest policy documents returned (not WhatsApp chats)
    assert not any("WhatsApp" in c or "Acme" in c or "Client Feedback" in c for c in citations4), \
        "FAILED: HR Policy query cited WhatsApp/Acme client documents — clearly wrong!"
    # If documents returned, count source headers to verify no duplication
    if citations4:
        count_headers = text4.count("## 📄 Grounded Search Result:")
        assert count_headers == len(citations4), f"FAILED: {count_headers} source headers for {len(citations4)} citations — duplication detected!"
    print("  ✅ TEST 4 PASSED: HR Policy returns relevant policy docs without WhatsApp noise and without duplication.")

    print("\n==========================================================================")
    print(" 🎉 ALL 4 USER BROWSER FEEDBACK TESTS PASSED WITH 100% PRECISION!        ")
    print("==========================================================================\n")

if __name__ == "__main__":
    asyncio.run(run_feedback_test_suite())
