"""
Test-wide setup: an isolated SQLite file per test session and the background
delivery worker disabled, both set via environment variables BEFORE `main` (or
anything that imports config/database) is imported anywhere -- pytest loads
conftest.py before collecting sibling test modules, which is what makes this
work.

With the worker disabled, delivery only happens when a test explicitly calls
services.delivery_queue.process_all_pending() (directly, or via the `post()`
helpers most test files define) -- deterministic, no timing-dependent
assertions anywhere in the suite.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_DB_PATH = os.path.join(tempfile.gettempdir(), "crop_advisory_test.db")
for suffix in ("", "-wal", "-shm"):
    try:
        os.remove(_DB_PATH + suffix)
    except OSError:
        pass

os.environ["DATABASE_URL"] = f"sqlite:///{_DB_PATH}"
os.environ["ENABLE_DELIVERY_WORKER"] = "false"

import pytest

import state_manager
from database import init_db

# Some test modules (test_rules.py, test_integrations.py) never import main.py,
# so main's module-level init_db() call wouldn't run for them -- do it here
# unconditionally instead, once, before any test's autouse fixture needs tables
# to already exist.
init_db()


@pytest.fixture(autouse=True)
def _reset_db_between_tests():
    """Every test starts from a clean database, mirroring the old `_STATE_STORE.clear()`."""
    state_manager.reset_all_state_for_tests()
    yield
    state_manager.reset_all_state_for_tests()
