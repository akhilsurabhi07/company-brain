"""
Knowledge Impact Analysis Engine — Module 3
============================================
Calculates downstream dependency impact.
Answers: "If Policy X / Entity Y changes, which teams, projects, workflows, and KPIs are affected?"
"""
from typing import List, Dict, Any

class KnowledgeImpactAnalyzer:
    """Performs graph impact traversal for changed entities or policies."""

    def analyze_impact(self, tenant_id: str, target_entity_name: str, sample_graph_edges: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Traverses downstream graph edges connected to target_entity_name.
        Returns affected teams, projects, workflows, and risk assessment.
        """
        affected_teams = []
        affected_projects = []
        affected_workflows = []

        for edge in sample_graph_edges:
            if edge.get("source") == target_entity_name:
                target = edge.get("target")
                relation = edge.get("relation")

                if "Team" in target or relation == "applies_to":
                    affected_teams.append(target)
                elif "Project" in target or relation == "affects":
                    affected_projects.append(target)
                elif "Workflow" in target or relation == "triggers":
                    affected_workflows.append(target)

        return {
            "target_entity": target_entity_name,
            "affected_teams_count": len(affected_teams),
            "affected_teams": list(set(affected_teams)),
            "affected_projects_count": len(affected_projects),
            "affected_projects": list(set(affected_projects)),
            "affected_workflows": list(set(affected_workflows)),
            "impact_severity": "high" if len(affected_projects) > 1 else "medium"
        }

knowledge_impact_analyzer = KnowledgeImpactAnalyzer()
