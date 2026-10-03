"""Historical opcode errors fall back through the real native HTTP batcher."""

import asyncio
import faulthandler
import json
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from socketserver import TCPServer
from threading import Thread

from tests.unit._runtime import assert_test_runtime

if __name__ == "__main__":
    faulthandler.enable()
    faulthandler.dump_traceback_later(20)

from eth_abi import decode, encode
from web3 import HTTPProvider, Web3

from dank_mids import controller, setup_dank_w3_from_sync


def historical_opcode_error_falls_back_without_poisoning_modern_batches():
    assert_test_runtime(controller)
    header = json.loads((Path(__file__).parents[1] / "data/mainnet-25957689.json").read_text())
    old_hash, modern_hash = "0x" + "ab" * 32, "0x" + "cd" * 32
    token = "0x0000000000000000000000000000000000000101"
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))

            def respond(request):
                received.append(request)
                method, params = request["method"], request.get("params", [])
                response = {"jsonrpc": "2.0", "id": request["id"]}
                if method == "eth_chainId":
                    result = "0x1"
                elif method == "web3_clientVersion":
                    result = "controlled-rpc"
                elif method == "eth_getBlockByHash":
                    number = 6100000 if params[0] == old_hash else 18000000
                    result = {**header, "hash": params[0], "number": hex(number)}
                elif method == "eth_call":
                    tx, block = params[:2]
                    old = block["blockHash"] == old_hash
                    data = bytes.fromhex(tx["data"][2:])
                    if data[:4] == bytes.fromhex("399542e9"):
                        if old:
                            return {
                                **response,
                                "error": {"code": -32003, "message": "EVM error: NotActivated"},
                            }
                        _, calls = decode(["bool", "(address,bytes)[]"], data[4:])
                        result = (
                            "0x"
                            + encode(
                                ["uint256", "bytes32", "(bool,bytes)[]"],
                                [
                                    18000000,
                                    bytes.fromhex(modern_hash[2:]),
                                    [(True, (222).to_bytes(32, "big")) for _ in calls],
                                ],
                            ).hex()
                        )
                    else:
                        assert tx == {"to": token, "data": "0x12345678"}
                        assert len(params) == 2
                        result = "0x" + (111 if old else 222).to_bytes(32, "big").hex()
                else:
                    raise AssertionError(method)
                return {**response, "result": result}

            encoded = json.dumps(
                [respond(r) for r in body] if isinstance(body, list) else respond(body)
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    class LocalHTTPServer(ThreadingHTTPServer):
        def server_bind(self):
            # This loopback fixture needs no reverse DNS. macOS CI can block in
            # HTTPServer.server_bind's getfqdn lookup before any RPC is sent.
            TCPServer.server_bind(self)
            self.server_name = "localhost"
            self.server_port = self.server_address[1]

    server = LocalHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def run():
        w3 = setup_dank_w3_from_sync(Web3(HTTPProvider(f"http://127.0.0.1:{server.server_port}")))
        blocks = [
            {"blockHash": value, "requireCanonical": True} for value in (old_hash, modern_hash)
        ]
        values = await asyncio.wait_for(
            asyncio.gather(
                *[
                    w3.eth.call({"to": token, "data": "0x12345678"}, block)
                    for block in blocks
                    for _ in range(4)
                ]
            ),
            10,
        )
        assert [int.from_bytes(value, "big") for value in values] == [111] * 4 + [222] * 4
        modern = await asyncio.gather(
            *[w3.eth.call({"to": token, "data": "0x12345678"}, blocks[1]) for _ in range(2)]
        )
        assert [int.from_bytes(value, "big") for value in modern] == [222, 222]
        calls = [r for r in received if r["method"] == "eth_call"]
        direct = [r for r in calls if r["params"][0]["to"].lower() == token]
        assert len(direct) == 4
        assert all(r["params"][1] == blocks[0] for r in direct)
        multicalls = [r for r in calls if r not in direct]
        assert sum(r["params"][1] == blocks[0] for r in multicalls) <= 7
        assert sum(r["params"][1] == blocks[1] for r in multicalls) == 2

    try:
        asyncio.run(run())
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_historical_opcode_error_falls_back_without_poisoning_modern_batches():
    # Native controller admission primitives belong to their first event loop.
    # Use a fresh process, as the installed-requester lifecycle tests do.
    try:
        subprocess.run(
            [sys.executable, "-m", "tests.unit.test_historical_multicall"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except subprocess.TimeoutExpired as error:
        raise AssertionError(f"Historical batch worker timed out:\n{error.stderr}") from error


if __name__ == "__main__":
    historical_opcode_error_falls_back_without_poisoning_modern_batches()
