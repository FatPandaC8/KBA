import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .infrastructure.config import get_settings
from .infrastructure.logging import setup_logging
import numpy as np
from .domain.entities import KnowledgeItemEntity
from .api.dependencies import get_container
from .api.routes.client import router as client_router
from .api.routes.admin import admin_router

# Setup unified logging
setup_logging()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Modern FastAPI Lifespan context
    container = get_container()
    # Backfill embeddings on startup safely
    container.backfill_embeddings_uc.execute()
    yield

settings = get_settings()
container = get_container()
# Backward-compatibility alias for legacy test fixtures
pipeline = container.extractor
pipeline.embed_knowledge_item = lambda item: np.frombuffer(container.embedder.embed_item(KnowledgeItemEntity(
    id=item.id,
    capture_id=item.capture_id,
    title=item.title,
    core_idea=item.core_idea,
    details=item.details,
    transcript=item.transcript,
    concepts=item.concepts,
    tags=item.tags,
    open_questions=item.open_questions,
    candidate_relations=item.candidate_relations,
    provenance=item.provenance,
    created_at=item.created_at,
    updated_at=item.updated_at,
)), dtype=np.float32)

app = FastAPI(
    title="Echo Knowledge API",
    version=settings.pipeline_version,
    lifespan=lifespan,
)

# Standard CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount Routes
app.include_router(client_router)
app.include_router(admin_router)

# Mount Admin Web Interface
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/admin-assets", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/admin", include_in_schema=False)
@app.get("/admin/", include_in_schema=False)
def serve_admin():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))

# Root redirect or information
@app.get("/", include_in_schema=False)
def index():
    return {
        "service": "Echo Knowledge Backend",
        "version": settings.pipeline_version,
        "docs": "/docs",
        "admin": "/admin",
    }
