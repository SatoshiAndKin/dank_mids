"""Queued callers must resume together so the next RPC calls can form batches."""

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def rate_limit():
    # Use the established source harness to control the requester thread boundary.
    # Native integration tests exercise the compiled module against the real node.
    source = Path(__file__).resolve().parents[2] / "dank_mids/helpers/_rate_limit.py"
    spec = importlib.util.spec_from_file_location("rate_limit_admission_source", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _control_requester(module, monkeypatch):
    loop = asyncio.get_running_loop()
    release = asyncio.Event()
    endpoint = "http://example.invalid"
    pending = [object()]
    monkeypatch.setattr(module, "limiters", {endpoint: SimpleNamespace(_waiters=pending)})
    monkeypatch.setattr(module, "_requester", SimpleNamespace(loop=loop, is_alive=lambda: True))

    async def wait_for_queue(_endpoint):
        await release.wait()

    monkeypatch.setattr(module, "_rate_limit_inactive", wait_for_queue)
    return endpoint, pending, release


def test_rate_limit_releases_callers_as_one_batch(rate_limit, monkeypatch):
    async def run():
        endpoint, pending, release = _control_requester(rate_limit, monkeypatch)
        batches = []
        ready = []
        loop = asyncio.get_running_loop()

        def flush():
            batches.append(ready[:])
            ready.clear()

        async def caller(index):
            await rate_limit.rate_limit_inactive(endpoint)
            if not ready:
                loop.call_soon(flush)
            ready.append(index)

        callers = [asyncio.create_task(caller(index)) for index in range(64)]
        for _ in range(4):
            await asyncio.sleep(0)
        assert not any(caller.done() for caller in callers)
        pending.clear()
        release.set()
        await asyncio.gather(*callers)
        await asyncio.sleep(0)
        assert batches == [list(range(64))]
        assert not rate_limit.TASKS

    asyncio.run(run())


@pytest.mark.parametrize("failure", [None, RuntimeError("queue failed")])
def test_cancelled_caller_does_not_cancel_other_waiters(rate_limit, monkeypatch, failure):
    async def run():
        endpoint, pending, release = _control_requester(rate_limit, monkeypatch)
        errors = []
        asyncio.get_running_loop().set_exception_handler(
            lambda _loop, context: errors.append(context)
        )

        async def finish_queue(_endpoint):
            await release.wait()
            if failure is not None:
                raise failure

        monkeypatch.setattr(rate_limit, "_rate_limit_inactive", finish_queue)
        callers = [asyncio.create_task(rate_limit.rate_limit_inactive(endpoint)) for _ in range(3)]
        for _ in range(4):
            await asyncio.sleep(0)
        callers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await callers[0]
        assert not any(caller.done() for caller in callers[1:])
        pending.clear()
        release.set()
        results = await asyncio.gather(*callers[1:], return_exceptions=True)
        await asyncio.sleep(0)
        assert results == [failure, failure]
        assert not errors
        assert not rate_limit.TASKS

    asyncio.run(run())


def test_inactive_queue_and_failed_requester(rate_limit, monkeypatch):
    async def run():
        endpoint, pending, _release = _control_requester(rate_limit, monkeypatch)
        failure = RuntimeError("requester stopped")
        monkeypatch.setattr(
            rate_limit, "_requester", SimpleNamespace(is_alive=lambda: False, _exc=failure)
        )
        with pytest.raises(RuntimeError, match="requester stopped") as caught:
            await rate_limit.rate_limit_inactive(endpoint)
        assert caught.value is failure
        pending.clear()
        assert await rate_limit.rate_limit_inactive(endpoint) is None

    asyncio.run(run())


@pytest.mark.parametrize("failure", [None, RuntimeError("shared drain failed")])
def test_requester_shares_drain_completion_and_errors(rate_limit, monkeypatch, failure):
    async def run():
        endpoint = "http://example.invalid"
        monkeypatch.setattr(
            rate_limit, "limiters", {endpoint: SimpleNamespace(_waiters=[object()])}
        )
        release = asyncio.Event()
        started = asyncio.Event()
        drain_calls = 0

        async def drain(_endpoint):
            nonlocal drain_calls
            drain_calls += 1
            started.set()
            await release.wait()
            if failure is not None:
                raise failure

        monkeypatch.setattr(rate_limit, "__rate_limit_inactive", drain)
        callers = [asyncio.create_task(rate_limit._rate_limit_inactive(endpoint)) for _ in range(3)]
        await started.wait()
        callers[0].cancel()
        with pytest.raises(asyncio.CancelledError):
            await callers[0]
        assert drain_calls == 1
        assert not any(caller.done() for caller in callers[1:])
        release.set()
        # Bound a broken shared-error path so the regression reports a failure.
        results = await asyncio.wait_for(
            asyncio.gather(*callers[1:], return_exceptions=True), timeout=1
        )
        assert results == [failure, failure]
        assert not rate_limit._rate_limit_tasks

    asyncio.run(run())
