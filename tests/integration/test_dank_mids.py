import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from a_sync import igather
from brownie import chain
from evmspec import Transaction1559, Transaction2930, Transaction7702
from hexbytes import HexBytes
from multicall import Call
from web3._utils.rpc_abi import RPC

from dank_mids import dank_web3, instances

CHAI = "0x06AF07097C9Eeb7fD685c692751D5C66dB49c215"


def call_chai(i: int, block: int, w3=dank_web3) -> Call:
    return Call(CHAI, "totalSupply()(uint)", [[f"totalSupply{i}", None]], _w3=w3, block_id=block)


height = chain.height
MULTIBLOCK_WORK = (call_chai(i, height - i) for i in range(1000))


@pytest.mark.asyncio_cooperative
async def test_middleware_controller_processes_calls() -> None:
    await asyncio.to_thread(
        subprocess.run,
        [sys.executable, str(Path(__file__).with_name("_batching_workload.py"))],
        check=True,
        text=True,
        timeout=120,
        # Admit both groups together; bound live HTTP payloads below provider limits.
        env={
            **os.environ,
            "MULTICALL_CALL_SEMAPHORE": "50000",
            "DANKMIDS_MAX_MULTICALL_SIZE": "1000",
        },
    )


@pytest.mark.asyncio_cooperative
async def test_bad_hex_handling() -> None:
    """
    Test the handling of bad hex values in contract calls.

    This test ensures that the system can correctly handle and process
    contract calls that might return unusual or malformed hex values.
    """
    chainlinkfeed = "0xfe67209f6FE3BA6cE36d0941700085C194e958DF"
    assert await Call(chainlinkfeed, "latestAnswer()(uint)", block_id=14_000_000) == 15717100


@pytest.mark.asyncio_cooperative
async def test_json_batch() -> None:
    """
    Test the JSON batch processing functionality.

    This test verifies that the system can correctly handle and process
    a batch of JSON-RPC requests across multiple blocks.
    """
    await igather(MULTIBLOCK_WORK)


def test_next_cid() -> None:
    """
    Test the generation of the next call ID.

    This test ensures that the call ID generator correctly increments
    and provides unique IDs for each call.
    """
    controller = instances[chain.id][0]
    assert controller.call_uid.next + 1 == controller.call_uid.next


def test_next_mid() -> None:
    """
    Test the generation of the next request ID.

    This test verifies that the request ID generator correctly increments
    and provides unique IDs for each request.
    """
    controller = instances[chain.id][0]
    assert controller.request_uid.next + 1 == controller.request_uid.next


def test_next_bid() -> None:
    """
    Test the generation of the next multicall ID.

    This test checks that the multicall ID generator correctly increments
    and provides unique IDs for each multicall.
    """
    controller = instances[chain.id][0]
    assert controller.multicall_uid.next + 1 == controller.multicall_uid.next


@pytest.mark.asyncio_cooperative
async def test_other_methods() -> None:
    """
    Test various other RPC methods.
    """
    work = [
        *(dank_web3.eth.block_number for _ in range(50)),
        dank_web3.eth.get_block("0xe25822"),
        dank_web3.manager.coro_request(RPC.web3_clientVersion, []),
    ]
    results = await igather(work)
    assert results
    assert results[-2].timestamp


@pytest.mark.asyncio_cooperative
async def test_AttributeDict() -> None:
    """
    Test the AttributeDict functionality.

    This test verifies that a dictionary response from dank_mids correctly allows
    both dictionary-style and attribute-style access to its contents.
    """
    block = await dank_web3.eth.get_block("0xe25822")
    assert block["timestamp"] and block.timestamp and (block["timestamp"] == block.timestamp)


@pytest.mark.asyncio_cooperative
async def test_string_block() -> None:
    with pytest.raises(TypeError):
        await Call(CHAI, "totalSupply()(uint)", block_id="14000000")


@pytest.mark.asyncio_cooperative
async def test_eth_getTransaction_1559() -> None:
    tx_1559 = await dank_web3.eth.get_transaction(
        "0x1540ea6e443ff81570624fe19220507a1d949464b5a012ac110c7e91205c456a"
    )
    assert isinstance(tx_1559, Transaction1559)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransaction_2930() -> None:
    tx_2930 = await dank_web3.eth.get_transaction(
        "0x3ea6b560065dabfac5218c64fd076ef62ff9d6c08817101e7dbece460eb2c8a5"
    )
    assert isinstance(tx_2930, Transaction2930)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransaction_7702() -> None:
    tx_7702 = await dank_web3.eth.get_transaction(
        "0xad5cdaffa0901bf3abb63c7bfa0307035aeeb94a2ff27d01d6dc33c3d1b40c8a"
    )
    assert isinstance(tx_7702, Transaction7702)


@pytest.mark.asyncio_cooperative
async def test_eth_getBalance_no_block() -> None:
    assert isinstance(await dank_web3.eth.get_balance(CHAI), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getBalance_int_block() -> None:
    assert isinstance(await dank_web3.eth.get_balance(CHAI, 20_000_000), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getBalance_hex_block() -> None:
    assert isinstance(await dank_web3.eth.get_balance(CHAI, hex(20_000_000)), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getBalance_latest() -> None:
    assert isinstance(await dank_web3.eth.get_balance(CHAI, "latest"), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransactionCount_no_block() -> None:
    assert isinstance(await dank_web3.eth.get_transaction_count(CHAI), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransactionCount_int_block() -> None:
    assert isinstance(await dank_web3.eth.get_transaction_count(CHAI, 20_000_000), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransactionCount_hex_block() -> None:
    assert isinstance(await dank_web3.eth.get_transaction_count(CHAI, hex(20_000_000)), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getTransactionCount_latest() -> None:
    assert isinstance(await dank_web3.eth.get_transaction_count(CHAI, "latest"), int)


@pytest.mark.asyncio_cooperative
async def test_eth_getCode_no_block() -> None:
    assert isinstance(await dank_web3.eth.get_code(CHAI), HexBytes)


@pytest.mark.asyncio_cooperative
async def test_eth_getCode_int_block() -> None:
    assert isinstance(await dank_web3.eth.get_code(CHAI, 20_000_000), HexBytes)


@pytest.mark.asyncio_cooperative
async def test_eth_getCode_hex_block() -> None:
    assert isinstance(await dank_web3.eth.get_code(CHAI, hex(20_000_000)), HexBytes)


@pytest.mark.asyncio_cooperative
async def test_eth_getCode_latest() -> None:
    assert isinstance(await dank_web3.eth.get_code(CHAI, "latest"), HexBytes)
