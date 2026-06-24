"""SignalFlow API - AI Visibility and Community Engagement Platform.

Backend API server using FastAPI with Supabase for authentication and database.
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.routes import router as v1_router
from app.core.config import get_settings
from app.core.exceptions import AppError
from app.core.logging import setup_logging
from app.db.supabase_client import get_supabase_client
from app.middleware import RateLimitMiddleware, RequestTracingMiddleware
from app.services.infrastructure.llm.providers._registry import get_configured_providers

setup_logging("INFO")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler.

    In the Supabase era, we don't create tables automatically since
    Supabase manages the schema. Tables should be created via Supabase
    dashboard, migrations, or SQL scripts.
    """
    logger.info("Starting SignalFlow API...")
    workers = os.environ.get("WEB_CONCURRENCY") or os.environ.get("UVICORN_WORKERS") or "1"
    if workers.isdigit() and int(workers) > 1:
        logger.warning(
            "Running with %s workers: the in-memory rate limiter and HTTP budget are "
            "per-process, so effective limits multiply by the worker count. Swap in a "
            "shared RateLimitBackend (app/middleware.py) before scaling out.",
            workers,
        )
    if settings.environment == "development" and not settings.supabase_secret_key:
        logger.warning(
            "SUPABASE_SECRET_KEY is not configured. Falling back to SUPABASE_PUBLISHABLE_KEY for local DB access; "
            "email/password registration and other admin-only auth flows will remain unavailable until the service role key is set."
        )
    configured_providers = get_configured_providers()
    if configured_providers:
        logger.info("Configured LLM providers: %s", ", ".join(sorted(configured_providers)))
    else:
        logger.warning(
            "No LLM provider is configured. Set GEMINI_API_KEY in the repo root .env.local, "
            "or configure another provider and restart the backend."
        )
    # Run pending schema migrations
    try:
        from app.db.run_migrations import run_migrations

        applied = run_migrations()
        if applied:
            logger.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
        else:
            logger.info("No pending migrations.")
    except Exception:
        logger.exception("Migration runner failed — continuing startup")
    logger.info("SignalFlow API started successfully.")
    yield
    logger.info("Shutting down SignalFlow API.")


settings = get_settings()
app = FastAPI(
    title="SignalFlow API",
    description="AI Visibility and Community Engagement Platform",
    version="2.1.0",
    lifespan=lifespan,
)

origins = [o.strip() for o in (settings.cors_origins_raw or "http://localhost:3000").split(",")]

# Starlette executes middleware in reverse order of addition.
# CORSMiddleware MUST be added last so it runs first — otherwise rate-limit
# or tracing responses won't carry CORS headers and the browser will block them.
app.add_middleware(RequestTracingMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)
app.include_router(v1_router)


@app.exception_handler(AppError)
async def app_exception_handler(request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(request, exc: RuntimeError):
    """Catch LLM/provider runtime errors and return a structured 503 response."""
    logger.error("RuntimeError in request handler: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc: Exception):
    """Catch-all for any unhandled exception. Returns a generic 500.

    Logs the full traceback so the error is debuggable without leaking
    internals to the client (Issue #61).
    """
    logger.exception("Unhandled %s in %s %s", type(exc).__name__, request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )


def _service_checks() -> dict[str, str]:
    """Check service health (API + Supabase database)."""
    checks = {"api": "ok"}
    try:
        supabase = get_supabase_client()
        # Actually query the database to verify connectivity
        supabase.table("account_users").select("id").limit(1).execute()
        checks["database"] = "ok"
    except Exception as e:
        logger.error("Supabase health check failed: %s", e)
        checks["database"] = "error"
    return checks


@app.get("/health")
def health_check():
    """Health check endpoint."""
    checks = _service_checks()
    status = "healthy" if all(value == "ok" for value in checks.values()) else "degraded"
    return {"status": status, "checks": checks}


@app.get("/ready")
def readiness_check():
    """Readiness check endpoint."""
    checks = _service_checks()
    ready = all(value == "ok" for value in checks.values())
    payload = {"status": "ready" if ready else "not_ready", "checks": checks}
    return JSONResponse(content=payload, status_code=200 if ready else 503)


@app.get("/")
def root():
    """Root endpoint."""
    return {"name": "SignalFlow API", "version": "2.1.0", "status": "running"}
