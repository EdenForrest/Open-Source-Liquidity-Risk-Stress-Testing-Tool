"""
Native-core bridge for the reverse-stress search.

This module is the thin Python side of the optional C++ search core
(``native/reverse_stress/reverse_stress_core.cpp``). It exposes one function,
:func:`native_solve`, which runs the deterministic part of the reverse-stress
search (coarse grid + breach-boundary refinement, radial ray bisection, and the
coordinate boundary-walk) in compiled C++, calling back into Python only for the
expensive portfolio repricing (the breach *oracle*).

Design contract
---------------
* The native core owns **no** domain logic beyond the search math: it is handed
  the precision matrix, the coherence axis groupings, the target, an evaluation
  budget, and an ``oracle(s) -> (liquid_pct_after, can_meet_redemption)`` callback.
  Everything portfolio-specific stays in Python.
* It is a **pure optimisation**: :func:`native_solve` returns ``None`` if the
  module is unavailable (not built, wrong ABI, import error), and the caller
  (:meth:`ReverseStressEngine.solve`) transparently falls back to the existing
  pure-Python search. Numerically the two agree — the C++ mirrors the Python
  routines line-for-line — so the only observable difference is speed.
* SLSQP stays in Python (scipy). The engine may run it first and pass the winners
  in as ``extra_seeds``; the native core ray/coordinate-polishes them alongside
  its own grid seeds, so the native path is never *worse* than the Python one.

The function returns a plain dict with the search-relevant fields the engine
needs to build a :class:`ReverseStressResult`; the engine does the final forced
repricing + scenario materialisation itself.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)

# Axis-name groupings for the coherence guardrail (kept in sync with the engine).
_MARKET_AXES = ("equity_shock", "rate_shock_bps")
_LIQUIDITY_AXES = ("adv_stress_scalar", "liquidity_haircut_multiplier", "redemption_rate")


def _load_core():
    """Import the compiled extension, or return ``None`` if it is unavailable.

    Kept behind a function (not a module-level import) so a missing/ABI-mismatched
    build degrades to the Python search instead of breaking import of the engine.
    """
    try:
        import reverse_stress_core  # type: ignore
        return reverse_stress_core
    except Exception:
        pass
    # The extension is installed *next to this shim* (inside the engines package
    # dir), which is not on sys.path when the package is imported normally. Add it
    # and retry before giving up, so a built module is found regardless of launch
    # mode (uvicorn, pytest, script).
    try:
        import os
        import sys

        here = os.path.dirname(os.path.abspath(__file__))
        if here not in sys.path:
            sys.path.append(here)
        import reverse_stress_core  # type: ignore
        return reverse_stress_core
    except Exception as exc:  # pragma: no cover - environment dependent
        logger.debug("native reverse_stress_core unavailable (%s) — using Python search", exc)
        return None


def native_available() -> bool:
    return _load_core() is not None


def native_solve(
    *,
    precision: np.ndarray,
    axis_names: Sequence[str],
    coherence_autonomy: float,
    target_liquid_pct: float,
    oracle: Callable[[Sequence[float]], "tuple[float, bool]"],
    grid_per_axis: int,
    eval_budget: int,
    extra_seeds: Optional[List[Sequence[float]]] = None,
) -> Optional[Dict]:
    """Run the native deterministic search. Returns a result dict or ``None``.

    Parameters mirror the engine's own state:

    * ``precision`` — the Mahalanobis precision matrix Σ⁻¹ (n×n).
    * ``axis_names`` — ordered active-axis names, used here only to derive the
      market/liquidity index groupings for the coherence guardrail.
    * ``oracle`` — ``s -> (liquid_pct_after, can_meet_redemption)``; the single
      expensive call. The native core caches it (4-dp quantised) exactly as the
      Python engine does, so the evaluation budget is comparable.
    * ``extra_seeds`` — optional pre-optimised (e.g. SLSQP) severity vectors.

    The returned dict has keys: ``status`` ("found" | "baseline-breach" |
    "infeasible"), and for "found": ``method``, ``s`` (list), ``distance``,
    ``corner_distance``, ``baseline_liquid_pct``, ``n_eval``.
    """
    core = _load_core()
    if core is None:
        return None

    names = list(axis_names)
    market_idx = [i for i, n in enumerate(names) if n in _MARKET_AXES]
    liquidity_idx = [i for i, n in enumerate(names) if n in _LIQUIDITY_AXES]

    # The C++ side takes plain Python lists/floats; the oracle must hand back a
    # (float, bool) pair. Wrap to coerce numpy scalars defensively.
    def _oracle(s):
        liquid, can_meet = oracle(s)
        return (float(liquid), bool(can_meet))

    prec = np.asarray(precision, dtype=float)
    prec_list = [[float(v) for v in row] for row in prec]

    try:
        sc = core.SearchCore(
            prec_list,
            market_idx,
            liquidity_idx,
            float(coherence_autonomy),
            float(target_liquid_pct),
            _oracle,
            int(eval_budget),
        )
        seeds = [list(map(float, s)) for s in (extra_seeds or [])]
        return dict(sc.solve(int(grid_per_axis), seeds))
    except Exception:  # pragma: no cover - defensive
        logger.exception("native reverse-stress solve failed — falling back to Python")
        return None
