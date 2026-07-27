"""
Embedding Validator Module
==========================
Validates vector integrity prior to database persistence:
  - Asserts expected dimension (1024-dim)
  - Checks for NaN, Infinity, or None values
  - Verifies L2 vector normalization magnitude
"""
import math
from typing import List, Tuple

class EmbeddingValidator:
    """Vector Integrity & Quality Validator."""

    def validate_vector(self, vector: List[float], expected_dimension: int = 1024) -> Tuple[bool, str]:
        """Validates a single float vector."""
        if not vector:
            return False, "Vector is empty"

        if len(vector) != expected_dimension:
            return False, f"Invalid dimension: expected {expected_dimension}, got {len(vector)}"

        # Check for NaN, Infinity, or non-float values
        for idx, val in enumerate(vector):
            if val is None or not isinstance(val, (int, float)):
                return False, f"Invalid value type at index {idx}: {val}"
            if math.isnan(val):
                return False, f"NaN value found at index {idx}"
            if math.isinf(val):
                return False, f"Infinity value found at index {idx}"

        # Verify L2 Norm
        l2_norm = math.sqrt(sum(v * v for v in vector))
        if l2_norm < 0.0001:
            return False, f"Zero or near-zero L2 norm: {l2_norm}"

        return True, "Valid"

    def validate_batch(self, vectors: List[List[float]], expected_dimension: int = 1024) -> Tuple[List[List[float]], List[str]]:
        """Validates a batch of vectors and returns (valid_vectors, rejection_reasons)."""
        valid_vectors = []
        reasons = []

        for idx, vec in enumerate(vectors):
            is_valid, reason = self.validate_vector(vec, expected_dimension)
            if is_valid:
                valid_vectors.append(vec)
            else:
                reasons.append(f"Vector {idx} rejected: {reason}")

        return valid_vectors, reasons

embedding_validator = EmbeddingValidator()
