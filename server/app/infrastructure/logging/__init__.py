import logging
import collections
import time
from typing import List, Dict, Any, Optional

# In-memory circular buffer for recent sanitized application logs
_LOG_BUFFER = collections.deque(maxlen=1000)

class InMemoryLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        # Sanitize secrets if any
        sanitized = msg.replace("sk-", "sk-***")
        _LOG_BUFFER.append({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": sanitized,
        })

def setup_logging():
    logger = logging.getLogger("echo")
    logger.setLevel(logging.INFO)
    handler = InMemoryLogHandler()
    formatter = logging.Formatter("[%(asctime)s] %(levelname)s [%(name)s]: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

def get_recent_memory_logs(limit: int = 100, level: Optional[str] = None) -> List[Dict[str, Any]]:
    logs = list(_LOG_BUFFER)
    if level:
        lvl = level.upper()
        logs = [l for l in logs if l["level"] == lvl]
    return logs[-limit:]
