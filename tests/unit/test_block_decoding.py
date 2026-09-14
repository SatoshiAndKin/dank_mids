"""Decode real fork-era block surfaces without depending on JSON field order."""

import json
from pathlib import Path

import pytest
from msgspec import Raw, ValidationError

from dank_mids import types


@pytest.fixture
def block():
    return json.loads((Path(__file__).parents[1] / "data/mainnet-25957689.json").read_text())


@pytest.mark.parametrize("method", ["eth_getBlockByNumber", "eth_getBlockByHash"])
@pytest.mark.parametrize(
    "first", ["baseFeePerGas", "difficulty", "withdrawals", "requestsHash", "hash"]
)
def test_current_block_accepts_every_field_order(block, method, first):
    ordered = {first: block[first], **block}
    result = types.PartialResponse(result=Raw(json.dumps(ordered).encode())).decode_result(method)
    assert int(result.number) == 25957689
    assert bytes(result.hash).hex() == block["hash"][2:]
    assert int(result.baseFeePerGas) == int(block["baseFeePerGas"], 16)
    assert int(result.blobGasUsed) == int(block["blobGasUsed"], 16)
    assert types._RETURN_TYPES[method] is types.Block


@pytest.mark.parametrize("era", ["pre-london", "london", "shanghai"])
def test_successive_fork_eras_do_not_change_other_requests(block, era):
    old = dict(block)
    if era != "shanghai":
        for key in (
            "withdrawals",
            "withdrawalsRoot",
            "blobGasUsed",
            "excessBlobGas",
            "parentBeaconBlockRoot",
            "requestsHash",
        ):
            old.pop(key, None)
    if era == "pre-london":
        old.pop("baseFeePerGas")
    old["totalDifficulty"] = "0x1"
    for payload in (block, old, block):
        result = types.PartialResponse(result=Raw(json.dumps(payload).encode())).decode_result(
            "eth_getBlockByNumber"
        )
        assert int(result.number) == 25957689
        assert types._RETURN_TYPES["eth_getBlockByNumber"] is types.Block


def test_minimal_block_schema_and_unknown_field_validation(block):
    for key in (
        "difficulty",
        "baseFeePerGas",
        "withdrawals",
        "withdrawalsRoot",
        "blobGasUsed",
        "excessBlobGas",
        "parentBeaconBlockRoot",
        "requestsHash",
    ):
        block.pop(key, None)
    response = types.PartialResponse(result=Raw(json.dumps(block).encode()))
    assert type(response.decode_result("eth_getBlockByNumber")) is types.Block
    block["notAnEthereumField"] = "0x0"
    with pytest.raises(ValidationError, match="notAnEthereumField"):
        types.PartialResponse(result=Raw(json.dumps(block).encode())).decode_result(
            "eth_getBlockByNumber"
        )


def test_missing_block_remains_null():
    assert types.PartialResponse(result=Raw(b"null")).decode_result("eth_getBlockByHash") is None
