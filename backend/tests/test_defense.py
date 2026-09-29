"""Section 9 checklist, items 45–52 (Defense Insights). Item 53 (RBAC 403) is in test_api.py."""
from __future__ import annotations

import logging
from datetime import date

from app.defense.engine import Evidence, Insight, _guard, attach_judgments, detect
from app.defense.retrieval import JudgmentIndex, Passage, get_index, guard_citations
from app.domain import ComputeContext
from app.eligibility.engine import evaluate_person
from conftest import TODAY, charge, custody, days_ago, make_case, make_person

_n = 0


def fact(field, value, text=None, doc_type="fir", conf=0.95):
    global _n
    _n += 1
    t = text if text is not None else str(value)
    return {"id": f"F{_n}", "document_id": f"D-{doc_type}", "doc_type": doc_type, "field": field, "value": value,
            "corrected_value": None, "review_status": "pending", "page": 1, "span_start": 10 * _n, "span_end": 10 * _n + len(t),
            "span_text": t, "confidence": conf}


def run(kb, facts, charges=None, person_kw=None):
    case = make_case(charges=charges or [charge("379")])
    p = make_person([case], [custody(days_ago(100))])
    res = evaluate_person(p, kb, ComputeContext(TODAY)).cases[0]
    return {i.code: i for i in detect(p, case, facts, res, kb, TODAY, **(person_kw or {}))}


def test_45_production_after_24_hours_with_evidence_spans(kb):
    a = fact("arrest_datetime", "2025-10-01T09:15", "01/10/2025 09:15", "arrest_memo")
    p = fact("production_datetime", "2025-10-03T14:00", "03/10/2025", "remand_order")
    ins = run(kb, [a, p])["PRODUCTION_BEYOND_24H"]
    assert ins.severity == "critical" and "53 hours" in ins.title
    assert [e.fact_id for e in ins.evidence] == [a["id"], p["id"]]
    assert ins.evidence[0].doc_type == "arrest_memo" and ins.evidence[1].text == "03/10/2025"
    # within 24h → no insight
    p2 = fact("production_datetime", "2025-10-02T08:00", "02/10/2025", "remand_order")
    assert "PRODUCTION_BEYOND_24H" not in run(kb, [a, p2])


def test_46_grounds_of_arrest_not_recorded(kb):
    ins = run(kb, [fact("grounds_of_arrest", "not_recorded", "Not recorded", "arrest_memo")])
    assert ins["GROUNDS_NOT_COMMUNICATED"].category == "A"
    assert "GROUNDS_NOT_COMMUNICATED" not in run(kb, [fact("grounds_of_arrest", "yes", "Yes", "arrest_memo")])


def test_47_fir_delay_without_explanation(kb):
    o = fact("offence_datetime", "2025-01-01T22:00", "01/01/2025")
    f = fact("fir_datetime", "2025-01-08T10:00", "08/01/2025")
    ins = run(kb, [o, f, fact("fir_delay_reason", "", "")])
    assert "7 days" in ins["FIR_DELAY_UNEXPLAINED"].title
    assert "FIR_DELAY_UNEXPLAINED" not in run(kb, [o, f, fact("fir_delay_reason", "Complainant was hospitalised")])


def test_48_contradiction_fir_vs_charge_sheet_dates_both_spans(kb):
    o = fact("offence_datetime", "2025-01-01T22:00", "01/01/2025", "fir")
    cs = fact("charge_sheet_offence_date", "2025-01-04", "04/01/2025", "charge_sheet")
    ins = run(kb, [o, cs])["DATE_CONTRADICTION_FIR_CHARGESHEET"]
    assert {e.doc_type for e in ins.evidence} == {"fir", "charge_sheet"}
    assert {e.text for e in ins.evidence} == {"01/01/2025", "04/01/2025"}


def test_49_compoundable_offence_settlement_route(kb):
    ch = fact("charge", {"act": "IPC", "section": "323", "modifier": None}, "u/s 323 IPC", "charge_sheet")
    ins = run(kb, [ch], charges=[charge("323")])["COMPOUNDABLE_SETTLEMENT"]
    assert "without the court's permission" in ins.explanation
    assert "voluntary" in ins.next_steps and _guard(ins)
    ch2 = fact("charge", {"act": "IPC", "section": "302", "modifier": None}, "u/s 302 IPC", "charge_sheet")
    assert "COMPOUNDABLE_SETTLEMENT" not in run(kb, [ch2], charges=[charge("302")])


def test_50_plea_bargaining_excluded_for_offence_against_child(kb):
    ok = fact("charge", {"act": "IPC", "section": "379", "modifier": None}, "u/s 379 IPC", "charge_sheet")
    assert "PLEA_BARGAINING_AVAILABLE" in run(kb, [ok])
    child = fact("charge", {"act": "POCSO", "section": "12", "modifier": None}, "Sec 12 POCSO", "charge_sheet")
    assert "PLEA_BARGAINING_AVAILABLE" not in run(kb, [child], charges=[charge("12", act="POCSO")])
    women = fact("charge", {"act": "IPC", "section": "354", "modifier": None}, "u/s 354 IPC", "charge_sheet")
    assert "PLEA_BARGAINING_AVAILABLE" not in run(kb, [women], charges=[charge("354")])


def test_51_insight_without_evidence_is_not_shown(kb):
    bare = Insight("X", "A", "high", "t", "e", "n", [], [], 3, 3, 1.0)
    assert not _guard(bare)
    ev = Evidence("F", "D", "fir", 1, 0, 5, "text", "f")
    assert _guard(Insight("X", "A", "high", "t", "e", "n", [ev], [], 3, 3, 1.0))
    # forbidden strategies are never emitted even with evidence
    assert not _guard(Insight("X", "D", "high", "t", "e", "Try contacting the witness to change the statement", [ev], [], 3, 3, 1.0))
    # speedy-trial needs hearings on record; with no facts at all, no record-based insights appear
    assert set(run(kb, [])) == set()


def test_52_citation_not_in_corpus_stripped_and_logged(caplog):
    idx = JudgmentIndex([Passage("p1", "SYNTHETIC-TEST-0001", "Synthetic", "2000-01-01", "", "custody release text", True)])
    text = "As held in SYNTHETIC-TEST-0001 and in (2019) 5 SCC 123, and AIR 1979 SC 1360, the accused must be released."
    with caplog.at_level(logging.WARNING, logger="nyayasetu.citations"):
        out, removed = guard_citations(text, idx, "test")
    assert "SYNTHETIC-TEST-0001" in out
    assert removed == ["(2019) 5 SCC 123", "AIR 1979 SC 1360"]
    assert "(2019) 5 SCC 123" not in out and out.count("[citation removed") == 2
    assert sum("Stripped citation" in r.message for r in caplog.records) == 2


def test_52b_retrieved_judgments_come_only_from_corpus(kb):
    a = fact("arrest_datetime", "2025-10-01T09:15", "01/10/2025 09:15", "arrest_memo")
    p = fact("production_datetime", "2025-10-03T14:00", "03/10/2025", "remand_order")
    ins = list(run(kb, [a, p]).values())
    index = get_index()
    attach_judgments(ins, index)
    js = [j for i in ins for j in i.judgments]
    assert js and all(index.exists(j["citation"]) for j in js)
    top = next(i for i in ins if i.code == "PRODUCTION_BEYOND_24H").judgments[0]
    assert "twenty-four hours" in top["passage"] and top["synthetic"] is True


def test_ranking_puts_release_routes_first(kb):
    facts = [fact("arrest_datetime", "2025-10-01T09:15", "01/10/2025 09:15", "arrest_memo"),
             fact("tip_status", "Not held", "Not held", "charge_sheet"),
             fact("remand_date", "2025-10-02", "02/10/2025", "remand_order")]
    case = make_case(charges=[charge("323")])
    p = make_person([case], [custody(days_ago(399))])
    res = evaluate_person(p, kb, ComputeContext(TODAY)).cases[0]
    ranked = detect(p, case, facts, res, kb, TODAY)
    assert ranked[0].code == "DETAINED_BEYOND_MAXIMUM"
    assert ranked[-1].code == "TIP_NOT_HELD"
    _ = date
