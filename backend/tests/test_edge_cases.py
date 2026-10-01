"""Edge cases for adding prisoners (duplicates) and lawyer accounts (creation, approval, availability)."""
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.seed import DEMO_PASSWORD, seed

JAIL_A, JAIL_B = "Central Prison Parappana Agrahara", "Central Prison Mysuru"


@pytest.fixture(scope="module")
def client():
    settings.demo_mode = True
    seed(population=0, reset=True, verbose=False, full=False)  # exactly the two demo prisoners
    from app.main import app
    with TestClient(app) as c:
        yield c
    settings.demo_mode = False


def login(client, email, password=DEMO_PASSWORD):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, (email, r.text)
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def add(client, h, name, *, relative=None, dob=None, cnr=None, fir=None, ps=None, jail=JAIL_A, district="Bengaluru Urban",
        arrest_days_ago=40, section=("BNS", "303(2)")):
    arrest = settings.today() - timedelta(days=arrest_days_ago)
    return client.post("/api/persons", headers=h, json={
        "name": name, "relative_name": relative, "relation": "s/o" if relative else None, "dob": dob, "jail": jail,
        "district": district, "case": {"court": "JMFC", "cnr": cnr, "fir_number": fir, "police_station": ps,
                                       "arrest_date": arrest.isoformat(), "charges": [{"act": section[0], "section": section[1]}]}})


# ------------------------------------------------------------------ duplicates
@pytest.mark.parametrize("variant,expect", [
    # the two demo prisoners already exist: Ravi Kumar s/o Venkataramanappa, Suresh Kumar s/o Hanumanthappa
    (dict(name="Ravi Kumar", relative="Venkataramanappa", dob="SAME"), 409),              # exact same person
    (dict(name="RAVI KUMAR", relative="venkataramanappa", dob="SAME"), 409),              # capitals
    (dict(name="Ravikumar", relative="Venkataramanappa", dob="SAME"), 409),               # joined name
    (dict(name="Ravi Kumar", relative="Venkataramanappa", dob=None), 200),               # no DOB → review, not blocked
    (dict(name="Ravi Kumar", relative="Krishnappa", dob="SAME"), 200),                    # different father → different person
    (dict(name="Ravi Kumar", relative=None, dob="SAME"), 200),                            # father unknown → review
    (dict(name="Ravi Shankar", relative="Venkataramanappa", dob="SAME"), 200),            # different name
])
def test_duplicate_by_identity(client, variant, expect):
    jail, dlsa = login(client, "jail@nyayasetu.test"), login(client, "dlsa@nyayasetu.test")
    ravi = next(r for r in client.get("/api/register", headers=dlsa).json() if (r["demo_label"] or "").startswith("DEMO A"))
    lawyer = login(client, "lawyer@nyayasetu.test")
    dob = client.get(f"/api/persons/{ravi['id']}", headers=lawyer).json()["dob"]
    v = dict(variant)
    if v["dob"] == "SAME":
        v["dob"] = dob
    r = add(client, jail, v["name"], relative=v["relative"], dob=v["dob"])
    assert r.status_code == expect, r.text
    if expect == 409:
        assert "already exists" in r.json()["detail"] and "Ravi Kumar" in r.json()["detail"]


def test_duplicate_by_case_identifiers(client):
    jail = login(client, "jail@nyayasetu.test")
    assert add(client, jail, "Case Ident One", cnr="KA0888000012026", fir="77/2026", ps="Jayanagar PS").status_code == 200
    assert add(client, jail, "Totally Different", cnr=" ka0888-0000-12026 ").status_code == 409     # CNR, any format
    assert add(client, jail, "Totally Different", fir="77/2026", ps="JAYANAGAR P.S.").status_code == 409  # FIR + PS
    assert add(client, jail, "Totally Different", fir="77/2026", ps="Hebbal PS").status_code == 200   # same FIR no, other PS
    assert add(client, jail, "Totally Different Two", fir="77/2026").status_code == 200               # FIR without PS: not enough


def test_released_prisoner_cannot_be_re_added_by_cnr(client):
    jail = login(client, "jail@nyayasetu.test")
    r = add(client, jail, "Released Man", cnr="KA0777000012026")
    pid = r.json()["id"]
    client.post(f"/api/persons/{pid}/release", json={"date": settings.today().isoformat()}, headers=jail)
    again = add(client, jail, "Released Man", cnr="KA0777000012026", jail=None)
    assert again.status_code == 409  # re-arrest in the same case belongs on the existing record


def test_other_jail_staff_are_not_told_whose_record_it_is(client):
    admin, jail = login(client, "admin@nyayasetu.test"), login(client, "jail@nyayasetu.test")
    add(client, jail, "Private Record", cnr="KA0555000012026")
    client.post("/api/admin/users", headers=admin, json={"email": "jail.b@nyayasetu.test", "name": "Mysuru jail", "role": "jail_staff",
                                                         "password": "mysuru-pass-1", "jail": JAIL_B})
    jb = login(client, "jail.b@nyayasetu.test", "mysuru-pass-1")
    r = add(client, jb, "Anyone", cnr="KA0555000012026", jail=None, district="Mysuru")
    assert r.status_code == 409 and "Private Record" not in r.text and JAIL_A not in r.text


def test_other_validation_edge_cases(client):
    jail = login(client, "jail@nyayasetu.test")
    long_name = "Venkata " * 30
    assert add(client, jail, long_name.strip()).status_code == 200                      # very long name is fine
    assert add(client, jail, "A").status_code == 422                                     # too short
    assert add(client, jail, "  ").status_code == 422
    assert add(client, jail, "Future Arrest", arrest_days_ago=-5).status_code == 422      # arrest in the future
    assert add(client, jail, "Other Jail", jail=JAIL_B).status_code == 403              # only into their own jail
    assert add(client, jail, "Unknown Section", section=("IPC", "9999")).json()["status"] == "REVIEW"
    r = client.post("/api/persons", headers=jail, json={"name": "No Charges", "jail": JAIL_A, "district": "Bengaluru Urban",
                                                          "case": {"court": "JMFC", "charges": [], "arrest_date": "2026-01-01"}})
    assert r.status_code == 422
    r = client.post("/api/persons", headers=jail, json={"name": "Bad Date", "jail": JAIL_A, "district": "Bengaluru Urban",
                                                          "case": {"court": "JMFC", "charges": [{"act": "BNS", "section": "305"}],
                                                                   "arrest_date": "2026-02-30"}})
    assert r.status_code == 422                                                           # impossible date


# ------------------------------------------------------------------ lawyers
def test_new_lawyer_lifecycle_and_availability(client):
    dlsa = login(client, "dlsa@nyayasetu.test")
    r = client.post("/api/lawyers", headers=dlsa, json={"email": "Asha.Rao@NyayaSetu.test", "name": "Adv. Asha Rao",
                                                        "password": "asha-temp-pass", "approve": True})
    assert r.status_code == 200 and r.json()["status"] == "active" and r.json()["prisoners"] == 0
    uid = r.json()["id"]
    # available for assignment everywhere a lawyer is chosen
    assert any(x["id"] == uid and x["active"] for x in client.get("/api/lawyers", headers=dlsa).json())
    asha = login(client, "asha.rao@nyayasetu.test", "asha-temp-pass")                     # email is case-insensitive
    assert client.get("/api/persons", headers=asha).json() == []                          # starts with zero
    ravi = next(r for r in client.get("/api/register", headers=dlsa).json() if (r["demo_label"] or "").startswith("DEMO A"))
    assert client.post(f"/api/persons/{ravi['id']}/assign", json={"lawyer_id": uid}, headers=dlsa).status_code == 200
    assert [p["name"] for p in client.get("/api/persons", headers=asha).json()] == ["Ravi Kumar"]
    assert next(x for x in client.get("/api/lawyers", headers=dlsa).json() if x["id"] == uid)["prisoners"] == 1
    meera = client.get("/api/auth/me", headers=login(client, "lawyer@nyayasetu.test")).json()["id"]
    client.post(f"/api/persons/{ravi['id']}/assign", json={"lawyer_id": meera}, headers=dlsa)
    assert client.get("/api/persons", headers=asha).json() == []                          # reassigned away at once


def test_lawyer_account_edge_cases(client):
    admin, dlsa, jail = login(client, "admin@nyayasetu.test"), login(client, "dlsa@nyayasetu.test"), login(client, "jail@nyayasetu.test")

    def new(h, **kw):
        body = {"email": "x.lawyer@nyayasetu.test", "name": "Adv. X", "password": "long-enough-1", **kw}
        return client.post("/api/lawyers", headers=h, json=body)

    assert new(jail).status_code == 403                                                   # jail staff cannot create lawyers
    assert new(admin).status_code == 403                                                  # nor the (technical) admin
    assert client.post("/api/admin/users", headers=admin, json={"email": "x2@nyayasetu.test", "name": "X", "role": "legal_aid_lawyer",
                       "password": "long-enough-1"}).status_code == 422                    # no back door via user admin
    assert new(dlsa, password="short").status_code == 422                                 # password too short
    assert new(dlsa, email="not-an-email").status_code == 422
    assert new(dlsa, email="lawyer@nyayasetu.test").status_code == 409                    # email already used
    r = new(dlsa)                                                                          # DLSA can create; pending by default
    assert r.status_code == 200 and r.json()["status"] == "pending_approval"
    uid = r.json()["id"]
    assert client.post("/api/auth/login", json={"email": "x.lawyer@nyayasetu.test", "password": "long-enough-1"}).status_code == 401
    assert not next(x for x in client.get("/api/lawyers", headers=dlsa).json() if x["id"] == uid)["active"]  # not offered
    suresh = next(r for r in client.get("/api/register", headers=dlsa).json() if (r["demo_label"] or "").startswith("DEMO B"))
    assert client.post(f"/api/persons/{suresh['id']}/assign", json={"lawyer_id": uid}, headers=dlsa).status_code == 400
    assert client.post(f"/api/lawyers/{uid}/approve", headers=dlsa).status_code == 200
    assert client.post(f"/api/lawyers/{uid}/approve", headers=dlsa).status_code == 409   # already active
    x = login(client, "x.lawyer@nyayasetu.test", "long-enough-1")
    assert client.get("/api/persons", headers=x).json() == []
    assert client.post(f"/api/lawyers/{uid}/deactivate", headers=dlsa).status_code == 200
    assert client.get("/api/persons", headers=x).status_code == 401                        # token dead immediately
    assert client.post(f"/api/lawyers/{uid}/deactivate", headers=dlsa).status_code == 409
    not_a_lawyer = client.get("/api/auth/me", headers=jail).json()["id"]
    assert client.post(f"/api/lawyers/{not_a_lawyer}/deactivate", headers=dlsa).status_code == 404  # only lawyer accounts
    assert client.post(f"/api/persons/{suresh['id']}/assign", json={"lawyer_id": not_a_lawyer}, headers=dlsa).status_code == 400
