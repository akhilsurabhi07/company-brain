"""Response Lifecycle States for Module 6A."""

from enum import Enum


class ResponseState(str, Enum):
    CREATED = "CREATED"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    VALIDATED = "VALIDATED"
    STREAMING = "STREAMING"
    COMPLETED = "COMPLETED"
    CACHED = "CACHED"
