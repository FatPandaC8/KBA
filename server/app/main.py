import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .api.dependencies import get_container
from .api.routes.admin import admin_router
from .api.routes.auth import account_router, consent_router, router as auth_router
from .api.routes.client import protected_router as protected_client_router
from .api.routes.client import router as client_router
from .domain.errors import (
    AudioProcessingError,
    AuthError,
    ConsentRequiredError,
    EntityNotFoundError,
    InvalidInputAudioError,
    ProviderError,
    ProviderNetworkError,
    ProviderNotConfiguredError,
    ProviderSchemaError,
    QuotaExhaustedError,
    RateLimitedError,
    ValidationError,
)
from .infrastructure.config import get_settings
from .infrastructure.logging import setup_logging

setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    container = get_container()
    container.open_database()
    # The worker resumes jobs whose lease expired during a restart (PRC-03).
    if container.settings.worker_enabled:
        container.worker.start()
    try:
        yield
    finally:
        container.worker.stop()
        container.close_database()


settings = get_settings()

_logging = __import__("logging")
_logging.getLogger("echo").info(
    "DATABASE_URL configured | ECHO_ENV: %s | consent_version: %s | worker_enabled: %s",
    settings.app_env,
    settings.consent_version,
    settings.worker_enabled,
)

app = FastAPI(
    title="Echo Knowledge API",
    version=settings.pipeline_version,
    lifespan=lifespan,
)

# Enable gzip compression for responses larger than 500 bytes.
app.add_middleware(GZipMiddleware, minimum_size=500)

# CORS is disabled unless explicitly configured. The Android client does not
# need CORS, and the admin UI is served from the same origin.
cors_origins = settings.cors_origin_list
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Session-Token"],
    )


@app.exception_handler(ValidationError)
async def _validation_error(_request: Request, exc: ValidationError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(EntityNotFoundError)
async def _not_found(_request: Request, exc: EntityNotFoundError):
    return JSONResponse(status_code=404, content={"detail": "Resource not found."})


@app.exception_handler(AuthError)
async def _auth_error(_request: Request, exc: AuthError):
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc)},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(ConsentRequiredError)
async def _consent_error(_request: Request, exc: ConsentRequiredError):
    return JSONResponse(status_code=403, content={"detail": str(exc)})


@app.exception_handler(RateLimitedError)
async def _rate_limited(_request: Request, exc: RateLimitedError):
    return JSONResponse(
        status_code=429,
        content={"detail": str(exc)},
        headers={"Retry-After": str(exc.retry_after)},
    )


@app.exception_handler(ProviderNotConfiguredError)
async def _provider_missing(_request: Request, exc: ProviderNotConfiguredError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(AudioProcessingError)
async def _audio_error(_request: Request, exc: AudioProcessingError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(InvalidInputAudioError)
async def _invalid_audio(_request: Request, exc: InvalidInputAudioError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(QuotaExhaustedError)
async def _quota(_request: Request, exc: QuotaExhaustedError):
    headers = {}
    if getattr(exc, "retry_after", 0):
        headers["Retry-After"] = str(exc.retry_after)
    return JSONResponse(status_code=429, content={"detail": str(exc)}, headers=headers)


@app.exception_handler(ProviderNetworkError)
async def _network(_request: Request, exc: ProviderNetworkError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(ProviderSchemaError)
async def _schema(_request: Request, exc: ProviderSchemaError):
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(ProviderError)
async def _provider(_request: Request, exc: ProviderError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


app.include_router(auth_router)
app.include_router(consent_router)
app.include_router(account_router)
app.include_router(client_router)
app.include_router(protected_client_router)
app.include_router(admin_router)

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
ADMIN_BUILD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../admin/dist"))
if os.path.exists(STATIC_DIR):
    app.mount("/admin-assets", StaticFiles(directory=STATIC_DIR), name="static")
if os.path.exists(ADMIN_BUILD_DIR):
    app.mount("/admin-app", StaticFiles(directory=ADMIN_BUILD_DIR, html=True), name="admin-app")


@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def serve_admin():
    built = os.path.join(ADMIN_BUILD_DIR, "index.html")
    return FileResponse(built if os.path.exists(built) else os.path.join(STATIC_DIR, "index.html"))


@app.get("/", include_in_schema=False)
def index():
    return {
        "service": "Echo Knowledge Backend",
        "version": settings.pipeline_version,
        "docs": "/docs",
        "admin": "/admin",
    }
