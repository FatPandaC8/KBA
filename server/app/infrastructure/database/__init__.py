import os
import sqlite3
import threading
from typing import Optional

_LOCAL = threading.local()

class DatabaseManager:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)

    def get_connection(self) -> sqlite3.Connection:
        # Use thread-local connection for clean pooling per thread
        conn = getattr(_LOCAL, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            # Enable WAL mode and foreign key constraints for high concurrency
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            _LOCAL.conn = conn
        return conn

    def init_database(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        c.execute("""
        CREATE TABLE IF NOT EXISTS captures (
            id TEXT PRIMARY KEY,
            idempotency_key TEXT UNIQUE,
            audio_path TEXT,
            duration_ms INTEGER,
            status TEXT,
            created_at TEXT
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_items (
            id TEXT PRIMARY KEY,
            capture_id TEXT UNIQUE,
            title TEXT,
            core_idea TEXT,
            details TEXT DEFAULT '',
            transcript TEXT,
            concepts TEXT,
            tags TEXT,
            open_questions TEXT,
            candidate_relations TEXT DEFAULT '[]',
            provenance TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """)
        # Safe column additions if needed
        try:
            c.execute("ALTER TABLE knowledge_items ADD COLUMN details TEXT DEFAULT ''")
        except Exception:
            pass
        try:
            c.execute("ALTER TABLE knowledge_items ADD COLUMN candidate_relations TEXT DEFAULT '[]'")
        except Exception:
            pass

        c.execute("""
        CREATE TABLE IF NOT EXISTS relationships (
            id TEXT PRIMARY KEY,
            from_id TEXT,
            to_id TEXT,
            relation_type TEXT,
            status TEXT,
            created_at TEXT,
            UNIQUE(from_id, to_id, relation_type)
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS model_eval_records (
            id TEXT PRIMARY KEY,
            capture_id TEXT,
            transcript TEXT,
            structured_json TEXT,
            user_corrected INTEGER DEFAULT 0,
            consent_given INTEGER DEFAULT 0,
            pipeline_version TEXT,
            created_at TEXT
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS knowledge_embeddings (
            item_id TEXT PRIMARY KEY,
            embedding BLOB,
            updated_at TEXT
        );
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS processing_jobs (
            id TEXT PRIMARY KEY,
            capture_id TEXT,
            stage TEXT,
            status TEXT,
            duration_ms INTEGER,
            error_message TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """)

        # Performance optimization: Strategic query indexes
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_created_at ON knowledge_items(created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_knowledge_capture_id ON knowledge_items(capture_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_from_to ON relationships(from_id, to_id);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_relationships_status ON relationships(status);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_captures_created ON captures(created_at DESC);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_eval_consent ON model_eval_records(consent_given);")
        c.execute("CREATE INDEX IF NOT EXISTS idx_processing_jobs_capture ON processing_jobs(capture_id);")

        conn.commit()
        conn.close()
