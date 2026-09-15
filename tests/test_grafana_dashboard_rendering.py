import json
import unittest
import os

DASHBOARD_PATH = os.path.join("deploy", "grafana", "provisioning", "dashboards", "company_brain_dashboard.json")
DATASOURCE_PATH = os.path.join("deploy", "grafana", "provisioning", "datasources", "datasource.yaml")

class TestGrafanaDashboardRendering(unittest.TestCase):

    def test_01_dashboard_json_syntax_and_structure(self):
        """Verify Grafana Dashboard JSON is valid JSON and contains required panels."""
        self.assertTrue(os.path.exists(DASHBOARD_PATH), f"Dashboard file missing at {DASHBOARD_PATH}")
        
        with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data["title"], "Company Brain — Enterprise Telemetry & Production Hardening")
        self.assertEqual(data["uid"], "company-brain-prod-dashboard")
        
        panels = data.get("panels", [])
        self.assertEqual(len(panels), 4, "Dashboard MUST contain exactly 4 provisioned panels.")

        panel_titles = [p["title"] for p in panels]
        self.assertIn("HTTP Request Rate per Tenant (req/sec)", panel_titles)
        self.assertIn("LLM Token Usage per Tenant", panel_titles)
        self.assertIn("Retrieval Search Latency (p95 / p99)", panel_titles)
        self.assertIn("Fail-Open Rate Limit Fallback Events", panel_titles)
        print("  [1.1] Dashboard JSON syntax valid. 4 required telemetry panels confirmed.")

    def test_02_prometheus_metrics_and_datasource_alignment(self):
        """Verify panel PromQL queries target real Prometheus metrics and matching datasource UIDs."""
        with open(DASHBOARD_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)

        panels = data.get("panels", [])
        expected_metrics = [
            "company_brain_http_requests_total",
            "company_brain_llm_tokens_total",
            "company_brain_retrieval_latency_seconds_bucket",
            "company_brain_rate_limit_fallbacks_total"
        ]

        all_queries_str = ""
        for panel in panels:
            for target in panel.get("targets", []):
                all_queries_str += f" {target.get('expr', '')}"
                self.assertEqual(target.get("datasource", {}).get("uid"), "prometheus", "Datasource UID MUST match 'prometheus'.")

        for metric in expected_metrics:
            self.assertIn(metric, all_queries_str, f"PromQL query for metric '{metric}' MUST be present in dashboard panels.")
            print(f"  [2.1] Verified PromQL panel query targets metric '{metric}'.")

        print("[PASS] Grafana Dashboard & Prometheus Datasource Alignment Verified.")

if __name__ == "__main__":
    unittest.main()
