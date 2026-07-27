"""
Module 2 Chunking Policies & Configuration
==========================================
Token budgets and overlap policies tailored per document/resource category.
"""
from typing import Dict, Any

DEFAULT_CHUNKING_POLICIES: Dict[str, Dict[str, Any]] = {
    # PDFs, Word Docs, Text files
    "document": {
        "parent_target_tokens": 1500,
        "parent_overlap_tokens": 100,
        "child_target_tokens": 500,
        "child_overlap_tokens": 50,
        "min_child_tokens": 15,
        "max_child_tokens": 1024,
    },
    # Chat messages (Slack, Teams, Discord)
    "chat": {
        "parent_target_tokens": 800,
        "parent_overlap_tokens": 50,
        "child_target_tokens": 300,
        "child_overlap_tokens": 30,
        "min_child_tokens": 10,
        "max_child_tokens": 512,
    },
    # Jira/GitHub issues and tickets
    "ticket": {
        "parent_target_tokens": 1000,
        "parent_overlap_tokens": 50,
        "child_target_tokens": 350,
        "child_overlap_tokens": 35,
        "min_child_tokens": 10,
        "max_child_tokens": 512,
    },
    # Legal contracts, compliance, academic papers
    "legal": {
        "parent_target_tokens": 2000,
        "parent_overlap_tokens": 150,
        "child_target_tokens": 700,
        "child_overlap_tokens": 100,
        "min_child_tokens": 20,
        "max_child_tokens": 1024,
    },
}

def get_chunking_policy(resource_category: str = "document") -> Dict[str, Any]:
    """Returns chunking token budget parameters based on resource category."""
    cat = (resource_category or "document").lower()
    return DEFAULT_CHUNKING_POLICIES.get(cat, DEFAULT_CHUNKING_POLICIES["document"])
