"""Exercise hash-selected calls through native middleware and the HTTP batcher."""

import asyncio
import json
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.machinery import EXTENSION_SUFFIXES
from pathlib import Path
from threading import Event, Thread

import pytest
from eth_abi import decode, encode
from web3 import HTTPProvider, Web3

from dank_mids import controller, setup_dank_w3_from_sync

HASH = "0x" + "ab" * 32
OTHER = "0x" + "cd" * 32
TOKEN = "0x0000000000000000000000000000000000000101"


def test_native_batcher_preserves_hashes_and_canonical_requirement():
    assert any(controller.__file__.endswith(suffix) for suffix in EXTENSION_SUFFIXES)
    header = json.loads((Path(__file__).parents[1] / "data/mainnet-25957689.json").read_text())
    received = []
    call_received = Event()
    release_response = Event()
    cancel_first = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

            def respond(request):
                received.append(request)
                method, params = request["method"], request.get("params", [])
                if method == "eth_chainId":
                    result = "0x1"
                elif method == "web3_clientVersion":
                    result = "controlled-rpc"
                elif method == "eth_getBlockByHash":
                    result = {**header, "hash": params[0]}
                elif method == "eth_getCode":
                    assert isinstance(params[1], dict)
                    result = "0x1234"
                elif method == "eth_call":
                    tx, block = params[:2]
                    assert isinstance(block, dict)
                    value = (111 if block["blockHash"] == HASH else 222).to_bytes(32, "big")
                    data = bytes.fromhex(tx["data"][2:])
                    if data[:4] == bytes.fromhex("399542e9"):
                        _, calls = decode(["bool", "(address,bytes)[]"], data[4:])
                        result = (
                            "0x"
                            + encode(
                                ["uint256", "bytes32", "(bool,bytes)[]"],
                                [
                                    int(header["number"], 16),
                                    bytes.fromhex(block["blockHash"][2:]),
                                    [(True, value) for _ in calls],
                                ],
                            ).hex()
                        )
                    else:
                        result = "0x" + value.hex()
                else:
                    return {
                        "id": request["id"],
                        "jsonrpc": "2.0",
                        "error": {
                            "code": -32601,
                            "message": "Method not found",
                            "data": {"method": method, "extra": "unsupported"},
                        },
                    }
                return {"id": request["id"], "jsonrpc": "2.0", "result": result}

            result = [respond(item) for item in body] if isinstance(body, list) else respond(body)
            requests = body if isinstance(body, list) else [body]
            if cancel_first and any(request["method"] == "eth_call" for request in requests):
                call_received.set()
                assert release_response.wait(10), "The test did not release the RPC response"
            encoded = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def check():
        w3 = setup_dank_w3_from_sync(Web3(HTTPProvider(f"http://127.0.0.1:{server.server_port}")))
        blocks = [
            {"blockHash": h, "requireCanonical": canonical}
            for h, canonical in ((HASH, True), (OTHER, True), (HASH, False))
        ]
        callers = [
            asyncio.create_task(w3.eth.call({"to": TOKEN, "data": "0x12345678"}, block))
            for block in blocks
            for _ in range(4)
        ]
        expected = [111] * 4 + [222] * 4 + [111] * 4
        try:
            if cancel_first:
                assert await asyncio.to_thread(call_received.wait, 5)
                callers[0].cancel()
                with pytest.raises(asyncio.CancelledError):
                    await callers[0]
                assert not any(caller.done() for caller in callers[1:])
                release_response.set()
                remaining = callers[1:]
                expected = expected[1:]
            else:
                remaining = callers
            results = await asyncio.wait_for(asyncio.gather(*remaining), 15)
        finally:
            release_response.set()
        assert [int.from_bytes(value, "big") for value in results] == expected
        assert await w3.eth.get_code(TOKEN, blocks[0]) == bytes.fromhex("1234")
        assert (
            int.from_bytes(
                await w3.eth.call({"to": TOKEN, "data": "0x12345678", "gas": 500000}, blocks[0]),
                "big",
            )
            == 111
        )
        # Repeated calls reuse the immutable header; they still issue hash-bound state reads.
        counts = Counter(r["params"][0] for r in received if r["method"] == "eth_getBlockByHash")
        assert counts == {HASH: 1, OTHER: 1}
        calls = [r for r in received if r["method"] == "eth_call"]
        assert {json.dumps(r["params"][1], sort_keys=True) for r in calls} == {
            json.dumps(block, sort_keys=True) for block in blocks
        }
        multicalls = [r for r in calls if r["params"][0]["data"].startswith("0x399542e9")]
        assert len(multicalls) == 3, "Each hash/canonical group must execute exactly once"
        assert all(
            len(
                decode(["bool", "(address,bytes)[]"], bytes.fromhex(r["params"][0]["data"][10:]))[1]
            )
            == 4
            for r in multicalls
        )

    async def run():
        nonlocal cancel_first
        # The native execution lock belongs to one caller event loop. Exercise
        # both independent controllers on that loop, as the application does.
        for cancel_first in (False, True):
            received.clear()
            call_received.clear()
            release_response.clear()
            await check()

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
