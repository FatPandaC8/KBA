"""Application configuration. Loaded once at startup from env / .env."""
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL: str = os.environ["DATABASE_URL"]
JWT_SECRET: str = os.environ["JWT_SECRET"]
ADMIN_SEED_USERNAME: str = os.environ.get("ADMIN_SEED_USERNAME", "admin")
ADMIN_SEED_PASSWORD: str = os.environ.get("ADMIN_SEED_PASSWORD", "admin")
ADMIN_SEED_EMAIL: str = os.environ.get("ADMIN_SEED_EMAIL", "admin@local")

# ponytail: single source of truth for tunables; bump these, don't restructure.
EXTRACTION_AUTO_SAVE_CONFIDENCE = 0.9
MAX_NOTE_LENGTH = 8000
MAX_AUDIO_UPLOAD_BYTES = 25 * 1024 * 1024
GRAPH_MAX_DEPTH = 3
GRAPH_MAX_RESULTS = 100
SEARCH_LIMIT = 50
AUDIO_TTL_MINUTES = 10