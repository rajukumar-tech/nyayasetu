"""Section 9 checklist, items 25–33 (custody timeline)."""
from __future__ import annotations

from datetime import date, timedelta

from hypothesis import given, strategies as st

from app.domain import CustodyType
from app.timeline.reconstruct import inclusive_days, reconstruct
from conftest import TODAY, custody, days_ago, make_case, make_person, src


def tl_for(events, case=None, **case_kw):
    case = case or make_case(**case_kw)
    return reconstruct(make_person([case], events), case, TODAY)


def test_25_police_and_judicial_custody_both_counted():
    tl = tl_for([custody(days_ago(399), days_ago(386), type=CustodyType.POLICE_CUSTODY),
                 custody(days_ago(385))])
    assert tl.custody_days == 400
    assert len(tl.intervals) == 1
    assert "police custody" in tl.intervals[0].explanation and "judicial custody" in tl.intervals[0].explanation


def test_26_bail_excluded_and_rearrest_resumes():
    tl = tl_for([custody(days_ago(400), type=CustodyType.ARREST),
                 custody(days_ago(301), type=CustodyType.RELEASED),
                 custody(days_ago(100), type=CustodyType.RE_ARREST)])
    assert tl.custody_days == 100 + 101
    assert tl.gaps == [(days_ago(300), days_ago(101))]
    assert "UNEXPLAINED_GAP" not in {f.code for f in tl.flags}
    # explicit on-bail interval inside an open custody record is subtracted
    tl2 = tl_for([custody(days_ago(400)), custody(days_ago(300), days_ago(101), type=CustodyType.ON_BAIL)])
    assert tl2.custody_days == 401 - 200


def test_27_overlapping_records_merged_no_double_count():
    tl = tl_for([custody(days_ago(400), days_ago(200)), custody(days_ago(300))])
    assert tl.custody_days == 401
    assert len(tl.intervals) == 1


def test_28_jail_transfer_without_gap():
    tl = tl_for([custody(days_ago(400), days_ago(201), jail="Central Prison A"),
                 custody(days_ago(200), jail="District Jail B")])
    assert tl.custody_days == 401 and tl.gaps == []
    assert tl.intervals[0].jails == ["Central Prison A", "District Jail B"]


def test_29_escape_period_excluded():
    tl = tl_for([custody(days_ago(400)), custody(days_ago(300), type=CustodyType.ESCAPED),
                 custody(days_ago(200), type=CustodyType.RE_ARREST)])
    assert tl.custody_days == 101 + 201
    # absconding given as an explicit interval
    tl2 = tl_for([custody(days_ago(400), days_ago(301)), custody(days_ago(300), days_ago(201), type=CustodyType.ABSCONDING),
                  custody(days_ago(200))])
    assert tl2.custody_days == 100 + 201


def test_30_custody_in_other_case_shown_both_ways():
    case = make_case(offence_date=days_ago(500))
    p = make_person([case, make_case("C2")], [custody(days_ago(400), days_ago(101), case_id="C2"), custody(days_ago(100))])
    tl = reconstruct(p, case, TODAY)
    assert tl.custody_days == 101
    assert tl.lenient_custody_days == 401
    assert "CUSTODY_IN_OTHER_CASE" in {f.code for f in tl.flags}


def test_31_current_custody_without_end_uses_today():
    tl = tl_for([custody(days_ago(9))])
    assert tl.custody_days == 10 and tl.in_custody_today
    assert tl.intervals[-1].end == TODAY
    assert "CURRENT_CUSTODY_USES_TODAY" in {f.code for f in tl.flags}


def test_32_leap_year_and_inclusive_counting():
    assert inclusive_days(date(2024, 2, 28), date(2024, 3, 1)) == 3  # leap year
    assert inclusive_days(date(2023, 2, 28), date(2023, 3, 1)) == 2
    assert inclusive_days(date(2024, 1, 1), date(2024, 1, 1)) == 1  # same day = 1 day
    assert inclusive_days(date(2024, 1, 1), date(2024, 12, 31)) == 366
    tl = tl_for([custody(date(2024, 2, 1), date(2024, 3, 31))])
    assert tl.custody_days == 60


@given(start=st.dates(min_value=date(2000, 1, 1), max_value=date(2015, 1, 1)),
       length=st.integers(min_value=1, max_value=3000), cut=st.integers(min_value=0, max_value=2999))
def test_32b_property_split_intervals_sum_to_whole(start, length, cut):
    """Splitting a custody period at any day (e.g. jail transfer) never changes the count."""
    end = start + timedelta(days=length - 1)
    cut = min(cut, length - 1)
    mid = start + timedelta(days=cut)
    whole = tl_for([custody(start, end)]).custody_days
    split = tl_for([custody(start, mid), custody(mid, end)]).custody_days
    assert whole == split == length


def test_33_conflicting_arrest_dates_earliest_primary_and_flag():
    events = [
        custody(days_ago(400), type=CustodyType.ARREST, is_primary_source=False, source=src("J1", doc_type="jail_record")),
        custody(days_ago(390), type=CustodyType.ARREST, source=src("A1", doc_type="arrest_memo")),
        custody(days_ago(385), type=CustodyType.ARREST, source=src("R1", doc_type="remand_order")),
    ]
    tl = tl_for(events)
    assert tl.arrest.chosen == days_ago(390)
    assert tl.arrest.conflict
    flag = next(f for f in tl.flags if f.code == "CONFLICTING_ARREST_DATES")
    assert days_ago(400).isoformat() in flag.message and days_ago(385).isoformat() in flag.message
    assert tl.custody_days == 391
