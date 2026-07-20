"""
AIFMD II Art. 16 LMT pre-selection rules (MODEL.md §20.4).

Two distinct counting forms exist and are deliberately kept separate:

* :func:`check_lmt_count` — the *activation* rule applied to an LMT simulation
  config: at least ``AIFMD2_MIN_LMT_COUNT`` of the active tools must come from
  ``SELECTABLE_TOOLS`` (suspension / side_pockets are always-available under
  Art. 16(2b) and do not count). Backs the pydantic 422 on the API.
* :func:`check_lmt_declared` — the *declaration* rule applied to Annex IV
  reporting metadata: at least ``AIFMD2_MIN_LMT_COUNT`` tools declared as
  pre-selected, regardless of the selectable/always-available split.
"""
from __future__ import annotations

from typing import Sequence

from ..config.settings import AIFMD2_MIN_LMT_COUNT, SELECTABLE_TOOLS


def check_lmt_count(active_tools: Sequence[str]) -> tuple[bool, str]:
    """
    §20.4 Rule 1: at least AIFMD2_MIN_LMT_COUNT *selectable* LMTs must be active.

    Returns ``(compliant, message)``; ``message`` is the exact violation text
    (empty when compliant) — API callers raise it verbatim so 422 bodies are
    stable.
    """
    selectable = {t for t in active_tools if t in SELECTABLE_TOOLS}
    if len(selectable) < AIFMD2_MIN_LMT_COUNT:
        return False, (
            f"AIFMD II requires at least {AIFMD2_MIN_LMT_COUNT} selectable LMTs "
            f"active (suspension and side_pockets are always-available and do "
            f"not count); got {sorted(selectable)} from {active_tools}."
        )
    return True, ""


def check_lmt_declared(lmt_preselected: Sequence[str]) -> bool:
    """§20.4 declaration form: ≥ AIFMD2_MIN_LMT_COUNT tools declared pre-selected."""
    return len(lmt_preselected) >= AIFMD2_MIN_LMT_COUNT
