"""Section 9 checklist, items 1–24 (eligibility). Numbered test names match the spec."""
from __future__ import annotations

from datetime import date, timedelta

from app.domain import Attribution, CaseStatus, ConvictionStatus, CustodyType, Modifier
from app.eligibility.engine import Status, evaluate_person
from conftest import (
    TODAY, charge, conviction, custody, days_ago, hearing, make_case, make_person, src,
)

# IPC 379: max 3 years = 36 × 365.25/12 = 1095.75 → 1096 days; 1/3 → 366; 1/2 → 548.


def run(kb, ctx, person):
    res = evaluate_person(person, kb, ctx)
    return res, {c.case_id: c for c in res.cases}


def test_01_first_time_offender_past_one_third_eligible(kb, ctx):
    p = make_person([make_case()], [custody(days_ago(399))])
    res, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.ELIGIBLE
    assert c.custody_days == 400 and c.threshold_days == 366 and c.fraction == "1/3"
    assert c.days_overdue == 34
    assert c.eligible_from_date == TODAY - timedelta(days=34)
    assert res.overall_status == "ELIGIBLE"
    assert any("eligible to APPLY" in s.text for s in c.trace)


def test_02_first_time_offender_before_one_third_not_yet(kb, ctx):
    p = make_person([make_case()], [custody(days_ago(299))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.NOT_YET
    assert c.projected_date == TODAY + timedelta(days=66)
    assert c.days_overdue is None


def test_03_prior_conviction_uses_one_half(kb, ctx):
    old = make_case("C0", status=CaseStatus.CONVICTED, conviction_date=date(2019, 5, 1))
    p = make_person([old, make_case()], [custody(days_ago(599))], [conviction("C0", ConvictionStatus.FINAL)])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.first_time_offender is False and c.fraction == "1/2" and c.threshold_days == 548
    assert c.status == Status.ELIGIBLE and c.days_overdue == 52
    assert cases["C0"].status == Status.NOT_APPLICABLE


def test_04_prior_arrest_but_acquitted_still_first_time(kb, ctx):
    old = make_case("C0", status=CaseStatus.ACQUITTED, acquittal_date=date(2020, 1, 1))
    p = make_person([old, make_case()], [custody(date(2019, 6, 1), date(2019, 12, 1), case_id="C0"),
                                         custody(days_ago(399))])
    _, cases = run(kb, ctx, p)
    assert cases["C1"].first_time_offender is True
    assert cases["C1"].status == Status.ELIGIBLE
    assert cases["C0"].status == Status.NOT_APPLICABLE


def test_05_prior_conviction_set_aside_is_first_time(kb, ctx):
    p = make_person([make_case()], [custody(days_ago(399))], [conviction("C0", ConvictionStatus.SET_ASIDE)])
    _, cases = run(kb, ctx, p)
    assert cases["C1"].first_time_offender is True and cases["C1"].status == Status.ELIGIBLE
    assert any("set aside" in s.text for s in cases["C1"].trace)


def test_06_prior_conviction_under_appeal_counts_and_flags(kb, ctx):
    p = make_person([make_case()], [custody(days_ago(399))], [conviction("C0", ConvictionStatus.UNDER_APPEAL)])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.first_time_offender is False and c.fraction == "1/2"
    assert "PRIOR_CONVICTION_UNDER_APPEAL" in c.flag_codes()
    assert c.status == Status.NOT_YET


def test_07_juvenile_adjudication_flagged_and_treated_per_kb(kb, ctx):
    p = make_person([make_case()], [custody(days_ago(399))], [conviction("C0", ConvictionStatus.JUVENILE)])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert "JUVENILE_ADJUDICATION" in c.flag_codes()
    assert c.first_time_offender is True  # rules.yaml: juvenile_adjudication_counts: false
    # flip the KB rule → counted
    kb.rules["prior_convictions"].data["juvenile_adjudication_counts"] = True
    _, cases = run(kb, ctx, p)
    assert cases["C1"].first_time_offender is False


def test_08_death_or_life_offence_excluded(kb, ctx):
    p = make_person([make_case(charges=[charge("302")])], [custody(days_ago(2000))])
    _, cases = run(kb, ctx, p)
    assert cases["C1"].status == Status.EXCLUDED_479
    assert cases["C1"].charge_calcs[0].is_death_or_life


def test_09_life_as_alternative_punishment_excluded(kb, ctx):
    p = make_person([make_case(charges=[charge("326")])], [custody(days_ago(2000))])
    _, cases = run(kb, ctx, p)
    assert cases["C1"].status == Status.EXCLUDED_479


def test_10_fine_only_offence_flags_unusual_detention(kb, ctx):
    p = make_person([make_case(charges=[charge("290")])], [custody(days_ago(10))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW
    assert "UNUSUAL_DETENTION_FINE_ONLY" in c.flag_codes()
    assert c.charge_calcs[0].fine_only


def test_11_detention_beyond_maximum_critical_even_with_multiple_cases(kb, ctx):
    c1 = make_case("C1", charges=[charge("323")])  # max 1 year = 366 days
    c2 = make_case("C2", charges=[charge("379")])
    p = make_person([c1, c2], [custody(days_ago(399), case_id=None)])
    res, cases = run(kb, ctx, p)
    assert cases["C1"].status == Status.CRITICAL_MUST_RELEASE
    assert cases["C1"].days_overdue == 400 - 366
    assert cases["C2"].status == Status.REVIEW_MULTIPLE_CASES
    assert res.overall_status == "CRITICAL_MUST_RELEASE"


def test_12_multiple_cases_pending_review_with_both_interpretations(kb, ctx):
    p = make_person([make_case("C1"), make_case("C2")], [custody(days_ago(399), case_id=None)])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW_MULTIPLE_CASES
    assert set(c.interpretations) == {"case_wise", "bar_applies"}
    assert c.interpretations["case_wise"]["status"] == "ELIGIBLE"
    assert c.interpretations["bar_applies"]["ceiling_date"] == (TODAY + timedelta(days=1096 - 400)).isoformat()


def test_13_multiple_charges_different_maxima_review_per_charge(kb, ctx):
    p = make_person([make_case(charges=[charge("379"), charge("324"), charge("447")])], [custody(days_ago(399))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW
    assert "MULTIPLE_OFFENCES" in c.flag_codes()
    maxima = {cc.charge: cc.max_days for cc in c.charge_calcs}
    assert maxima == {"IPC 379": 1096, "IPC 324": 1096, "IPC 447": 92}
    assert c.max_term == "3 years"


def test_14_attempt_abetment_conspiracy_use_derived_maximum(kb, ctx):
    p = make_person([make_case(charges=[charge("380", modifier=Modifier.ATTEMPT)])], [custody(days_ago(429))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.max_term == "3 years 6 months" and c.max_days == 1279 and c.threshold_days == 427
    assert c.status == Status.ELIGIBLE and c.days_overdue == 3
    # attempt of an offence punishable with death → half of life-as-20-years = 10 years, not excluded
    p2 = make_person([make_case(charges=[charge("302", modifier=Modifier.ATTEMPT)])], [custody(days_ago(100))])
    _, c2 = run(kb, ctx, p2)
    assert c2["C1"].max_term == "10 years" and c2["C1"].status == Status.NOT_YET
    # conspiracy to a minor offence → 6 months
    p3 = make_person([make_case(charges=[charge("323", modifier=Modifier.CONSPIRACY)])], [custody(days_ago(199))])
    _, c3 = run(kb, ctx, p3)
    assert c3["C1"].max_term == "6 months" and c3["C1"].status == Status.CRITICAL_MUST_RELEASE
    # abetment (committed) → same maximum; common intention (s.34 as a separate charge) → ignored as liability rule
    p4 = make_person([make_case(charges=[charge("379", modifier=Modifier.ABETMENT), charge("34")])], [custody(days_ago(399))])
    _, c4 = run(kb, ctx, p4)
    assert c4["C1"].max_term == "3 years" and c4["C1"].status == Status.ELIGIBLE
    assert any("liability provision" in s.text for s in c4["C1"].trace)


def test_15_special_law_charge_flagged_not_auto_decided(kb, ctx):
    p = make_person([make_case(charges=[charge("20(b)(ii)(A)", act="NDPS")])], [custody(days_ago(200))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW
    assert "SPECIAL_LAW" in c.flag_codes()


def test_16_pre_bns_offence_uses_ipc_punishment_and_479_thresholds(kb, ctx):
    # Charged under BNS for an offence committed in 2023 → IPC 379 governs punishment.
    ch = charge("303(2)", act="BNS", offence_date=date(2023, 3, 1))
    p = make_person([make_case(charges=[ch])], [custody(days_ago(399))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert "IPC_BNS_TRANSITION_MISMATCH" in c.flag_codes()
    assert "LEGACY_OFFENCE_479_APPLIED" in c.flag_codes()
    assert c.charge_calcs[0].record_key == "IPC:379"
    assert c.status == Status.ELIGIBLE and c.threshold_days == 366


def test_17_delay_attributable_to_accused_subtracted(kb, ctx):
    h = hearing(days_ago(200), days_ago(180), Attribution.ACCUSED, "Adjourned at the request of the accused")
    p = make_person([make_case(hearings=[h])], [custody(days_ago(399))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.accused_days == 20 and c.counted_days == 380
    assert c.days_overdue == 14 and c.status == Status.ELIGIBLE


def test_18_unknown_delay_attribution_not_subtracted_and_flagged(kb, ctx):
    h = hearing(days_ago(200), days_ago(180), Attribution.UNKNOWN, "", confidence=0.0)
    p = make_person([make_case(hearings=[h])], [custody(days_ago(399))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.accused_days == 0 and c.counted_days == 400
    assert "DELAY_ATTRIBUTION_UNCERTAIN" in c.flag_codes()


def test_19_low_confidence_arrest_date_downgrades_to_review(kb, ctx):
    ev = custody(days_ago(399), type=CustodyType.ARREST, confidence=0.5)
    p = make_person([make_case()], [ev])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW
    assert any("Arrest date" in n for n in c.needs_verification)
    assert c.interpretations["if_inputs_confirmed"]["status"] == "ELIGIBLE"


def test_20_unverified_legal_data_downgrades_to_review(kb_raw, ctx):
    p = make_person([make_case()], [custody(days_ago(399))])
    _, cases = run(kb_raw, ctx, p)
    c = cases["C1"]
    assert c.status == Status.REVIEW
    assert any("IPC:379" in n for n in c.needs_verification)
    assert "DOWNGRADED_TO_REVIEW" in c.flag_codes()


def test_21_convicted_during_pendency_not_applicable(kb, ctx):
    case = make_case(status=CaseStatus.CONVICTED, conviction_date=days_ago(50))
    p = make_person([case], [custody(days_ago(399))], [conviction("C1", ConvictionStatus.FINAL, days_ago(50))])
    _, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.status == Status.NOT_APPLICABLE
    assert c.timeline.stop_date == days_ago(50) and c.custody_days == 350


def test_22_acquitted_but_still_detained_critical(kb, ctx):
    case = make_case(status=CaseStatus.ACQUITTED, acquittal_date=days_ago(30))
    p = make_person([case], [custody(days_ago(399))])
    res, cases = run(kb, ctx, p)
    assert cases["C1"].status == Status.CRITICAL_ACQUITTED_DETAINED
    assert res.overall_status == "CRITICAL_ACQUITTED_DETAINED"


def test_23_bail_granted_surety_not_furnished_counted_and_flagged(kb, ctx):
    case = make_case(bail_granted_date=days_ago(30))
    p = make_person([case], [custody(days_ago(399))])
    res, cases = run(kb, ctx, p)
    c = cases["C1"]
    assert c.custody_days == 400  # still counted
    assert "CRITICAL_BAIL_NOT_FURNISHED" in c.finding_codes()
    assert res.overall_status == "CRITICAL_BAIL_NOT_FURNISHED"


class TestDefaultBail:
    def test_24a_charge_sheet_not_filed_urgent(self, kb, ctx):
        case = make_case(first_remand_date=days_ago(100))
        p = make_person([case], [custody(days_ago(100))])
        res, cases = run(kb, ctx, p)
        f = next(f for f in cases["C1"].findings if f.code == "URGENT_DEFAULT_BAIL")
        assert f.date == days_ago(40)  # remand + 60 days
        assert res.overall_status == "URGENT_DEFAULT_BAIL"

    def test_24b_filed_on_time_no_flag(self, kb, ctx):
        case = make_case(first_remand_date=days_ago(100), charge_sheet_date=days_ago(50))
        p = make_person([case], [custody(days_ago(100))])
        _, cases = run(kb, ctx, p)
        assert not {"URGENT_DEFAULT_BAIL", "DEFAULT_BAIL_RIGHT_LOST"} & cases["C1"].finding_codes()

    def test_24c_filed_late_without_application_right_lost(self, kb, ctx):
        case = make_case(first_remand_date=days_ago(100), charge_sheet_date=days_ago(25))
        p = make_person([case], [custody(days_ago(100))])
        _, cases = run(kb, ctx, p)
        assert "DEFAULT_BAIL_RIGHT_LOST" in cases["C1"].finding_codes()
        assert "URGENT_DEFAULT_BAIL" not in cases["C1"].finding_codes()

    def test_24d_filed_late_after_application_right_asserted(self, kb, ctx):
        case = make_case(first_remand_date=days_ago(100), charge_sheet_date=days_ago(25),
                         default_bail_application_date=days_ago(35))
        p = make_person([case], [custody(days_ago(100))])
        _, cases = run(kb, ctx, p)
        assert "DEFAULT_BAIL_RIGHT_ASSERTED" in cases["C1"].finding_codes()

    def test_24e_serious_offence_uses_ninety_days(self, kb, ctx):
        case = make_case(charges=[charge("302")], first_remand_date=days_ago(80))
        p = make_person([case], [custody(days_ago(80))])
        _, cases = run(kb, ctx, p)
        assert "URGENT_DEFAULT_BAIL" not in cases["C1"].finding_codes()
        assert "DEFAULT_BAIL_WINDOW_SOON" not in cases["C1"].finding_codes()
        case.first_remand_date = days_ago(85)
        _, cases = run(kb, ctx, make_person([case], [custody(days_ago(85))]))
        assert "DEFAULT_BAIL_WINDOW_SOON" in cases["C1"].finding_codes()
        case.first_remand_date = days_ago(95)
        _, cases = run(kb, ctx, make_person([case], [custody(days_ago(95))]))
        assert "URGENT_DEFAULT_BAIL" in cases["C1"].finding_codes()
        assert cases["C1"].status == Status.EXCLUDED_479

    def test_24f_special_law_extended_period_flagged(self, kb, ctx):
        case = make_case(charges=[charge("20(b)(ii)(C)", act="NDPS")], first_remand_date=days_ago(100))
        p = make_person([case], [custody(days_ago(100))])
        _, cases = run(kb, ctx, p)
        assert "SPECIAL_LAW_DEFAULT_BAIL_PERIOD" in cases["C1"].flag_codes()
        assert "URGENT_DEFAULT_BAIL" not in cases["C1"].finding_codes()  # 180 days
