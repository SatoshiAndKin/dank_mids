import asyncio
import heapq
from collections import defaultdict
from typing import Final

import a_sync.asyncio

from dank_mids import ENVIRONMENT_VARIABLES as ENVS
from dank_mids._tasks import shield
from dank_mids._vendor.aiolimiter.src.aiolimiter import AsyncLimiter
from dank_mids.helpers._requester import _requester
from dank_mids.logging import get_c_logger
from dank_mids.types import RateLimiters

TASKS: Final[set[asyncio.Task[None]]] = set()

logger: Final = get_c_logger("dank_mids.rate_limit")

CancelledError: Final = asyncio.CancelledError
create_task: Final = asyncio.create_task
get_running_loop: Final = asyncio.get_running_loop

nlargest: Final = heapq.nlargest

sleep0: Final = a_sync.asyncio.sleep0


# default is 50 requests/second
limiters: Final[RateLimiters] = defaultdict(
    lambda: AsyncLimiter(1, 1 / int(ENVS.REQUESTS_PER_SECOND))
)

_rate_limit_tasks: Final[dict[str, "asyncio.Task[None]"]] = {}


async def rate_limit_inactive(endpoint: str) -> None:
    """
    Wait until the rate limiter for `endpoint` has no remaining waiters.
    Join the shared drain operation on the requester loop.
    """
    limiter = limiters[endpoint]

    # Quick exit if no queued waiters
    if not limiter._waiters:
        return

    if not _requester.is_alive():
        raise _requester._exc.with_traceback(_requester._exc.__traceback__)

    caller_loop = get_running_loop()
    caller_future: asyncio.Future[None] = caller_loop.create_future()

    def finish(error: Exception | None = None) -> None:
        # Check on the caller's loop, where cancellation and completion are ordered.
        if caller_future.done():
            return
        if error is None:
            caller_future.set_result(None)
        else:
            caller_future.set_exception(error)

    async def check() -> None:
        try:
            # The requester loop already shares one drain operation per endpoint.
            # A caller-side lock would release queued calls one at a time and
            # prevent them from joining the same next batch.
            await _rate_limit_inactive(endpoint)
        except Exception as error:
            caller_loop.call_soon_threadsafe(finish, error)
        else:
            caller_loop.call_soon_threadsafe(finish)

    def start_check() -> None:
        task = create_task(check())
        tasks = TASKS
        tasks.add(task)
        task.add_done_callback(tasks.discard)

    handle = _requester.loop.call_soon_threadsafe(start_check)
    try:
        await caller_future
    except CancelledError:
        handle.cancel()
        raise


async def _rate_limit_inactive(endpoint: str) -> None:
    """
    Wait until the rate limiter for `endpoint` has no remaining waiters.
    Share the drain task and its result with other callers on the requester loop.
    """
    # Quick exit if no queued waiters (2nd check)
    if not limiters[endpoint]._waiters:
        return

    task = _rate_limit_tasks.get(endpoint)
    if task is None:
        task = create_task(__rate_limit_inactive(endpoint))
        _rate_limit_tasks[endpoint] = task

        def discard(completed: asyncio.Task[None]) -> None:
            if _rate_limit_tasks.get(endpoint) is completed:
                del _rate_limit_tasks[endpoint]

        task.add_done_callback(discard)
    logger.debug("rate limit is activated, waiting...")
    await shield(task)
    logger.debug("rate limit inactives, proceeding with more calls")


async def __rate_limit_inactive(endpoint: str) -> None:
    # sourcery skip: use-contextlib-suppress

    # alias this global var so we only look it up 1x
    yield_to_loop = sleep0

    # get the waiters for this particular endpoint
    waiters = limiters[endpoint]._waiters

    # run it
    while waiters:
        # pop last item
        last_waiter_tuple = nlargest(1, waiters)[0]
        last_waiter = last_waiter_tuple[-1]

        if last_waiter.cancelled():
            waiters.remove(last_waiter_tuple)
            continue

        if last_waiter.done():
            # NOTE: I don't think this is possible but want to confirm
            raise RuntimeError("last waiter is done")

        # await it
        try:
            await last_waiter
        except CancelledError:
            # AsyncLimiter cancels the fut as part of regular operation
            # This cannot be cancelled from above due to use of `asyncio.shield` in `rate_limit_inactive`
            pass

        # let recently popped waiters check the limiter for capacity, they might create new waiters
        # then, let recently popped waiters make some calls to see if we're still being limited
        for _ in range(10):
            if waiters:
                break
            await yield_to_loop()
