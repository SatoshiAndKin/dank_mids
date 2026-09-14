from decimal import Decimal
from typing import Final, Literal, cast

from a_sync.primitives.locks.prio_semaphore import (
    _AbstractPrioritySemaphore,
    _PrioritySemaphoreContextManager,
)

from dank_mids._block import HashBlock, StateBlockIdentifier

_TOP_PRIORITY: Final = -1


class _BlockSemaphoreContextManager(_PrioritySemaphoreContextManager):
    """
    A context manager for block-specific semaphores.

    This class is used internally to manage concurrency for operations
    related to specific blockchain blocks.
    """

    _priority_name = "block"
    """The noun that describes the priority, set to "block"."""

    def __init__(
        self,
        parent: "BlockSemaphore",
        priority: int | float | Decimal,
        name: str | None = None,
    ) -> None:
        if not isinstance(priority, (int, float, Decimal)):
            raise TypeError(priority)
        super().__init__(parent, priority, name)


# NOTE: keep this so we can include in type stubs
# class BlockSemaphore(_AbstractPrioritySemaphore[str, _BlockSemaphoreContextManager]):  # type: ignore [type-var]
class BlockSemaphore(_AbstractPrioritySemaphore):
    """A semaphore for managing concurrency based on block numbers.

    This class extends :class:`_AbstractPrioritySemaphore` to provide block-specific concurrency control.

    Args:
        value: The initial value of the semaphore.
        name: An optional name for the semaphore.

    See Also:
        :class:`_BlockSemaphoreContextManager`: The context manager used by this semaphore.
    """

    _context_manager_class: type[_BlockSemaphoreContextManager]
    """The context manager class used by this semaphore."""

    _top_priority: Literal[-1]
    """The highest priority value, set to -1."""

    def __init__(self, value=1, *, name=None) -> None:
        super().__init__(_BlockSemaphoreContextManager, -1, int(value), name=name)

    def __getitem__(self, block: StateBlockIdentifier | HashBlock | None) -> "_BlockSemaphoreContextManager":  # type: ignore [override]
        if isinstance(block, HashBlock):
            priority = block.number
        elif isinstance(block, dict):
            # Brownie encoding precedes header resolution. Hash-selected calls
            # share the same admission limit and receive equal priority.
            priority = int(block["blockNumber"], 16) if "blockNumber" in block else _TOP_PRIORITY
        elif isinstance(block, int):
            priority = block
        elif isinstance(block, bytes):
            priority = int(block.hex(), 16)
        elif isinstance(block, str) and "0x" in block:
            priority = int(block, 16)
        elif block not in {None, "latest"}:
            # NOTE: We do this to generate an err if an unsuitable value was provided
            raise TypeError("unsupported block identifier", block)
        else:
            priority = _TOP_PRIORITY
        return cast(_BlockSemaphoreContextManager, super().__getitem__(priority))
