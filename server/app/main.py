"""FastAPI application entrypoint."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import admin as admin_routes
from app.api.routes import auth as auth_routes
from app.api.routes import knowledge as knowledge_routes
from app.api.routes import notes as notes_routes


@asynccontextmanager
async def _lifespan(app: FastAPI):
    from sqlalchemy.orm import Session

    from app.admin_service import seed_initial_admin
    from app.db import SessionLocal

    db = SessionLocal()
    try:
        seed_initial_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(title="KBA", version="0.1.0", lifespan=_lifespan)
app.include_router(auth_routes.router)
app.include_router(admin_routes.router)
app.include_router(notes_routes.router)
app.include_router(knowledge_routes.router)


@app.get("/health/live")
def health_live():
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    return {"status": "ok"}
