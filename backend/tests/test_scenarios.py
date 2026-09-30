"""The ~1,000 synthetic scenarios, checked against the independent oracle (see app/scenario_check.py).

The full run with the complete API/authorization sweep (≈13,000 requests) is `python -m app.scenario_check`;
here all 1,000 scenarios are checked for calculations, invariants and recompute idempotency, and a 150-scenario
sample also goes through the API authorization / consistency / audit sweep."""
from __future__ import annotations

from app.scenario_check import run


def test_1000_scenarios_calculations_and_idempotency():
    out = run(target=1000, api_checks=False, write_report=False, verbose=False)
    s = out["summary"]
    assert s["scenarios"] >= 1000
    assert s["failed"] == 0, out["failures"][:10]
    assert s["recompute_idempotent"], s["recompute"]
    assert s["categories"] >= 100


def test_scenario_sample_through_the_api():
    out = run(target=150, api_checks=True, write_report=False, verbose=False)
    s = out["summary"]
    assert s["failed"] == 0, out["failures"][:10]
    assert s["authorization_failures"] == 0, out["authorization_failures"][:10]
    assert s["consistency_failures"] == 0, out["consistency_failures"][:10]
    assert s["audit_failures"] == 0, out["audit_failures"]
    assert s["identity"]["auto_merged"] == 0 and s["identity"]["different_people_proposed_as_link"] == 0
