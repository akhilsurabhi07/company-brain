"""
Request Normalization & Advanced Fuzzy Typo Resolution Engine — Module 5 EKAP
=============================================================================
Trims whitespace, resolves enterprise aliases, phonetic misspellings, shorthands,
and performs fuzzy edit-distance typo correction on user queries.
"""
import re
import difflib
from typing import Tuple, List

class QueryNormalizer:
    """Normalizes query text, resolving enterprise aliases, phonetic typos, and shorthands."""

    def __init__(self):
        # Primary enterprise entity canonical mapping
        self._aliases = {
            "phoenix": "Project Phoenix",
            "atlas": "Project Atlas",
            "titan": "Project Titan",
            "legal team": "Legal Department",
            "gdpr compliance": "GDPR Compliance Verification",
            "payroll": "Executive Payroll & Compensation"
        }

        # Phonetic and enterprise shorthand mappings
        self._shorthands = {
            "fenix": "phoenix",
            "phnix": "phoenix",
            "pohnix": "phoenix",
            "atls": "atlas",
            "ttn": "titan",
            "tinn": "titan",
            "legl": "legal team",
            "payrol": "payroll",
            "complince": "gdpr compliance"
        }

    def normalize(self, query_text: str) -> Tuple[str, List[str]]:
        # 1. Clean whitespace and normalize spacing
        cleaned = re.sub(r"\s+", " ", query_text).strip()
        
        # 2. Extract and resolve entity hints with exact, shorthand & fuzzy typo matching
        resolved_hints = []
        q_lower = cleaned.lower()
        tokens = re.findall(r"\b\w+\b", q_lower)

        # Substitute known shorthands into token check
        expanded_tokens = list(tokens)
        for token in tokens:
            if token in self._shorthands:
                expanded_tokens.append(self._shorthands[token])

        expanded_text = " ".join(expanded_tokens)

        for alias, canonical in self._aliases.items():
            if alias in q_lower or alias in expanded_text:
                if canonical not in resolved_hints:
                    resolved_hints.append(canonical)
            else:
                # Fuzzy typo match on tokens (edit-distance cutoff=0.70)
                alias_words = alias.split()
                for token in tokens:
                    if len(token) >= 3:
                        matches = difflib.get_close_matches(token, alias_words, cutoff=0.70)
                        if matches and canonical not in resolved_hints:
                            resolved_hints.append(canonical)

        return cleaned, resolved_hints

query_normalizer = QueryNormalizer()
