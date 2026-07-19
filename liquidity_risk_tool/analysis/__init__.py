"""Library-level analysis orchestration (no web-tier dependency).

Exposes ``AnalysisResult`` (the single DTO produced by a pipeline run) and
``compute_analysis`` (the shared orchestrator consumed by both the FastAPI
backend and the CLI entry point).
"""
from .result import AnalysisResult
from .pipeline import compute_analysis

__all__ = ["AnalysisResult", "compute_analysis"]
