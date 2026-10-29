"""Single-process background worker for persisted processing jobs.

SQLite is the queue: the worker only claims rows with an expired or absent
lease, so a restarted process resumes work without a message broker (PRC-02).
"""

import logging
import threading
import uuid

from server.app.application.use_cases.jobs import ProcessCaptureUseCase

logger = logging.getLogger(__name__)


class JobWorker:
    def __init__(self, use_case: ProcessCaptureUseCase, poll_interval: float = 1.0):
        self.use_case = use_case
        self.poll_interval = poll_interval
        self.worker_id = f"worker-{uuid.uuid4()}"
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="echo-job-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    def kick(self) -> None:
        """Wake the worker immediately after a new upload."""
        self._wake.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                processed = self.use_case.process_next(self.worker_id)
            except Exception:
                logger.exception("Job worker iteration failed")
                processed = None
            if processed is not None:
                self._wake.clear()
                continue
            self._wake.wait(self.poll_interval)
            self._wake.clear()
