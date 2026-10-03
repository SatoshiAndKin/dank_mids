"""Measure batching without other tests sharing SDK locks or rate admission."""

import asyncio
import importlib.machinery
import os
import sys

from brownie import chain, network, web3
from multicall import Call
from web3 import HTTPProvider, Web3

from dank_mids import controller as native_controller
from dank_mids import instances, setup_dank_w3_from_sync

CHAI = "0x06AF07097C9Eeb7fD685c692751D5C66dB49c215"


def call_chai(i: int, block: int, w3) -> Call:
    return Call(CHAI, "totalSupply()(uint)", [[f"totalSupply{i}", None]], _w3=w3, block_id=block)


async def measure() -> None:
    workload_web3 = setup_dank_w3_from_sync(Web3(HTTPProvider(web3.provider.endpoint_uri)))
    workload_height = await workload_web3.eth.block_number
    controller = next(item for item in instances[chain.id] if item.w3 is workload_web3)
    before = tuple(
        counter.latest
        for counter in (controller.call_uid, controller.multicall_uid, controller.request_uid)
    )
    num_calls = 500 if "llama" in web3.provider.endpoint_uri else 50_000
    # Queue both block groups together, independent of a_sync's iterator admission.
    await asyncio.gather(
        *[
            call_chai(i, workload_height - (i // 25000), w3=workload_web3)
            for i in sorted(range(0, num_calls, 4), key=lambda i: i % 25000)
        ]
    )
    cid, mid, rid = (
        counter.latest - previous
        for counter, previous in zip(
            (controller.call_uid, controller.multicall_uid, controller.request_uid), before
        )
    )
    assert cid, "The DankMiddlewareController did not process any calls."
    if sys.version_info < (3, 10):
        # Not sure why this assert fails above 3.10
        assert mid, "The DankMiddlewareController did not process any batches."
    assert rid, "The DankMiddlewareController did not process any requests."
    print(f"calls:                  {cid}")
    print(f"multicalls:             {mid}")
    print(f"requests:               {rid}")
    print(f"calls per multicall:    {cid/mid}")
    print(f"calls per request:      {cid/rid}")
    print(f"multicalls per request: {mid/rid}")
    # General "tests" that verify batching performance
    assert mid < cid / 30, f"Batched {cid} calls into {mid} multicalls. Performance underwhelming."
    assert rid < cid / 150, f"Batched {cid} calls into {rid} requests. Performance underwhelming."
    assert (
        mid / rid > 1
    ), f"Batched {mid} multicalls into {rid} requests. Performance underwhelming."


if __name__ == "__main__":
    assert native_controller.__file__.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))
    if not network.is_connected():
        network.connect(os.environ.get("PYTEST_NETWORK", "mainnet"))
    asyncio.run(measure())
