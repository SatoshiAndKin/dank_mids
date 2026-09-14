import asyncio
import atexit
import threading
from collections.abc import Callable
from typing import Any, Final, final

from aiohttp import ClientTimeout, TCPConnector
from aiohttp.typedefs import DEFAULT_JSON_DECODER

from dank_mids import ENVIRONMENT_VARIABLES as ENVS
from dank_mids.helpers._session import DankClientSession
from dank_mids.types import T


@final
class HTTPRequesterThread(threading.Thread):
    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.loop: Final = asyncio.new_event_loop()
        self._session: DankClientSession | None = None
        self.start()

    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            self._exc = e
        finally:
            self.loop.close()

    @property
    def session(self) -> DankClientSession:
        session = self._session
        if session is None:
            connector = TCPConnector(limit=0, enable_cleanup_closed=True)
            client_timeout = ClientTimeout(int(ENVS.AIOHTTP_TIMEOUT))
            session = self._session = DankClientSession(
                connector=connector,
                headers={"content-type": "application/json"},
                timeout=client_timeout,
                raise_for_status=True,
                read_bufsize=2**20,
            )
        return session

    async def post(
        self,
        endpoint: str,
        *args: Any,
        loads: Callable[[str], T] = DEFAULT_JSON_DECODER,
        **kwargs: Any,
    ) -> T:
        """Returns decoded json data from `endpoint`."""
        if not self.is_alive():
            raise self._exc.with_traceback(self._exc.__traceback__)

        async def request() -> T:
            # Construct and use the session on its owning thread. The standard
            # future bridge carries cancellation and results in both directions.
            return await self.session.post(endpoint, *args, loads=loads, **kwargs)

        return await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(request(), self.loop))


def shutdown_http_requester() -> None:
    if not _requester.is_alive():
        return

    async def close_session() -> None:
        if session := _requester._session:
            await session.close()

    # Keep the loop running until it transfers the coroutine result to the
    # concurrent future. Stopping inside the coroutine prevents that transfer.
    asyncio.run_coroutine_threadsafe(close_session(), _requester.loop).result()
    _requester.loop.call_soon_threadsafe(_requester.loop.stop)
    _requester.join()


_requester = HTTPRequesterThread()
atexit.register(shutdown_http_requester)
