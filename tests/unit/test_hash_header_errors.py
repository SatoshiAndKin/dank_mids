"""Preserve header lookup failures through the native controller and HTTP edge."""

import asyncio
import json
from pathlib import Path

import pytest
from web3 import HTTPProvider, Web3
from web3.exceptions import BlockNotFound

from dank_mids import controller, setup_dank_w3_from_sync
from dank_mids._exceptions import BadResponse
from tests.unit._jsonrpc import jsonrpc_server, server_endpoint
from tests.unit._runtime import assert_test_runtime

HASH = "0x" + "ab" * 32
TOKEN = "0x0000000000000000000000000000000000000101"


@pytest.mark.parametrize("canonical", [False, True])
@pytest.mark.parametrize(
    "data", [None, "provider-detail", [1, "detail"], {"reason": {"retry": False}}, ...]
)
def test_hash_header_rpc_error_keeps_details_and_can_recover(jsonrpc_server, canonical, data):
    assert_test_runtime(controller)
    error = {"code": -32001, "message": "backend unavailable"}
    if data is not ...:
        error["data"] = data
    jsonrpc_server.errors["eth_getBlockByHash"] = error
    header = json.loads((Path(__file__).parents[1] / "data/mainnet-25957689.json").read_text())
    jsonrpc_server.results["eth_getBlockByHash"] = {**header, "hash": HASH}
    jsonrpc_server.results["eth_call"] = "0x" + (123).to_bytes(32, "big").hex()

    async def check():
        from dank_mids.helpers._controllers import get_controller_for_async_w3

        w3 = setup_dank_w3_from_sync(Web3(HTTPProvider(server_endpoint(jsonrpc_server))))
        get_controller_for_async_w3(w3).no_multicall.add(TOKEN)
        selector = {"blockHash": HASH, "requireCanonical": canonical}
        tx = {"to": TOKEN, "data": "0x12345678"}
        for _ in range(2):
            with pytest.raises(BadResponse) as exc:
                await w3.eth.call(tx, selector)
            assert exc.value.args[0] == error
            assert exc.value.response.error.to_dict() == error
            assert exc.value.request.method == "eth_getBlockByHash"
            assert exc.value.request.params == (HASH, False)
        assert not any(method == "eth_call" for method, _params in jsonrpc_server.calls)
        jsonrpc_server.errors.pop("eth_getBlockByHash")
        for _ in range(2):
            assert int.from_bytes(await w3.eth.call(tx, selector), "big") == 123
        lookups = [
            params for method, params in jsonrpc_server.calls if method == "eth_getBlockByHash"
        ]
        assert lookups == [[HASH, False]] * 3, "Only successful metadata may be cached"
        calls = [params for method, params in jsonrpc_server.calls if method == "eth_call"]
        assert len(calls) == 2
        assert all(params[1] == selector for params in calls)
        requests = [
            row
            for row in jsonrpc_server.payloads
            if row["method"] in ("eth_call", "eth_getBlockByHash")
        ]
        assert len({row["id"] for row in requests}) == 5

    asyncio.run(check())


def test_null_hash_header_still_reports_missing_block(jsonrpc_server):
    assert_test_runtime(controller)
    jsonrpc_server.results["eth_getBlockByHash"] = None

    async def check():
        w3 = setup_dank_w3_from_sync(Web3(HTTPProvider(server_endpoint(jsonrpc_server))))
        for _ in range(2):
            with pytest.raises(BlockNotFound) as exc:
                await w3.eth.call({"to": TOKEN, "data": "0x12345678"}, {"blockHash": HASH})
            assert exc.value.args == (HASH,)
        lookups = [
            params for method, params in jsonrpc_server.calls if method == "eth_getBlockByHash"
        ]
        assert lookups == [[HASH, False]] * 2
        assert not any(method == "eth_call" for method, _params in jsonrpc_server.calls)

    asyncio.run(check())
