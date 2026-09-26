"""Failed singleton multicalls must terminate at the original RPC operation."""

import asyncio
import json
from threading import RLock
from types import SimpleNamespace

import pytest

from dank_mids._requests import Multicall, RPCRequest
from dank_mids._uid import UIDGenerator
from dank_mids.helpers._codec import decode_raw


class Controller:
    endpoint = "http://example.invalid"
    max_jsonrpc_batch_size = 1000

    def __init__(self, operation):
        self._loop = asyncio.get_running_loop()
        self.call_uid = UIDGenerator()
        self.multicall_uid = UIDGenerator()
        self.batcher = SimpleNamespace(step=1000)
        self.pools_closed_lock = RLock()
        self.pending_rpc_calls = []
        self.make_request = operation

    async def dispatch_pending_rpc_batch_and_wait(self, batches):
        raise AssertionError("A failed singleton must not be bisected into another multicall")


def failed_response():
    return decode_raw(
        b'{"jsonrpc":"2.0","id":1,"error":{"code":-32003,"message":"EVM error: NotActivated"}}'
    )


@pytest.mark.parametrize("revert", [False, True])
@pytest.mark.parametrize(
    "block", [6100000, {"blockHash": "0x" + "ab" * 32, "requireCanonical": True}]
)
def test_failed_singleton_preserves_original_request_and_response(block, revert):
    async def run():
        received = []
        payload = {"jsonrpc": "2.0", "id": "original"}
        (
            payload.update(error={"code": 3, "message": "execution reverted"})
            if revert
            else payload.update(result="0x1234")
        )
        expected = decode_raw(json.dumps(payload).encode())

        async def operation(method, params, request_id):
            received.append((method, params, request_id))
            return expected

        controller = Controller(operation)
        params = [{"to": "0x0000000000000000000000000000000000000001", "data": "0x12345678"}, block]
        request = RPCRequest(controller, "eth_call", params, uid="original")
        batch = Multicall(controller, [request])
        await batch._spoof_or_retry(failed_response())
        assert received == [("eth_call", params, "original")]
        assert request._fut.result() is expected
        assert batch._done.is_set()

    asyncio.run(run())


def test_failed_empty_multicall_finishes_without_recreating_calls():
    async def run():
        async def forbidden(*args, **kwargs):
            raise AssertionError("abandoned calls must not be recreated")

        batch = Multicall(Controller(forbidden), [])
        await batch._spoof_or_retry(failed_response())
        assert batch._done.is_set()

    asyncio.run(run())


@pytest.mark.parametrize("error", [RuntimeError("transport failed")])
def test_singleton_direct_failure_and_cancellation_propagate(error):
    async def run():
        calls = 0

        async def operation(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise error

        controller = Controller(operation)
        request = RPCRequest(controller, "eth_call", [], uid="original")
        batch = Multicall(controller, [request])
        try:
            with pytest.raises(type(error)):
                await batch._spoof_or_retry(failed_response())
            assert calls == 1
            assert not batch._done.is_set()
        finally:
            request._fut.cancel()

    asyncio.run(run())


def test_singleton_caller_cancellation_releases_the_direct_call():
    async def run():
        started, released = asyncio.Event(), asyncio.Event()

        async def operation(*args, **kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                released.set()

        controller = Controller(operation)
        request = RPCRequest(controller, "eth_call", [], uid="original")
        batch = Multicall(controller, [request])
        task = asyncio.create_task(batch._spoof_or_retry(failed_response()))
        try:
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert released.is_set()
            assert not batch._done.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            request._fut.cancel()

    asyncio.run(run())
