"""A caller owns its remote HTTP work across the requester thread boundary."""

import asyncio
from collections import Counter
from contextlib import asynccontextmanager

import pytest

from dank_mids.helpers._requester import HTTPRequesterThread


@asynccontextmanager
async def requester():
    worker = HTTPRequesterThread()
    try:
        yield worker
    finally:

        async def close():
            # Cleanup follows each assertion so the failing control stays isolated.
            current = asyncio.current_task()
            pending = asyncio.all_tasks() - {current}
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if worker._session is not None:
                await worker._session.close()

        asyncio.run_coroutine_threadsafe(close(), worker.loop).result(timeout=5)
        worker.loop.call_soon_threadsafe(worker.loop.stop)
        worker.join(timeout=5)
        assert not worker.is_alive()
        assert worker.loop.is_closed()


@pytest.mark.parametrize("response_started", [False, True])
@pytest.mark.parametrize("concurrency", [1, 32])
def test_caller_cancellation_closes_remote_sockets(response_started, concurrency):
    async def check():
        active = set()
        received = []
        handlers = set()
        entered, closed = asyncio.Event(), asyncio.Event()

        async def serve(reader, writer):
            handler = asyncio.current_task()
            handlers.add(handler)
            active.add(writer)
            try:
                headers = await reader.readuntil(b"\r\n\r\n")
                length = next(
                    int(line.split(b":", 1)[1])
                    for line in headers.splitlines()
                    if line.lower().startswith(b"content-length:")
                )
                received.append(await reader.readexactly(length))
                if response_started:
                    writer.write(
                        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                        b"Content-Length: 1000\r\n\r\n{"
                    )
                    await writer.drain()
                if len(received) == concurrency:
                    entered.set()
                assert await reader.read() == b""
            finally:
                active.remove(writer)
                writer.close()
                await writer.wait_closed()
                if not active:
                    closed.set()
                handlers.remove(handler)

        async with await asyncio.start_server(serve, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with requester() as worker:
                tasks = [
                    asyncio.create_task(worker.post(f"http://127.0.0.1:{port}", data=b"owned"))
                    for _ in range(concurrency)
                ]
                try:
                    await asyncio.wait_for(entered.wait(), 5)
                    assert Counter(received) == {b"owned": concurrency}
                    for task in tasks:
                        task.cancel()
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    assert all(isinstance(result, asyncio.CancelledError) for result in results)
                    await asyncio.wait_for(closed.wait(), 2)
                    assert not active

                    # The same requester remains usable after the cancelled group.
                    async def ready(reader, writer):
                        await reader.readuntil(b"\r\n\r\n")
                        writer.write(
                            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                            b'Content-Length: 11\r\nConnection: close\r\n\r\n{"value":7}'
                        )
                        await writer.drain()
                        writer.close()
                        await writer.wait_closed()

                    async with await asyncio.start_server(ready, "127.0.0.1", 0) as available:
                        address = available.sockets[0].getsockname()[1]
                        assert await worker.post(f"http://127.0.0.1:{address}") == {"value": 7}
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    for writer in list(active):
                        writer.close()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)

    asyncio.run(check())
