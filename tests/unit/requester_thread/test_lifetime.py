"""Compiled requester methods must preserve threading.Thread's object lifetime."""

import os
import subprocess
import sys


def test_requester_threads_release_weak_references_before_process_exit():
    code = """
import gc
import weakref
from tests.unit._runtime import assert_test_runtime
from dank_mids.helpers import _requester

assert_test_runtime(_requester)
for _ in range(3):
    thread = _requester.HTTPRequesterThread()
    reference = weakref.ref(thread)
    thread.loop.call_soon_threadsafe(thread.loop.stop)
    thread.join(timeout=2)
    assert not thread.is_alive()
    del thread
    gc.collect()
    assert reference() is None
_requester.shutdown_http_requester()
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "PYTHONMALLOC": "debug", "PYTHONFAULTHANDLER": "1"},
        text=True,
        capture_output=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr
