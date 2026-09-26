"""
The background delivery worker: polls for due DeliveryJob rows and processes
them. Started/stopped as plain module-level calls from main.py (not a FastAPI
lifespan hook) -- consistent with this codebase's existing style of doing
startup checks as plain top-level code, and it sidesteps any ambiguity about
whether lifespan events fire for a bare `TestClient(app)` used without a
`with` block (as every existing test does).

Tests set ENABLE_DELIVERY_WORKER=false (see tests/conftest.py) so delivery
only happens when a test explicitly calls
services.delivery_queue.process_all_pending() -- deterministic, no
timing-dependent assertions.
"""
import logging
import threading

from config import WORKER_POLL_INTERVAL_SECONDS
from services.delivery_queue import process_all_pending

log = logging.getLogger("worker")

_thread = None
_stop_event = threading.Event()


def _run():
    while not _stop_event.is_set():
        try:
            process_all_pending()
        except Exception:
            log.exception("delivery worker poll iteration failed")
        _stop_event.wait(WORKER_POLL_INTERVAL_SECONDS)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run, name="delivery-worker", daemon=True)
    _thread.start()


def stop(timeout: float = 5.0):
    global _thread
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=timeout)
        _thread = None
