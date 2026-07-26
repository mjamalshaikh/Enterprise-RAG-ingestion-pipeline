"""Versioned domain events and Kafka topic definitions."""
"""Versioned domain event contracts."""

from .document_submitted import build_document_submitted_event

__all__ = ["build_document_submitted_event"]
