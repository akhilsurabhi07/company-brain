"""
Enterprise Intent Registry — Module 4
======================================
Hierarchical, pluggable, extensible intent registry supporting 25+ enterprise intents.
Taxonomy hierarchy: Domain -> Category -> Intent Name.
Allows dynamic registration of new intents at runtime without code redesign.
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.retrieval.domain.query import IntentCandidate

class EnterpriseIntent(BaseModel):
    name: str
    domain: str = "Business"  # Business, Engineering, HR, Finance, Legal, Operations
    category: str  # Risk, Governance, Financial, People, Project, Document, General, Technical
    description: str
    keywords: List[str] = Field(default_factory=list)
    default_reasoning: str = "Lookup"  # Lookup, Causal, Comparison, Temporal, Aggregation, Statistical
    default_output_constraint: Optional[str] = None

class IntentRegistry:
    """Pluggable registry holding hierarchical enterprise intent definitions."""

    def __init__(self):
        self._intents: Dict[str, EnterpriseIntent] = {}
        self._populate_defaults()

    def register_intent(self, intent: EnterpriseIntent) -> None:
        """Register a new enterprise intent dynamically at runtime."""
        self._intents[intent.name] = intent

    def get_intent(self, name: str) -> Optional[EnterpriseIntent]:
        return self._intents.get(name)

    def list_intents(self) -> List[EnterpriseIntent]:
        return list(self._intents.values())

    def list_by_domain(self, domain: str) -> List[EnterpriseIntent]:
        return [i for i in self._intents.values() if i.domain.lower() == domain.lower()]

    def score_query(self, query_text: str) -> List[IntentCandidate]:
        """Scores query against all registered intents and returns ranked IntentCandidate objects."""
        q_lower = query_text.lower().strip()
        candidates: List[IntentCandidate] = []

        for name, intent in self._intents.items():
            score = 0.20  # Base prior
            matched_keywords = [k for k in intent.keywords if k in q_lower]
            
            if matched_keywords:
                # Strong boost per keyword match
                score += min(0.75, 0.40 + (len(matched_keywords) * 0.20))
            elif name == "GeneralSearch":
                score = 0.35

            conf = min(1.0, round(score, 2))
            if conf >= 0.85:
                tier = "HIGH"
            elif conf >= 0.60:
                tier = "MEDIUM"
            else:
                tier = "LOW"

            candidates.append(IntentCandidate(intent_name=name, confidence=conf, tier=tier))

        # Sort descending by confidence score
        candidates.sort(key=lambda x: x.confidence, reverse=True)
        return candidates

    def _populate_defaults(self) -> None:
        """Populate 25 enterprise intent definitions across 6 major domains out of the box."""
        defaults = [
            EnterpriseIntent(
                name="RiskAnalysis",
                domain="Business",
                category="Risk",
                description="Analysis of project risks, delays, bottlenecks, and blockers.",
                keywords=["delay", "risk", "overdue", "block", "issue", "failure", "blocker", "bottleneck"],
                default_reasoning="Causal",
                default_output_constraint="dependency_analysis"
            ),
            EnterpriseIntent(
                name="DependencyLookup",
                domain="Business",
                category="Project",
                description="Identification of prerequisite or downstream dependencies.",
                keywords=["depend", "prerequisite", "blocked_by", "relies on", "dependency"],
                default_reasoning="Dependency",
                default_output_constraint="dependency_analysis"
            ),
            EnterpriseIntent(
                name="EntityOwnership",
                domain="HR",
                category="People",
                description="Lookup of project owners, leads, assigned engineers, or contacts.",
                keywords=["owner", "who", "lead", "team", "manager", "assigned", "responsible", "contact"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="ProjectStatus",
                domain="Business",
                category="Project",
                description="Tracking project progress, milestones, and health status.",
                keywords=["status", "progress", "update", "health", "milestone", "delivery"],
                default_reasoning="Temporal",
                default_output_constraint="timeline"
            ),
            EnterpriseIntent(
                name="DecisionHistory",
                domain="Operations",
                category="Governance",
                description="Historical record of architectural, strategic, or project decisions.",
                keywords=["decision", "rationale", "why did", "approved", "agreed", "consensus"],
                default_reasoning="Causal"
            ),
            EnterpriseIntent(
                name="FinancialMetric",
                domain="Finance",
                category="Financial",
                description="Financial analysis including budgets, costs, invoices, and revenue.",
                keywords=["budget", "revenue", "cost", "financial", "$", "invoice", "spend", "expense", "profit"],
                default_reasoning="Statistical"
            ),
            EnterpriseIntent(
                name="Comparison",
                domain="Business",
                category="General",
                description="Side-by-side comparison of entities, projects, or documents.",
                keywords=["compare", "versus", "vs", "difference", "benchmark", "contrast", "alternative"],
                default_reasoning="Comparison"
            ),
            EnterpriseIntent(
                name="Compliance",
                domain="Legal",
                category="Governance",
                description="Security, regulatory, GDPR, ISO, and compliance verification.",
                keywords=["gdpr", "iso", "compliance", "audit", "security certification", "policy", "regulation"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="Summarization",
                domain="Business",
                category="General",
                description="Executive summaries, overviews, and recaps.",
                keywords=["summarize", "summary", "overview", "recap", "briefing", "tldr"],
                default_reasoning="Aggregation"
            ),
            EnterpriseIntent(
                name="DocumentLookup",
                domain="Operations",
                category="Document",
                description="Retrieval of specific documents, PDFs, contracts, or specifications.",
                keywords=["document", "pdf", "file", "contract", "policy doc", "manual", "spec"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="PeopleLookup",
                domain="HR",
                category="People",
                description="Employee profiles, roles, organization hierarchy, and contact info.",
                keywords=["people", "person", "employee", "profile", "role", "title", "roster"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="TemporalTimeline",
                domain="Business",
                category="Project",
                description="Chronological event progression and timelines.",
                keywords=["timeline", "history", "chronological", "schedule", "roadmap", "deadline"],
                default_reasoning="Temporal",
                default_output_constraint="timeline"
            ),
            EnterpriseIntent(
                name="AuditTrail",
                domain="Legal",
                category="Governance",
                description="Audit logs, edit history, and revision tracking.",
                keywords=["audit log", "change history", "revision", "commit", "modification", "edit history"],
                default_reasoning="Temporal"
            ),
            EnterpriseIntent(
                name="Troubleshooting",
                domain="Engineering",
                category="Technical",
                description="Technical issue resolution, error debugging, and root cause analysis.",
                keywords=["error", "bug", "crash", "issue resolution", "fix", "root cause", "failure mode"],
                default_reasoning="Causal"
            ),
            EnterpriseIntent(
                name="ArchitectureExploration",
                domain="Engineering",
                category="Technical",
                description="System architecture, component diagrams, and tech stack details.",
                keywords=["architecture", "design", "diagram", "component", "system design", "stack"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="ContractReview",
                domain="Legal",
                category="Governance",
                description="Vendor contracts, SLAs, terms, and expiration tracking.",
                keywords=["contract", "agreement", "vendor", "sla", "terms", "expiration", "renewal"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="CustomerFeedback",
                domain="Operations",
                category="Project",
                description="Customer complaints, feedback, feature requests, and support tickets.",
                keywords=["customer", "client", "bug report", "feedback", "ticket", "nps", "complaint"],
                default_reasoning="Aggregation"
            ),
            EnterpriseIntent(
                name="WorkflowTraversal",
                domain="Operations",
                category="Project",
                description="Process steps, approval flows, and pipeline stages.",
                keywords=["process", "workflow", "approval flow", "pipeline", "stage", "transition"],
                default_reasoning="Dependency"
            ),
            EnterpriseIntent(
                name="ResourceAllocation",
                domain="Finance",
                category="Financial",
                description="Headcount allocation, team capacity, and resource utilization.",
                keywords=["headcount", "allocation", "capacity", "staffing", "resource", "utilization"],
                default_reasoning="Statistical"
            ),
            EnterpriseIntent(
                name="StrategicGoal",
                domain="Business",
                category="Governance",
                description="Company OKRs, strategic goals, targets, and KPIs.",
                keywords=["okr", "goal", "target", "objective", "kpi", "vision", "priority"],
                default_reasoning="Aggregation"
            ),
            EnterpriseIntent(
                name="MeetingIntelligence",
                domain="Operations",
                category="Document",
                description="Meeting notes, transcripts, standup minutes, and action items.",
                keywords=["meeting", "minutes", "sync", "standup", "transcript", "discussion"],
                default_reasoning="Temporal"
            ),
            EnterpriseIntent(
                name="ProductFeature",
                domain="Engineering",
                category="Project",
                description="Product capabilities, feature specs, and user story requirements.",
                keywords=["feature", "capability", "spec", "roadmap item", "user story", "requirement"],
                default_reasoning="Lookup"
            ),
            EnterpriseIntent(
                name="GeneralSearch",
                domain="Business",
                category="General",
                description="Fallback broad domain search.",
                keywords=[],
                default_reasoning="Lookup"
            )
        ]
        for intent in defaults:
            self.register_intent(intent)

# Global Pluggable Intent Registry Instance
intent_registry = IntentRegistry()
