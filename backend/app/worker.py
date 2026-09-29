"""Celery worker: nightly monitoring + background document processing.

    celery -A app.worker worker -B --loglevel=info
"""
from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery("nyayasetu", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.beat_schedule = {
    "nightly-monitoring": {"task": "app.worker.nightly", "schedule": crontab(hour=1, minute=30)},
}
celery_app.conf.timezone = "Asia/Kolkata"


@celery_app.task(name="app.worker.nightly")
def nightly() -> dict:
    from dataclasses import asdict

    from app.db import SessionLocal
    from app.monitoring.alerts import run_nightly
    with SessionLocal() as db:
        return asdict(run_nightly(db))


@celery_app.task(name="app.worker.refresh_person")
def refresh_person(person_id: str) -> str:
    from app.db import SessionLocal
    from app.defense.service import refresh_insights
    from app.models import Person
    from app.monitoring.alerts import alerts_for
    from app.services.eligibility import compute_for_person
    with SessionLocal() as db:
        p = db.get(Person, person_id)
        if p is None:
            return "missing"
        out = compute_for_person(db, p)
        alerts_for(db, p, out, settings.today(), reason="document")
        refresh_insights(db, p)
        db.commit()
        return out.row.status
