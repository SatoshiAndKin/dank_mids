"""Retried HTTP outcomes must not stay owned by a pending replacement attempt."""

import asyncio
import gc
from threading import RLock
from types import SimpleNamespace
import weakref

from aiohttp import ClientResponseError
import pytest

from dank_mids import _requests
from dank_mids._requests import RPCRequest
from dank_mids.helpers._codec import decode_raw
from dank_mids.retry_observer import register_retry_observer, unregister_retry_observer


class Payload:
    def __init__(self):
        self.buffer = bytearray(128 * 1024)


class Controller:
    max_jsonrpc_batch_size = 1000
    endpoint = "http://example.invalid"

    def __init__(self, operation):
        self._loop = asyncio.get_running_loop()
        self.pools_closed_lock = RLock()
        self.pending_rpc_calls = []
        self.make_request = operation


@pytest.mark.parametrize("cancel", [False, True])
def test_http_408_releases_failed_attempts_before_replacement_finishes(cancel):
    async def check():
        started, release = asyncio.Event(), asyncio.Event()
        references, calls, events = [], [], []
        expected = decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x1"}')

        async def operation(method, params, request_id):
            calls.append((method, params, request_id))
            if len(calls) <= 8:
                payload = Payload()
                references.append(weakref.ref(payload))
                raise ClientResponseError(
                    SimpleNamespace(real_url="http://example.invalid"),
                    (),
                    status=408,
                    message="request timeout",
                )
            started.set()
            await release.wait()
            return expected

        def observer(event):
            events.append((event.attempt, type(event.error), event.metadata))

        request = RPCRequest(Controller(operation), "eth_blockNumber", [], uid="same")
        register_retry_observer(observer)
        task = asyncio.create_task(request.make_request())
        try:
            await asyncio.wait_for(started.wait(), 2)
            await asyncio.sleep(0)
            gc.collect()
            assert len(references) == 8
            assert [ref() for ref in references] == [None] * 8
            assert calls == [("eth_blockNumber", [], "same")] * 9
            assert events == [
                (index, ClientResponseError, {"status": "408"}) for index in range(1, 9)
            ]
            if cancel:
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                release.set()
                assert await task is expected
                assert request._fut.result() is expected
        finally:
            unregister_retry_observer(observer)
            release.set()
            await asyncio.gather(task, return_exceptions=True)
            if not request._fut.done():
                request._fut.cancel()

    asyncio.run(check())


def test_success_keeps_response_and_request_identity():
    async def check():
        calls = []
        expected = decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x1"}')

        async def operation(method, params, request_id):
            calls.append((method, params, request_id))
            return expected

        params = [{"to": "0x1234"}, "0xabc"]
        request = RPCRequest(Controller(operation), "eth_call", params, uid="same")
        assert await request.make_request() is expected
        assert request._fut.result() is expected
        assert calls == [("eth_call", params, "same")]
        assert calls[0][1] is params

    asyncio.run(check())


@pytest.mark.parametrize("status", [400, 429, 500])
def test_other_http_errors_keep_identity_without_retry(status):
    async def check():
        calls = []
        error = ClientResponseError(
            SimpleNamespace(real_url="http://example.invalid"), (), status=status
        )

        async def operation(method, params, request_id):
            calls.append(request_id)
            raise error

        request = RPCRequest(Controller(operation), "eth_blockNumber", [], uid="same")
        try:
            with pytest.raises(ClientResponseError) as caught:
                await request.make_request()
            assert caught.value is error
            assert calls == ["same"]
        finally:
            request._fut.cancel()

    asyncio.run(check())


@pytest.mark.parametrize("winner", [0, 1])
@pytest.mark.parametrize("previous_timeouts", [0, 2])
def test_local_timeout_preserves_the_race(monkeypatch, winner, previous_timeouts):
    async def check():
        gates = [asyncio.Event(), asyncio.Event()]
        both_started = asyncio.Event()
        calls, attempts, events = [], [], []
        responses = [
            decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x1"}'),
            decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x2"}'),
        ]

        async def operation(method, params, request_id):
            index = len(calls)
            calls.append((method, params, request_id))
            if len(calls) == 2:
                both_started.set()
            await gates[index].wait()
            return responses[index]

        async def quick_result(task):
            attempts.append(task)
            if len(attempts) == 1:
                await asyncio.sleep(0)
                raise asyncio.TimeoutError()
            return await task

        def observer(event):
            events.append((event.attempt, type(event.error), event.metadata))

        monkeypatch.setattr(_requests, "try_for_result_quick", quick_result)
        register_retry_observer(observer)
        request = RPCRequest(Controller(operation), "eth_blockNumber", [], uid="same")
        initial_tasks = asyncio.all_tasks()
        task = asyncio.create_task(request.make_request(previous_timeouts))
        try:
            await asyncio.wait_for(both_started.wait(), 2)
            assert not task.done()
            gates[winner].set()
            assert await asyncio.wait_for(task, 2) is responses[winner]
            assert request._fut.result() is responses[winner]
            assert calls == [("eth_blockNumber", [], "same")] * 2
            assert all(attempt.done() for attempt in attempts)
            assert events == [
                (
                    previous_timeouts + 1,
                    asyncio.TimeoutError,
                    {"timeout_seconds": str(_requests.TIMEOUT_SECONDS_SMALL)},
                )
            ]
        finally:
            unregister_retry_observer(observer)
            pending = asyncio.all_tasks() - initial_tasks
            for pending_task in pending:
                pending_task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if not request._fut.done():
                request._fut.cancel()

    asyncio.run(check())


@pytest.mark.parametrize("entrypoint", ["make_request", "get_response_unbatched"])
@pytest.mark.parametrize("retrying", [False, True])
def test_caller_cancellation_releases_every_http_attempt(monkeypatch, retrying, entrypoint):
    async def check():
        entered = asyncio.Event()
        attempts = []
        active = set()

        async def operation(method, params, request_id):
            task = asyncio.current_task()
            active.add(task)
            try:
                if len(active) == (3 if retrying else 1):
                    entered.set()
                await asyncio.Event().wait()
            finally:
                active.remove(task)

        async def quick_result(task):
            attempts.append(task)
            await asyncio.sleep(0)
            if retrying and len(attempts) < 3:
                raise asyncio.TimeoutError()
            return await asyncio.shield(task)

        monkeypatch.setattr(_requests, "try_for_result_quick", quick_result)
        request = RPCRequest(Controller(operation), "eth_blockNumber", [], uid="same")
        initial_tasks = asyncio.all_tasks()
        caller = asyncio.create_task(getattr(request, entrypoint)())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            caller.cancel()
            with pytest.raises(asyncio.CancelledError):
                await caller
            assert not active
            assert all(task.done() for task in attempts)
        finally:
            pending = asyncio.all_tasks() - initial_tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            request._fut.cancel()

    asyncio.run(check())


@pytest.mark.parametrize("outcome", ["success", "failure", "cancel"])
def test_finished_batch_task_releases_registry_ownership(outcome):
    from dank_mids._tasks import BATCH_TASKS, create_batch_task

    async def check():
        entered = asyncio.Event()

        async def operation():
            entered.set()
            if outcome == "failure":
                raise RuntimeError("failed batch")
            if outcome == "cancel":
                await asyncio.Event().wait()
            return 7

        task = create_batch_task(operation(), name="owned-batch")
        reference = weakref.ref(task)
        try:
            await entered.wait()
            if outcome == "cancel":
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.sleep(0)
            assert task not in BATCH_TASKS
        finally:
            BATCH_TASKS.discard(task)
        del task
        gc.collect()
        assert reference() is None

    asyncio.run(check())


@pytest.mark.parametrize("retrying", [False, True])
@pytest.mark.parametrize("failure", [False, True])
def test_unbatched_response_keeps_result_and_closes_duplicate_attempts(
    monkeypatch, retrying, failure
):
    async def check():
        calls = []
        active = set()
        waits = 0
        error = RuntimeError("failed unbatched request")
        response = decode_raw(b'{"jsonrpc":"2.0","id":"same","result":"0x1"}')

        async def operation(method, params, request_id):
            task = asyncio.current_task()
            active.add(task)
            calls.append((method, params, request_id))
            try:
                if retrying and len(calls) == 1:
                    await asyncio.Event().wait()
                if failure:
                    raise error
                return response
            finally:
                active.remove(task)

        async def result(task):
            nonlocal waits
            waits += 1
            if retrying and waits == 1:
                await asyncio.sleep(0)
                raise asyncio.TimeoutError()
            return await asyncio.shield(task)

        async def available(endpoint):
            assert endpoint == Controller.endpoint

        monkeypatch.setattr(_requests, "try_for_result", result)
        monkeypatch.setattr(_requests, "rate_limit_inactive", available)
        request = RPCRequest(Controller(operation), "eth_blockNumber", [], uid="same")
        initial_tasks = asyncio.all_tasks()
        try:
            if failure:
                with pytest.raises(RuntimeError) as caught:
                    await request.get_response_unbatched()
                assert caught.value is error
            else:
                assert await request.get_response_unbatched() == {"result": 1}
            assert calls == [("eth_blockNumber", [], "same")] + (
                [("eth_blockNumber", [], "same_copy")] if retrying else []
            )
            assert not active
        finally:
            pending = asyncio.all_tasks() - initial_tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if not request._fut.done():
                request._fut.cancel()

    asyncio.run(check())


@pytest.mark.parametrize("winner", [0, 1, "cancel"])
def test_json_batch_race_releases_only_its_owned_attempts(monkeypatch, winner):
    async def check():
        started = asyncio.Event()
        gates = [asyncio.Event(), asyncio.Event()]
        attempts = []
        expected = [
            [decode_raw(b'{"jsonrpc":"2.0","id":1,"result":"0x1"}')],
            [decode_raw(b'{"jsonrpc":"2.0","id":1,"result":"0x2"}')],
        ]

        async def post(endpoint, *, data, loads):
            assert endpoint == Controller.endpoint and data == b"recorded batch"
            index = len(attempts)
            attempts.append(asyncio.current_task())
            if len(attempts) == 2:
                started.set()
            await gates[index].wait()
            return expected[index]

        async def timeout(future, timeout):
            assert timeout == 30
            await asyncio.sleep(0)
            future.cancel()
            raise asyncio.TimeoutError()

        monkeypatch.setattr(_requests, "_requester", SimpleNamespace(post=post))
        monkeypatch.setattr(_requests, "wait_for", timeout)
        batch = SimpleNamespace(
            data=b"recorded batch", controller=SimpleNamespace(endpoint=Controller.endpoint), uid=1
        )
        neighbour = asyncio.create_task(asyncio.Event().wait())
        caller = asyncio.create_task(_requests.JSONRPCBatch.post(batch))
        try:
            await asyncio.wait_for(started.wait(), 2)
            if winner == "cancel":
                caller.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await caller
            else:
                gates[winner].set()
                assert await caller is expected[winner]
            assert all(task.done() for task in attempts)
            assert not neighbour.done()
        finally:
            for task in [caller, neighbour, *attempts]:
                task.cancel()
            await asyncio.gather(caller, neighbour, *attempts, return_exceptions=True)

    asyncio.run(check())


def test_unobserved_failed_batch_logs_once_without_retaining_the_task(caplog):
    from dank_mids._tasks import BATCH_TASKS, create_batch_task

    async def check():
        entered = asyncio.Event()
        unhandled = []
        loop = asyncio.get_running_loop()
        loop.set_exception_handler(lambda loop, context: unhandled.append(context["message"]))

        async def operation():
            entered.set()
            raise RuntimeError("unobserved batch failure")

        task = create_batch_task(operation(), name="unobserved-owned-batch")
        reference = weakref.ref(task)
        del task
        try:
            await entered.wait()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            gc.collect()
            assert reference() is None
            assert not unhandled
            messages = [
                record.getMessage()
                for record in caplog.records
                if "unobserved-owned-batch" in record.getMessage()
            ]
            assert len(messages) == 1
            assert "unobserved batch failure" in messages[0]
        finally:
            if task := reference():
                task.exception()
                BATCH_TASKS.discard(task)

    asyncio.run(check())
