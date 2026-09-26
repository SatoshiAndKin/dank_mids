import asyncio

import pytest

from dank_mids._block import HashBlock, block_height, rpc_block, validate_hash_selector
from dank_mids.semaphores import BlockSemaphore

HASH = "0x" + "ab" * 32


def test_hash_key_keeps_number_hash_and_canonical_requirement():
    block = HashBlock(HASH, True, 18000000)
    other = HashBlock("0x" + "cd" * 32, True, 18000000)
    optional = HashBlock(HASH, False, 18000000)
    assert len({block, other, optional}) == 3
    assert rpc_block(block) == {"blockHash": HASH, "requireCanonical": True}
    assert block_height(block) == 18000000
    assert rpc_block("0x123") == "0x123"
    assert block_height("latest") == "latest"


def test_selector_normalizes_hash_and_default_canonical_requirement():
    assert validate_hash_selector({"blockHash": "0x" + "AB" * 32}) == (HASH, False)
    assert validate_hash_selector({"blockHash": HASH, "requireCanonical": True}) == (HASH, True)


@pytest.mark.parametrize(
    "selector,error",
    [
        ({"blockHash": HASH, "blockNumber": "0x1"}, ValueError),
        ({"blockHash": "0x123"}, ValueError),
        ({"blockHash": 1}, ValueError),
        ({"blockHash": "0x" + "zz" * 32}, ValueError),
        ({"blockHash": HASH, "requireCanonical": 1}, TypeError),
    ],
)
def test_invalid_hash_selector_is_not_sent(selector, error):
    with pytest.raises(error):
        validate_hash_selector(selector)


def test_hash_identifiers_use_the_existing_admission_limit():
    async def check():
        semaphore = BlockSemaphore(1)
        first = HashBlock(HASH, True, 18000000)
        entered = asyncio.Event()

        async def second():
            async with semaphore[{"blockHash": HASH, "requireCanonical": True}]:
                entered.set()

        async with semaphore[first]:
            task = asyncio.create_task(second())
            await asyncio.sleep(0)
            assert not entered.is_set()
        await task
        assert entered.is_set()
        async with semaphore[{"blockNumber": "0x123"}]:
            pass

    asyncio.run(check())


@pytest.mark.parametrize(
    "header,error", [(None, "BlockNotFound"), ({"hash": bytes(32), "number": 1}, "ValueError")]
)
def test_missing_or_mismatched_header_is_never_cached(monkeypatch, header, error):
    from unittest.mock import AsyncMock

    from dank_mids import _requests
    from dank_mids._block import resolve_block_number

    async def check():
        owner = object()
        rpc = AsyncMock(return_value={"result": header})
        monkeypatch.setattr(_requests, "RPCRequest", rpc)
        for _ in range(2):
            with pytest.raises(Exception) as exc:
                await resolve_block_number(owner, HASH)
            assert type(exc.value).__name__ == error
        assert rpc.await_count == 2

    asyncio.run(check())


def test_shared_header_lookup_survives_one_cancelled_waiter(monkeypatch):
    from dank_mids import _requests
    from dank_mids._block import resolve_block_number

    async def check():
        owner = object()
        started, release = asyncio.Event(), asyncio.Event()
        calls = 0

        async def rpc(*args):
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return {"result": {"hash": bytes.fromhex(HASH[2:]), "number": 18000000}}

        monkeypatch.setattr(_requests, "RPCRequest", rpc)
        first = asyncio.create_task(resolve_block_number(owner, HASH))
        second = asyncio.create_task(resolve_block_number(owner, HASH))
        await started.wait()
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        release.set()
        assert await second == 18000000
        assert await resolve_block_number(owner, HASH) == 18000000
        assert calls == 1

    asyncio.run(check())


def test_controller_keeps_hash_identity_for_unbatched_calls(monkeypatch):
    from unittest.mock import AsyncMock
    from dank_mids import controller as module
    from test_gc_batch_contract import _build_controller_for_early_start

    async def check():
        owner = _build_controller_for_early_start()
        target = "0x0000000000000000000000000000000000000002"
        tx = {"to": target, "data": "0x12345678"}
        hash_block = {"blockHash": HASH, "requireCanonical": True}
        monkeypatch.setattr(module, "resolve_block_number", AsyncMock(return_value=18000000))
        batched = AsyncMock(return_value={"result": b"batched"})
        rpc = AsyncMock(return_value={"result": b"single"})
        monkeypatch.setattr(module, "eth_call", batched)
        monkeypatch.setattr(module, "RPCRequest", rpc)
        assert await owner("eth_call", (tx, hash_block)) == {"result": b"batched"}
        assert batched.call_args.args[1] == (tx, HashBlock(HASH, True, 18000000))
        owner.no_multicall.add(target)
        assert await owner("eth_call", (tx, hash_block)) == {"result": b"single"}
        assert rpc.call_args.args[2] == (tx, hash_block)
        await owner("eth_call", (tx, {"blockNumber": "0x123"}))
        assert rpc.call_args.args[2] == (tx, "0x123")
        # Resolve height for Multicall deployment selection, never for RPC state.
        assert owner._select_mcall_target_for_block(HashBlock(HASH, True, 18000000)) == owner.mc2
        assert owner._select_mcall_target_for_block("latest") == owner.mc2

    asyncio.run(check())


@pytest.mark.parametrize("block", [123, "0x123", bytes.fromhex("0123"), None, "latest"])
def test_existing_semaphore_identifiers_keep_working(block):
    async def check():
        async with BlockSemaphore(1)[block]:
            pass

    asyncio.run(check())


def test_semaphore_rejects_unsupported_selector():
    with pytest.raises(TypeError):
        BlockSemaphore(1)[object()]


def test_duplicate_rpc_keeps_the_hash_batch_key_and_wire_selector():
    from dank_mids._requests import eth_call
    from test_gc_batch_contract import _build_controller_for_early_start

    async def check():
        owner = _build_controller_for_early_start()
        block = HashBlock(HASH, True, 18000000)
        tx = {"to": "0x0000000000000000000000000000000000000002", "data": "0x12345678"}
        call = eth_call(owner, (tx, block))
        duplicate = call.create_duplicate()
        assert duplicate.block == block
        assert duplicate.params == (tx, block.rpc())
        assert list(owner.pending_eth_calls) == [block]
        assert "blockHash" in repr(duplicate)
        await duplicate.spoof_response(bytes(32))

    asyncio.run(check())
