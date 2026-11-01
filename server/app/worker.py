"""Dedicated worker process entrypoint (ADR D8).

Run as:  python -m app.worker     (from the ``server/`` directory)

- Owns its own pool plus container; the API process never starts a worker loop.
- SIGTERM/SIGINT: finish the current job (or release its lease if asked to
  stop immediately), then exit 0.
- On startup it reclaims stale leases (a restart may have died mid-job);
  each loss costs one attempt per the owner-confirmed rule.
"""

import logging
import os
import signal
import threading
import time
import uuid

from server.app.api.dependencies import Container
from server.app.infrastructure.config import get_settings

logger = logging.getLogger("echo.worker")


class WorkerRunner:
    def __init__(self, container: Container, poll_seconds: float = 1.0):
        self.container = container
        self.poll_seconds = poll_seconds
        self.worker_id = os.environ.get("ECHO_WORKER_ID") or f"worker-{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._draining = False

    def request_stop(self, signum=None, frame=None) -> None:
        logger.info("worker stop requested sig=%s", signum)
        self._stop.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    def reclaim_on_boot(self) -> int:
        affected = self.container.process_capture_uc.job_repo.reclaim_stale(
            self.container.settings.job_max_attempts
        )
        if affected:
            logger.info("reclaimed stale jobs count=%s", affected)
        return affected

    def run_once(self) -> bool:
        """Process at most one job; True when one was claimed."""
        result = self.container.process_capture_uc.process_next(self.worker_id)
        return result is not None

    def run_forever(self) -> int:
        self.reclaim_on_boot()
        idle_poll = self.poll_seconds
        while not self._stop.is_set():
            processed = None
            try:
                processed = self.run_once()
            except Exception:  # loop survivability (R5)
                logger.exception("worker iteration failed")
            if processed:
                continue
            self._stop.wait(idle_poll)
        logger.info("worker exited cleanly worker_id=%s", self.worker_id)
        return 0


def main() -> int:
    settings = get_settings()
    container = Container(settings)
    container.open_database()
    runner = WorkerRunner(container, poll_seconds=settings.job_poll_seconds)
    signal.signal(signal.SIGTERM, runner.request_stop)
    signal.signal(signal.SIGINT, runner.request_stop)
    logger.info(
        "echo worker started worker_id=%s max_attempts=%s backoff=%s/%sj",
        runner.worker_id,
        settings.job_max_attempts,
        settings.job_backoff_a1_seconds,
        settings.job_backoff_a2_seconds,
    )
    try:
        return runner.run_forever()
    finally:
        container.close_database()


if __name__ == "__main__":
    logging.basicConfig(
        level=os.environ.get("ECHO_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    raise SystemExit(main())
