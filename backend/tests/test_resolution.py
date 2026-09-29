"""Section 9 checklist, items 38–44 (entity resolution)."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select

from app.models import AuditLog, Case, CustodyEvent, Person
from app.resolution.matcher import PairModel, Record, resolve, score_pair
from app.resolution.merge import dedupe_cases_by_cnr, merge_persons, unmerge

M = PairModel()


def rec(i, name, father=None, age=None, district="Bengaluru Urban", ps=None, addr=None, cnrs=()):
    return Record(i, name, father, age, district, ps, addr, [], list(cnrs))


def test_38_same_person_different_spellings_and_scripts_linked():
    a = rec("a", "Manjunatha S", "Siddappa", 34, ps="Jayanagar PS", addr="12, Hebbal")
    b = rec("b", "ಮಂಜುನಾಥ ಎಸ್", "ಸಿದ್ದಪ್ಪ", 35, ps="Jayanagar PS", addr="12, Hebbal")
    c = rec("c", "MANJUNATH", "Siddapa", 34, ps="Jayanagar PS")
    res = resolve([a, b, c], M)
    assert any({"a", "b"} <= cl for cl in res.clusters)
    assert score_pair(a, b, M).decision == "link"
    # sparser record (no address): linked or queued for review — never a false split without trace
    assert score_pair(a, c, M).decision in ("link", "review")


def test_39_different_people_same_name_different_fathers_not_linked():
    a = rec("a", "Ravi Kumar", "Krishnappa", 30, ps="Shivajinagar PS", addr="3, Yelahanka")
    b = rec("b", "Ravi Kumar", "Hanumanthappa", 31, ps="Shivajinagar PS", addr="9, Yelahanka")
    s = score_pair(a, b, M)
    assert s.decision == "no_link" and "RELATIVE_NAME_DIFFERS" in s.vetoes
    assert {"a"} in resolve([a, b], M).clusters


def test_40_same_name_same_father_age_20_years_apart_not_linked():
    a = rec("a", "Ravi Kumar", "Ramaiah", 24, ps="Jayanagar PS", addr="12, Hebbal")
    b = rec("b", "Ravi Kumar", "Ramaiah", 44, ps="Jayanagar PS", addr="14, Hebbal")
    s = score_pair(a, b, M)
    assert "AGE_GAP" in s.vetoes and s.decision == "no_link"


def test_41_alias_linked():
    a = rec("a", "Syed Imran", "Abdul Rahim", 29, ps="Lashkar PS", addr="5, Hunsur")
    b = rec("b", "Imran @ Sheru", "Abdul Raheem", 29, ps="Lashkar PS", addr="5, Hunsur")
    c = rec("c", "Venkatesh urf Venki", "Mallesh", 33)
    d = rec("d", "Venki", "Mallesha", 33)
    assert score_pair(a, b, M).p >= 0.45  # at least reviewed, never silently dropped
    assert score_pair(c, d, M).features["alias_match"] == 1.0
    assert {"c", "d"} in resolve([c, d], M).clusters
    assert {"a", "b"} in resolve([a, b], M).clusters


def test_42_uncertain_pair_goes_to_review_not_merged():
    a = rec("a", "Anand Naik", None, None, district="Mysuru")
    b = rec("b", "A. Naik", None, 40, district="Mysuru")
    res = resolve([a, b], M)
    s = score_pair(a, b, M)
    assert s.decision in ("review", "no_link")
    assert {"a"} in res.clusters and {"b"} in res.clusters  # never auto-merged


def _person(db, name, cases=(), father=None):
    p = Person(canonical_name=name, relative_name_variants=[father] if father else [], name_variants=[])
    for c in cases:
        p.cases.append(c)
    db.add(p)
    db.flush()
    return p


def test_43_unmerge_restores_prior_state_with_audit(db):
    c1, c2 = Case(cnr="KA01", status="trial"), Case(cnr="KA02", status="trial")
    keep = _person(db, "Ravi Kumar", [c1], "Ramaiah")
    other = _person(db, "Ravikumar", [c2], "Ramayya")
    db.add(CustodyEvent(person_id=other.id, case_id=c2.id, type="judicial_custody", start=date(2025, 1, 1)))
    db.commit()
    ev = merge_persons(db, keep, other, None, 0.8)
    db.refresh(keep)
    assert {c.id for c in keep.cases} == {c1.id, c2.id}
    assert other.merged_into_id == keep.id and "Ravikumar" in keep.name_variants
    assert db.scalar(select(CustodyEvent.person_id)) == keep.id
    unmerge(db, ev, None)
    db.refresh(keep)
    db.refresh(other)
    assert [c.id for c in keep.cases] == [c1.id] and [c.id for c in other.cases] == [c2.id]
    assert other.merged_into_id is None and keep.name_variants == []
    assert db.scalar(select(CustodyEvent.person_id)) == other.id
    actions = [a.action for a in db.scalars(select(AuditLog).order_by(AuditLog.id))]
    assert actions == ["merge_persons", "unmerge_persons"]


def test_44_transferred_case_two_numbers_same_cnr_is_one_case(db):
    a = Case(cnr="KA01020001232024", case_numbers=["CC 12/2024"], court="JMFC-I", status="trial", first_remand_date=date(2024, 3, 1))
    b = Case(cnr="KA01020001232024", case_numbers=["CC 88/2024"], court="JMFC-III", status="trial")
    _person(db, "Basavaraj", [a])
    _person(db, "Basavaraju", [b])
    db.commit()
    merged = dedupe_cases_by_cnr(db)
    assert len(merged) == 1
    cases = db.scalars(select(Case)).all()
    assert len(cases) == 1 and cases[0].case_numbers == ["CC 12/2024", "CC 88/2024"]
    assert len(cases[0].persons) == 2  # both person records now point at one case → strong ER signal
    ra = rec("x", "Basavaraj", cnrs=[cases[0].cnr])
    rb = rec("y", "Basavaraju", cnrs=[cases[0].cnr])
    assert score_pair(ra, rb, M).decision == "link"
