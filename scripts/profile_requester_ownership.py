"""Measure cancelled HTTP ownership with a fixed local workload and no forced GC."""

import argparse
import asyncio
import faulthandler
import signal
import hashlib
import json
import resource
import time
import tracemalloc
from pathlib import Path
from typing import Any

from dank_mids.helpers._requester import HTTPRequesterThread


async def measure(output: Path, allocations: bool, rounds: int) -> None:
    worker = HTTPRequesterThread()
    active: set[asyncio.StreamWriter] = set()
    handlers: set[asyncio.Task[Any]] = set()
    received: list[str] = []
    entered = asyncio.Event()
    target = 0
    clients: list[asyncio.Task[Any]] = []
    samples: list[dict[str, Any]] = []
    complete = False

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        handler = asyncio.current_task()
        assert handler is not None
        handlers.add(handler)
        active.add(writer)
        try:
            headers = await reader.readuntil(b"\r\n\r\n")
            length = next(
                int(line.split(b":", 1)[1])
                for line in headers.splitlines()
                if line.lower().startswith(b"content-length:")
            )
            body = await reader.readexactly(length)
            received.append(hashlib.sha256(body).hexdigest())
            del body, headers
            if len(received) == target:
                entered.set()
            await reader.read()
        finally:
            active.remove(writer)
            writer.close()
            await writer.wait_closed()
            handlers.remove(handler)

    async def task_count() -> int:
        return len(asyncio.all_tasks()) - 1

    async def close_worker() -> None:
        pending = asyncio.all_tasks() - {asyncio.current_task()}
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if worker._session is not None:
            await worker._session.close()

    if allocations:
        tracemalloc.start()
    started = time.perf_counter()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        for index in range(rounds):
            entered.clear()
            target += 64
            clients = [
                asyncio.create_task(
                    worker.post(
                        f"http://127.0.0.1:{port}",
                        data=json.dumps(
                            {
                                "jsonrpc": "2.0",
                                "id": index * 64 + key,
                                "method": "eth_call",
                                "params": [],
                                "diagnostic": "x" * (128 * 1024),
                            }
                        ).encode(),
                    )
                )
                for key in range(64)
            ]
            await asyncio.wait_for(entered.wait(), 10)
            for client in clients:
                client.cancel()
            results = await asyncio.gather(*clients, return_exceptions=True)
            assert all(isinstance(result, asyncio.CancelledError) for result in results)
            del clients[:], results
            # Both revisions receive the same fixed cancellation-settlement interval.
            await asyncio.sleep(0.1)
            pending = await asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(task_count(), worker.loop)
            )
            rss = next(
                int(line.split()[1]) * 1024
                for line in Path("/proc/self/status").read_text().splitlines()
                if line.startswith("VmRSS:")
            )
            samples.append(
                {
                    "round": index + 1,
                    "http_calls": len(received),
                    "open_server_connections": len(active),
                    "pending_requester_tasks": pending,
                    "process_fds": len(list(Path("/proc/self/fd").iterdir())),
                    "rss_current_bytes": rss,
                }
            )
        assert len(received) == rounds * 64 and len(set(received)) == rounds * 64
        complete = True
    finally:
        current, peak = tracemalloc.get_traced_memory()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "complete": complete,
                    "concurrency": 64,
                    "rounds": rounds,
                    "http_calls": len(received),
                    "request_body_hashes": received,
                    "samples": samples,
                    "elapsed_seconds": time.perf_counter() - started,
                    "rss_peak_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                    "python_current_bytes": current if allocations else None,
                    "python_peak_bytes": peak if allocations else None,
                    "profiler": "tracemalloc; exclude timings" if allocations else None,
                    "gc_policy": "normal cyclic collection; no explicit collection",
                    "boundary": "Local HTTP sockets; all measurements precede final cleanup",
                },
                indent=2,
            )
            + "\n"
        )
        # Clean up only after the workload has written its retained-state evidence.
        for client in clients:
            client.cancel()
        await asyncio.gather(*clients, return_exceptions=True)
        await asyncio.wrap_future(asyncio.run_coroutine_threadsafe(close_worker(), worker.loop))
        worker.loop.call_soon_threadsafe(worker.loop.stop)
        worker.join(timeout=5)
        assert not worker.is_alive()
        for writer in list(active):
            writer.close()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        server.close()
        await server.wait_closed()


if __name__ == "__main__":
    faulthandler.register(signal.SIGUSR1, all_threads=True)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allocations", action="store_true")
    parser.add_argument("--rounds", type=int, default=4)
    args = parser.parse_args()
    if args.rounds < 1:
        parser.error("rounds must be positive")
    asyncio.run(measure(args.output, args.allocations, args.rounds))
