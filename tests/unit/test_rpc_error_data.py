import json

import pytest

from dank_mids._exceptions import (
    BadResponse,
    ChainstackRateLimitError,
    ExecutionReverted,
)
from dank_mids.helpers._codec import decode_jsonrpc_batch, decode_raw
from dank_mids.types import _CHAINSTACK_429_ERR_MSG


@pytest.mark.parametrize(
    "data", [None, "0x1234", {}, {"method": "unknown", "extra": "unsupported"}, [1, "x"], 42, True]
)
def test_error_preserves_arbitrary_json_data_in_single_and_batch_responses(data):
    payload = {
        "id": 1,
        "jsonrpc": "2.0",
        "error": {"code": -32601, "message": "Method not found", "data": data},
    }
    encoded = json.dumps(payload).encode()
    for response in (decode_raw(encoded).decode(), decode_jsonrpc_batch(encoded)):
        assert response.error.to_dict() == payload["error"]
        assert type(response.exception) is BadResponse
    response = decode_jsonrpc_batch(b"[" + encoded + b"]")[0].decode()
    assert response.error.to_dict() == payload["error"]


def test_revert_with_structured_context_remains_a_revert():
    response = decode_raw(
        b'{"error":{"code":3,"message":"execution reverted","data":{"reason":"paused"}}}'
    ).decode()
    assert isinstance(response.exception, ExecutionReverted)
    assert response.error.data == {"reason": "paused"}


@pytest.mark.parametrize("duration,seconds", [("250ms", 0.25), ("250µs", 0.00025)])
def test_only_chainstack_rate_limits_parse_the_retry_duration(duration, seconds):
    response = decode_raw(
        json.dumps(
            {
                "error": {
                    "code": -32005,
                    "message": _CHAINSTACK_429_ERR_MSG,
                    "data": {"try_again_in": duration},
                }
            }
        ).encode()
    ).decode()
    assert isinstance(response.exception, ChainstackRateLimitError)
    assert response.exception.try_again_in == seconds
    assert response.error.data == {"try_again_in": duration}


@pytest.mark.parametrize("data", [{}, None, {"try_again_in": 1}])
def test_malformed_rate_limit_retains_the_actual_error_context(data):
    response = decode_raw(
        json.dumps(
            {"error": {"code": -32005, "message": _CHAINSTACK_429_ERR_MSG, "data": data}}
        ).encode()
    ).decode()
    with pytest.raises(ValueError, match="lacks a retry duration"):
        _ = response.exception.try_again_in
    assert response.error.data == data
