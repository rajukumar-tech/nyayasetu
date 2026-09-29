"""Additional cases so the eligibility engine reaches 100% branch coverage."""
from __future__ import annotations

from datetime import timedelta

from app.domain import Attribution, CaseStatus, ConvictionStatus, CustodyType
from app.eligibility.engine import Status, evaluate_person, urgency_rank
from conftest import (
    TODAY, charge, conviction, custody, days_ago, hearing, make_case, make_person,
)


def one(kb, ctx, person, cid="C1"):
    res = evaluate_person(person, kb, ctx)
    return res, next(c for c in res.cases if c.case_id == cid)


def test_person_level_aggregates(kb, ctx):
    res, c = one(kb, ctx, make_person([make_case()], [custody(days_ago(399))]))
    assert res.eligible_from_date == c.eligible_from_date and res.days_overdue == 34
    res2, _ = one(kb, ctx, make_person([make_case()], [custody(days_ago(10))]))
    assert res2.eligible_from_date is None and res2.days_overdue is None
    empty = evaluate_person(make_person([], []), kb, ctx)
    assert empty.overall_status == "NOT_APPLICABLE" and empty.flags[0].code == "NO_CASES"
    assert urgency_rank("SOMETHING_ELSE") == len(Status)


def test_accused_delay_edge_cases(kb, ctx):
    hs = [hearing(days_ago(300), None, Attribution.ACCUSED, "accused sought time"),
          hearing(days_ago(250), days_ago(240), Attribution.ACCUSED, "counsel changed", confidence=0.4),
          hearing(days_ago(200), days_ago(190), Attribution.PROSECUTION, "PP sought time"),
          hearing(days_ago(150), days_ago(140), Attribution.BOTH, "both sides sought time")]
    _, c = one(kb, ctx, make_person([make_case(hearings=hs)], [custody(days_ago(399))]))
    assert "ACCUSED_DELAY_NO_NEXT_DATE" in c.flag_codes()
    assert c.accused_days == 10
    assert any("Delay attribution" in n for n in c.needs_verification)
    assert c.status == Status.REVIEW
    assert "DELAY_ATTRIBUTION_UNCERTAIN" in c.flag_codes()


def test_conviction_set_aside_reassessed(kb, ctx):
    case = make_case(status=CaseStatus.CONVICTED, conviction_date=days_ago(50))
    p = make_person([case], [custody(days_ago(399))], [conviction("C1", ConvictionStatus.SET_ASIDE, days_ago(50))])
    _, c = one(kb, ctx, p)
    assert "CONVICTION_SET_ASIDE_REASSESS" in c.flag_codes()
    assert c.custody_days == 400 and c.status == Status.ELIGIBLE


def test_low_case_status_confidence(kb, ctx):
    _, c = one(kb, ctx, make_person([make_case(status_confidence=0.3)], [custody(days_ago(399))]))
    assert c.status == Status.REVIEW


def test_disposed_cases(kb, ctx):
    # acquitted, released on the day → not applicable
    case = make_case(status=CaseStatus.ACQUITTED, acquittal_date=days_ago(30))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(399), days_ago(30))]))
    assert c.status == Status.NOT_APPLICABLE
    # disposed without a date
    case = make_case(status=CaseStatus.DISPOSED)
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(399), days_ago(30))]))
    assert c.status == Status.NOT_APPLICABLE
    # acquitted but custody continues because another case is pending
    p = make_person([make_case(status=CaseStatus.ACQUITTED, acquittal_date=days_ago(30)), make_case("C2")],
                    [custody(days_ago(399), case_id=None)])
    _, c = one(kb, ctx, p)
    assert c.status == Status.NOT_APPLICABLE and "DETAINED_IN_OTHER_CASE" in c.flag_codes()


def test_pending_but_not_in_custody(kb, ctx):
    ev = [custody(days_ago(399), days_ago(200)), custody(days_ago(199), type=CustodyType.ON_BAIL)]
    _, c = one(kb, ctx, make_person([make_case()], ev))
    assert c.status == Status.NOT_APPLICABLE


def test_dropped_low_confidence_and_unknown_charges(kb, ctx):
    charges = [charge("324", dropped_on=days_ago(100)), charge("379", confidence=0.5)]
    _, c = one(kb, ctx, make_person([make_case(charges=charges)], [custody(days_ago(399))]))
    assert any("dropped" in s.text for s in c.trace)
    assert c.status == Status.REVIEW and any("Charge IPC 379" in n for n in c.needs_verification)
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("999")])], [custody(days_ago(399))]))
    assert c.status == Status.REVIEW and any("UNKNOWN_SECTION" in n for n in c.needs_verification)


def test_no_offence_charges(kb, ctx):
    case = make_case(charges=[charge("34")], first_remand_date=days_ago(100))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(100))]))
    assert c.status == Status.REVIEW and "NO_CHARGES" in c.flag_codes()
    assert any("No charge data" in s.text for s in c.trace)


def test_critical_with_special_law_and_with_unverified_inputs(kb, kb_raw, ctx):
    ch = charge("20(b)(ii)(A)", act="NDPS")  # max 1 year
    _, c = one(kb, ctx, make_person([make_case(charges=[ch])], [custody(days_ago(399))]))
    assert c.status == Status.CRITICAL_MUST_RELEASE and "SPECIAL_LAW" in c.flag_codes()
    _, c = one(kb_raw, ctx, make_person([make_case(charges=[charge("323")])], [custody(days_ago(399))]))
    assert c.status == Status.CRITICAL_MUST_RELEASE and "CRITICAL_NEEDS_VERIFICATION" in c.flag_codes()


def test_borderline_flag(kb, ctx):
    _, c = one(kb, ctx, make_person([make_case()], [custody(days_ago(364))]))
    assert "BORDERLINE" in c.flag_codes() and c.status == Status.NOT_YET


def test_lenient_count_changes_outcome_goes_to_review(kb, ctx):
    c1 = make_case("C1", offence_date=days_ago(500))
    c2 = make_case("C2", status=CaseStatus.ACQUITTED, acquittal_date=days_ago(101))
    p = make_person([c1, c2], [custody(days_ago(400), days_ago(101), case_id="C2"), custody(days_ago(100))])
    _, c = one(kb, ctx, p)
    assert c.status == Status.REVIEW and "including_other_case_custody" in c.interpretations
    # lenient differs but both below threshold → no review needed on that ground
    p2 = make_person([make_case("C1", offence_date=days_ago(500)), c2],
                     [custody(days_ago(150), days_ago(101), case_id="C2"), custody(days_ago(100))])
    _, c = one(kb, ctx, p2)
    assert c.status == Status.NOT_YET


def test_default_bail_other_paths(kb, ctx):
    # remand date unknown
    _, c = one(kb, ctx, make_person([make_case()], [custody(days_ago(100))]))
    assert any("First remand date unknown" in s.text for s in c.trace)
    # applied after accrual, no charge sheet yet
    case = make_case(first_remand_date=days_ago(100), default_bail_application_date=days_ago(30))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(100))]))
    assert "DEFAULT_BAIL_RIGHT_ASSERTED" in c.finding_codes()
    # far from the deadline → nothing
    case = make_case(first_remand_date=days_ago(10))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(10))]))
    assert not {f.code for f in c.findings} & {"DEFAULT_BAIL_WINDOW_SOON", "URGENT_DEFAULT_BAIL"}
    # unverified rule is listed
    from app.legal_kb.kb import KnowledgeBase
    from app.core.config import settings
    raw = KnowledgeBase.load(settings.legal_data_dir)
    _, c = one(raw, ctx, make_person([make_case(first_remand_date=days_ago(10))], [custody(days_ago(10))]))
    assert any("default_bail" in n for n in c.needs_verification)


def test_bail_granted_recently_or_released_in_between(kb, ctx):
    _, c = one(kb, ctx, make_person([make_case(bail_granted_date=days_ago(3))], [custody(days_ago(399))]))
    assert "CRITICAL_BAIL_NOT_FURNISHED" not in c.finding_codes()
    ev = [custody(days_ago(399), days_ago(25)), custody(days_ago(10), type=CustodyType.RE_ARREST)]
    _, c = one(kb, ctx, make_person([make_case(bail_granted_date=days_ago(30))], ev))
    assert "CRITICAL_BAIL_NOT_FURNISHED" not in c.finding_codes()


def test_time_served_findings(kb, ctx):
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("354")])], [custody(days_ago(399))]))
    assert "TIME_SERVED_EXCEEDS_MINIMUM" in c.finding_codes()
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("379")])], [custody(days_ago(599))],
                                    [conviction("C0", ConvictionStatus.FINAL)]))
    assert "TIME_SERVED_SUBSTANTIAL" in c.finding_codes()


def test_excluded_with_unverified_data_is_review(kb_raw, ctx):
    _, c = one(kb_raw, ctx, make_person([make_case(charges=[charge("302")])], [custody(days_ago(100))]))
    assert c.status == Status.REVIEW
    assert c.interpretations["if_inputs_confirmed"]["status"] == "EXCLUDED_479"


def test_multiple_offences_not_yet_sets_projection(kb, ctx):
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("379"), charge("447")])], [custody(days_ago(100))]))
    assert c.status == Status.REVIEW and c.projected_date == TODAY + timedelta(days=366 - 101)


def test_bns_era_offence_no_legacy_flag(kb, ctx):
    from datetime import date
    ch = charge("303(2)", act="BNS", offence_date=date(2025, 1, 10))
    _, c = one(kb, ctx, make_person([make_case(charges=[ch])], [custody(days_ago(399))]))
    assert "LEGACY_OFFENCE_479_APPLIED" not in c.flag_codes()
    assert c.status == Status.ELIGIBLE and c.charge_calcs[0].record_key == "BNS:303(2)"
