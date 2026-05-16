"""In-memory run store keyed by UUID run_id."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

_store: dict[str, "RunRecord"] = {}


@dataclass
class RunRecord:
    status: str  # "pending" | "running" | "complete" | "error"
    results: Optional[dict] = field(default=None)
    error: Optional[str] = field(default=None)


def create(run_id: str) -> RunRecord:
    record = RunRecord(status="pending")
    _store[run_id] = record
    return record


def get(run_id: str) -> Optional[RunRecord]:
    return _store.get(run_id)


def update(run_id: str, **kwargs) -> None:
    record = _store.get(run_id)
    if record is None:
        return
    for k, v in kwargs.items():
        setattr(record, k, v)
