"""
Knowledge Reasoning Engine — Module 3
======================================
Derives higher-order business inferences and risk propagation from explicit relationships.
(e.g., Project Phoenix depends on Security Review, Security Review depends on Legal Approval,
Legal Approval is overdue -> Inferred Derived Fact: 'Project Phoenix is at risk').
"""
from typing import List, Dict, Any
from app.domain.graph_models import FactModel

class KnowledgeReasoner:
    """Evaluates rule-based dependency graphs to infer derived business facts."""

    def infer_dependency_risks(self, tenant_id: str, project_name: str, dependency_chain: List[Dict[str, Any]]) -> List[FactModel]:
        """
        Traverses dependency chain.
        If any upstream dependency has state 'overdue' or 'blocked',
        infers a derived risk fact for the project.
        """
        derived_facts = []
        is_blocked = any(dep.get("state") in ["overdue", "blocked"] for dep in dependency_chain)

        if is_blocked:
            blocked_dep = next(dep["name"] for dep in dependency_chain if dep.get("state") in ["overdue", "blocked"])
            derived_facts.append(FactModel(
                tenant_id=tenant_id,
                fact_type="DerivedRiskInsight",
                is_derived=True,
                metric_name="Project Risk Status",
                value=f"{project_name} is at risk due to overdue dependency: {blocked_dep}",
                confidence_score=0.88,
                source_authority=0.95
            ))

        return derived_facts

knowledge_reasoner = KnowledgeReasoner()
