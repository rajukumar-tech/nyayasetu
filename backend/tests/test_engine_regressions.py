"""Regression tests for calculation bugs found in the audit (each test failed before its fix)."""
from __future__ import annotations

from datetime import date, timedelta

from conftest import TODAY, charge, custody, days_ago, hearing, make_case, make_person

from app.domain import Attribution, CaseStatus, CustodyType
from app.eligibility.engine import Status, evaluate_person


def one(kb, ctx, person):
    res = evaluate_person(person, kb, ctx)
    return res, res.cases[0]


def test_duplicate_and_overlapping_accused_adjournments_are_counted_once(kb, ctx):
    # before: each record subtracted its own overlap → 40 + 40 + 40 days for what is 60 calendar days
    hs = [hearing(days_ago(300), days_ago(260), Attribution.ACCUSED, verified=True),
          hearing(days_ago(300), days_ago(260), Attribution.ACCUSED, verified=True),
          hearing(days_ago(280), days_ago(240), Attribution.ACCUSED, verified=True)]
    _, c = one(kb, ctx, make_person([make_case(hearings=hs)], [custody(days_ago(399))]))
    assert c.accused_days == 60
    assert c.counted_days == c.custody_days - 60
    assert "DUPLICATE_HEARING" in c.flag_codes()


def test_accused_days_can_never_exceed_custody(kb, ctx):
    hs = [hearing(days_ago(500), days_ago(1), Attribution.ACCUSED, verified=True)] * 3
    _, c = one(kb, ctx, make_person([make_case(hearings=hs)], [custody(days_ago(100))]))
    assert c.accused_days <= c.custody_days and c.counted_days >= 0


def test_reversed_bail_range_does_not_inflate_custody(kb, ctx):
    # before: a bail record ending before it starts split custody into two OVERLAPPING pieces (days counted twice)
    ev = [custody(days_ago(399)), custody(days_ago(100), days_ago(150), type=CustodyType.ON_BAIL)]
    _, c = one(kb, ctx, make_person([make_case()], ev))
    assert c.custody_days == 400
    assert "INVALID_EXCLUSION_RANGE" in c.flag_codes()
    assert c.status in (Status.REVIEW, Status.CRITICAL_MUST_RELEASE)


def test_unknown_section_is_not_treated_as_fine_only(kb, ctx):
    # before: a section missing from the legal data became "fine only" and raised a false critical flag
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("999Z")])], [custody(days_ago(399))]))
    assert c.status == Status.REVIEW
    assert "UNUSUAL_DETENTION_FINE_ONLY" not in c.flag_codes()
    assert "MISSING_LEGAL_DATA" in c.flag_codes()


def test_counted_detention_is_shown_even_without_charges(kb, ctx):
    # before: counted_days stayed 0 next to the real custody days when charges were missing
    _, c = one(kb, ctx, make_person([make_case(charges=[])], [custody(days_ago(399))]))
    assert c.status == Status.REVIEW and c.custody_days == 400 and c.counted_days == 400


def test_future_only_custody_goes_to_review_not_not_applicable(kb, ctx):
    ev = [custody(TODAY + timedelta(days=5))]
    _, c = one(kb, ctx, make_person([make_case()], ev))
    assert c.status == Status.REVIEW and "FUTURE_START_DATE" in c.flag_codes()


def test_conflicting_primary_arrest_dates_need_review(kb, ctx):
    ev = [custody(days_ago(300), type=CustodyType.ARREST), custody(days_ago(305), type=CustodyType.ARREST),
          custody(days_ago(299))]
    _, c = one(kb, ctx, make_person([make_case(charges=[charge("420")])], ev))
    assert "CONFLICTING_ARREST_DATES" in c.flag_codes()
    assert c.status == Status.REVIEW
    assert any("Primary documents give different arrest dates" in n for n in c.needs_verification)


def test_eligibility_date_accounts_for_a_later_gap(kb, ctx):
    # custody 600 days, then 100 days on bail, then 100 days custody again; first-time IPC 379 → threshold 366.
    # The threshold was reached during the FIRST custody period; the old linear formula (today − surplus) put it
    # inside the bail period instead.
    first = days_ago(799)
    ev = [custody(first, days_ago(200)), custody(days_ago(199), days_ago(100), type=CustodyType.ON_BAIL),
          custody(days_ago(99), type=CustodyType.RE_ARREST)]
    _, c = one(kb, ctx, make_person([make_case()], ev))
    assert c.status == Status.ELIGIBLE
    assert c.eligible_from_date == first + timedelta(days=365)  # the 366th custody day
    assert c.days_overdue == c.counted_days - c.threshold_days
    assert c.eligible_from_date <= TODAY


def test_unknown_delay_that_could_flip_the_result_is_flagged_not_subtracted(kb, ctx):
    thr = 366
    start = days_ago(thr + 4)  # counted = thr + 5
    hs = [hearing(start + timedelta(days=10), start + timedelta(days=40), Attribution.UNKNOWN)]
    _, c = one(kb, ctx, make_person([make_case(hearings=hs)], [custody(start)]))
    assert c.status == Status.ELIGIBLE and c.accused_days == 0  # D-008: never subtracted
    assert "DELAY_ATTRIBUTION_AFFECTS_RESULT" in c.flag_codes()


def _db_case(**kw):
    return make_case(charges=[charge("305", act="BNS", offence_date=days_ago(120))], status=CaseStatus.INVESTIGATION, **kw)


def test_default_bail_application_same_day_as_late_charge_sheet_is_review(kb, ctx):
    case = _db_case(first_remand_date=days_ago(150), charge_sheet_date=days_ago(40), default_bail_application_date=days_ago(40))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(151))]))
    assert "DEFAULT_BAIL_REVIEW" in c.finding_codes()
    assert not {"DEFAULT_BAIL_RIGHT_LOST", "DEFAULT_BAIL_RIGHT_ASSERTED"} & c.finding_codes()


def test_default_bail_premature_application_with_late_charge_sheet_is_review(kb, ctx):
    case = _db_case(first_remand_date=days_ago(150), charge_sheet_date=days_ago(40), default_bail_application_date=days_ago(120))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(151))]))
    assert "DEFAULT_BAIL_REVIEW" in c.finding_codes() and "DEFAULT_BAIL_RIGHT_LOST" not in c.finding_codes()


def test_default_bail_charge_sheet_before_remand_is_review(kb, ctx):
    case = _db_case(first_remand_date=days_ago(100), charge_sheet_date=days_ago(110))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(101))]))
    assert "DEFAULT_BAIL_REVIEW" in c.finding_codes()


def test_default_bail_missing_remand_during_investigation_is_review(kb, ctx):
    case = _db_case()
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(70))]))
    assert "DEFAULT_BAIL_REVIEW" in c.finding_codes()


def test_default_bail_ten_year_maximum_between_day_60_and_90_is_review(kb, ctx):
    case = make_case(charges=[charge("309(4)", act="BNS", offence_date=days_ago(90))], status=CaseStatus.INVESTIGATION,
                     first_remand_date=days_ago(75))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(76))]))
    assert "DEFAULT_BAIL_REVIEW" in c.finding_codes() and "URGENT_DEFAULT_BAIL" not in c.finding_codes()


def test_default_bail_late_charge_sheet_without_application_is_not_simply_lost(kb, ctx):
    case = _db_case(first_remand_date=days_ago(150), charge_sheet_date=days_ago(40))
    _, c = one(kb, ctx, make_person([case], [custody(days_ago(151))]))
    f = next(x for x in c.findings if x.code == "DEFAULT_BAIL_RIGHT_LOST")
    assert "no default-bail application is on record" in f.message and "may survive" in f.message


def test_leap_day_and_year_boundaries_count_inclusively(kb, ctx):
    ev = [custody(date(2024, 2, 27), date(2024, 3, 2)), custody(date(2023, 12, 30), date(2024, 1, 2))]
    res = evaluate_person(make_person([make_case()], ev), kb, ctx)
    assert res.cases[0].custody_days == 5 + 4  # 27, 28, 29 Feb, 1, 2 Mar + 30, 31 Dec, 1, 2 Jan
