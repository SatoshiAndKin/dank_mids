"""The requester must finish cleanup before stopping its event loop."""

import asyncio
import atexit
import importlib.util
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "dank_mids/helpers/_requester.py"


@pytest.mark.parametrize("open_session", [False, True])
def test_source_shutdown_closes_session_thread_and_loop(open_session):
    spec = importlib.util.spec_from_file_location("requester_shutdown_source", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    requester = module._requester
    session = None
    if open_session:

        async def get_session():
            return requester.session

        session = asyncio.run_coroutine_threadsafe(get_session(), requester.loop).result(timeout=2)
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        executor.submit(module.shutdown_http_requester).result(timeout=2)
        assert not requester.is_alive()
        assert requester.loop.is_closed()
        if session is not None:
            assert session.closed
        module.shutdown_http_requester()
    finally:
        atexit.unregister(module.shutdown_http_requester)
        executor.shutdown(wait=False, cancel_futures=True)


@pytest.mark.parametrize("open_session", [False, True])
def test_installed_requester_process_exits_cleanly(open_session):
    code = f"""
import asyncio
from dank_mids.helpers import _requester as module
requester = module._requester
if {open_session!r}:
    async def get_session():
        return requester.session
    session = asyncio.run_coroutine_threadsafe(get_session(), requester.loop).result(timeout=2)
module.shutdown_http_requester()
assert not requester.is_alive()
assert requester.loop.is_closed()
if {open_session!r}:
    assert session.closed
module.shutdown_http_requester()
print(module.__file__)
"""
    result = subprocess.run(
        [sys.executable, "-c", code], check=True, text=True, capture_output=True, timeout=10
    )
    assert "_requester" in result.stdout
