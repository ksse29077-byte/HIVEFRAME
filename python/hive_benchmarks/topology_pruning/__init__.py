"""Model-free M1-P0 Analytical Topology Pre-Gate."""

from .cost_model import amdahl_bound, build_cost_record
from .report import decide_gate
from .synthetic_cases import CASES, case_profile, generate_case

__all__ = [
    "CASES",
    "amdahl_bound",
    "build_cost_record",
    "case_profile",
    "decide_gate",
    "generate_case",
]
