"""
Financial Metric Extractor Plugin — Module 3
=============================================
Extracts financial metrics, growth percentages, revenues, and quarterly periods.
"""
import re
from typing import List
from app.graph.interfaces.plugin_sdk import ExtractorPluginInterface
from app.domain.graph_models import EntityModel, FactModel

class FinancialExtractorPlugin(ExtractorPluginInterface):
    @property
    def plugin_name(self) -> str:
        return "financial_metric_extractor"

    def extract_entities(self, tenant_id: str, text_content: str) -> List[EntityModel]:
        return []

    def extract_facts(self, tenant_id: str, text_content: str) -> List[FactModel]:
        facts = []
        # Pattern: Revenue / Expense / Metric increased by X% in Q1/Q2/Q3/Q4
        pattern = r'(Revenue|Expense|Growth|MRR|ARR)\s+(?:increased|decreased|reached|expanded)\s+by\s+([\$\d\.\%M]+)(?:\s+in\s+(Q[1-4]\s+\d{4}|\d{4}))?'
        matches = re.findall(pattern, text_content, re.IGNORECASE)

        for metric, val, period in matches:
            facts.append(FactModel(
                tenant_id=tenant_id,
                fact_type="FinancialMetric",
                metric_name=metric.capitalize(),
                value=val,
                period=period if period else "Current Period",
                confidence_score=0.96,
                source_authority=0.90
            ))
        return facts

financial_extractor_plugin = FinancialExtractorPlugin()
