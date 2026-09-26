"""Block identities used by RPC queues and native multicall batches."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from async_lru import alru_cache
from web3.exceptions import BlockNotFound
from web3.types import BlockIdentifier, RPCEndpoint

if TYPE_CHECKING:
    from dank_mids.controller import DankMiddlewareController


@dataclass(frozen=True)
class HashBlock:
    block_hash: str
    require_canonical: bool
    number: int

    def rpc(self) -> dict[str, str | bool]:
        return {"blockHash": self.block_hash, "requireCanonical": self.require_canonical}


BlockId: TypeAlias = str | HashBlock
StateBlockIdentifier: TypeAlias = BlockIdentifier | dict[str, str | bool]


def rpc_block(block: BlockId) -> str | dict[str, str | bool]:
    return block.rpc() if isinstance(block, HashBlock) else block


def block_height(block: BlockId) -> int | str:
    return block.number if isinstance(block, HashBlock) else block


def validate_hash_selector(block: dict[str, object]) -> tuple[str, bool]:
    if set(block) - {"blockHash", "requireCanonical"}:
        raise ValueError("blockHash cannot be combined with other block selectors", block)
    value = block.get("blockHash")
    if not isinstance(value, str) or len(value) != 66 or not value.startswith("0x"):
        raise ValueError("blockHash must contain exactly 32 bytes", value)
    try:
        bytes.fromhex(value[2:])
    except ValueError:
        raise ValueError("blockHash must be hexadecimal", value) from None
    canonical = block.get("requireCanonical", False)
    if not isinstance(canonical, bool):
        raise TypeError("requireCanonical must be a boolean")
    return value.lower(), canonical


@alru_cache(maxsize=1024)
async def resolve_block_number(controller: "DankMiddlewareController", block_hash: str) -> int:
    """Share immutable header metadata while preserving hash identity for calls."""
    from dank_mids._requests import RPCRequest

    response = await RPCRequest(controller, RPCEndpoint("eth_getBlockByHash"), (block_hash, False))
    header = response.get("result")
    if header is None:
        raise BlockNotFound(block_hash)
    if bytes(header["hash"]).hex() != block_hash[2:]:
        raise ValueError("RPC returned a different block hash", block_hash)
    return int(header["number"])
