"""تطبيق Medify — FastAPI، القاعدة /api/v1 (DOC-05 حصراً)."""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .analytics import track
from .config import get_settings
from .errors import MedifyError
from .ratelimit import enforce_rate_limit

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("medify")

app = FastAPI(
    title="Medify API",
    version=get_settings().app_version,
    docs_url="/api/v1/docs",
    openapi_url="/api/v1/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[get_settings().frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["ETag", "Retry-After"],
)


@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """حصر المعدل — DOC-05 §١ (أشد على نقاط AI)."""
    if request.url.path.startswith("/api/v1") and request.url.path != "/api/v1/health":
        identity = request.headers.get("Authorization", request.client.host if request.client else "anon")[-48:]
        try:
            enforce_rate_limit(identity, request.url.path)
        except MedifyError as exc:
            return JSONResponse(status_code=exc.http_status, content=exc.body(), headers=exc.headers)
    return await call_next(request)


@app.exception_handler(MedifyError)
async def medify_error_handler(request: Request, exc: MedifyError):
    if exc.http_status >= 500:
        # الرموز 50xx تُسجل في التتبع دون محتوى سريري (DOC-13 §٤)
        try:
            track("error.5xx", exc.details.get("facility_id", "unknown"), "system", mdf_code=exc.code)
        except Exception:
            pass
    return JSONResponse(status_code=exc.http_status, content=exc.body(), headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """لا رمز تحقق عام في الـ22 — تغليف بـ MDF-5001 مع التفاصيل (D-25)."""
    error = MedifyError("MDF-5001", details={"validation": exc.errors()})
    return JSONResponse(status_code=422, content=error.body())


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    logger.exception("خطأ غير معالج على %s", request.url.path)
    error = MedifyError("MDF-5001", details={"trace_id": getattr(request.state, "trace_id", None)})
    return JSONResponse(status_code=500, content=error.body())


@app.get("/api/v1/health")
def health():
    return {"data": {"status": "ok", "version": get_settings().app_version}, "meta": {}}


from .api.v1 import (  # noqa: E402
    admin_settings,
    approvals,
    auth,
    clinics_doctors,
    facilities,
    notifications,
    summary,
    templates,
    visits,
    ws_transcribe,
)

API = "/api/v1"
app.include_router(auth.router, prefix=API, tags=["auth"])
app.include_router(facilities.router, prefix=API, tags=["facility"])
app.include_router(clinics_doctors.router, prefix=API, tags=["clinics-doctors"])
app.include_router(admin_settings.router, prefix=API, tags=["admin"])
app.include_router(templates.router, prefix=API, tags=["templates"])
app.include_router(visits.router, prefix=API, tags=["visits"])
app.include_router(summary.router, prefix=API, tags=["summary"])
app.include_router(approvals.router, prefix=API, tags=["approvals"])
app.include_router(notifications.router, prefix=API, tags=["notifications"])
app.include_router(ws_transcribe.router, tags=["ws"])
