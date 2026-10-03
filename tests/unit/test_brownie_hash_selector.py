"""Brownie method wrappers forward the complete EIP-1898 selector."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock


def test_brownie_contract_call_preserves_hash_and_canonical_requirement(monkeypatch):
    from dank_mids.brownie_patch import call

    selector = {"blockHash": "0x" + "ab" * 32, "requireCanonical": True}
    from faster_hexbytes import HexBytes

    operation = AsyncMock(return_value=HexBytes((123).to_bytes(32, "big")))

    class Web3:
        eth = SimpleNamespace(call=operation)

    target = SimpleNamespace(
        _address="0x0000000000000000000000000000000000000001",
        signature="0x1234",
        abi={
            "name": "value",
            "inputs": [],
            "outputs": [{"name": "", "type": "uint256"}],
            "stateMutability": "view",
            "type": "function",
        },
        _skip_decoder_proc_pool=True,
    )
    coroutine = call._get_coroutine_fn(Web3(), 0)
    assert asyncio.run(coroutine(target, block_identifier=selector)) == 123
    operation.assert_awaited_once_with({"to": target._address, "data": "0x1234"}, selector)


def test_overloaded_brownie_method_forwards_hash_selector():
    from dank_mids.brownie_patch import overloaded

    selector = {"blockHash": "0x" + "ab" * 32, "requireCanonical": True}
    operation = AsyncMock(return_value=321)

    class Overloaded:
        def __init__(self):
            self.methods = {}

        def _get_fn_from_args(self, args):
            assert args == (7,)
            return SimpleNamespace(coroutine=operation)

    method = Overloaded()
    overloaded._patch_overloaded_method(method, object())
    assert asyncio.run(method.coroutine(7, block_identifier=selector)) == 321
    operation.assert_awaited_once_with(7, block_identifier=selector)


def test_brownie_map_forwards_hash_selector_to_every_call():
    from dank_mids.brownie_patch import _method

    selector = {"blockHash": "0x" + "ab" * 32, "requireCanonical": True}
    received = []

    class Method(_method._DankMethodMixin[int]):
        def __init__(self):
            pass

        async def coroutine(self, value, *, block_identifier, decimals):
            received.append((value, block_identifier, decimals))
            return value * 2

    async def run():
        return await Method().map([1, 2], block_identifier=selector)

    assert asyncio.run(run()) == [2, 4]
    assert received == [(1, selector, None), (2, selector, None)]
