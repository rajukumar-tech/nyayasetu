from __future__ import annotations

import json
import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.core.config import settings
from app.db import create_all


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": record.getMessage()}
        for k in ("request_id", "path", "status", "ms"):
            if hasattr(record, k):
                out[k] = getattr(record, k)
        return json.dumps(out)


_h = logging.StreamHandler()
_h.setFormatter(JsonFormatter())
logging.basicConfig(level=logging.INFO, handlers=[_h], force=True)
log = logging.getLogger("nyayasetu.http")

app = FastAPI(title="NyayaSetu API", version="1.0.0",
              description="Decision support for legal-aid lawyers. Not legal advice. Deterministic eligibility; "
                          "LLMs never decide.")
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True, allow_methods=["*"],
                   allow_headers=["*"], expose_headers=["Content-Disposition"])


@app.middleware("http")
async def request_log(request: Request, call_next):
    rid = uuid.uuid4().hex[:10]
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:  # noqa: BLE001
        log.exception("unhandled error", extra={"request_id": rid, "path": request.url.path})
        return JSONResponse({"detail": "Something went wrong on our side. The error has been logged "
                                       f"(reference {rid})."}, status_code=500)
    response.headers["X-Request-ID"] = rid
    log.info("request", extra={"request_id": rid, "path": request.url.path, "status": response.status_code,
                               "ms": round((time.perf_counter() - t0) * 1000, 1)})
    return response


@app.on_event("startup")
def _startup() -> None:
    create_all()


app.include_router(router)
