from alembic.config import Config
from app.config import DATABASE_URL

cfg = Config()
cfg.set_main_option("script_location", "alembic")
cfg.set_main_option("sqlalchemy.url", DATABASE_URL)
