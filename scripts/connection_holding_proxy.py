"""Connection-holding TCP front for the peer's public port (league interop).

Some opponents' clients fail hard on the first refused connection — zero
retries. Our runtime plays one sub-game per process, so the real MCP port
drops for a few seconds between sub-games. This proxy sits on the PUBLIC
port permanently: it always accepts, then patiently retries the backend
(the real peer) for up to --retry-seconds before piping bytes. A caller in
the restart gap waits a moment instead of ever seeing a refused connection.

    uv run python scripts/connection_holding_proxy.py \
        --listen 8801 --backend 8901 --retry-seconds 20
"""

import argparse
import asyncio

CHUNK = 65536


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(CHUNK)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except (ConnectionError, asyncio.IncompleteReadError, OSError):
        pass
    finally:
        try:
            writer.close()
        except OSError:  # pragma: no cover — teardown best-effort
            pass


async def _handle(client_r, client_w, backend_port: int, retry_seconds: float) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + retry_seconds
    while True:
        try:
            backend_r, backend_w = await asyncio.open_connection("127.0.0.1", backend_port)
            break
        except OSError:
            if loop.time() >= deadline:
                client_w.close()
                return
            await asyncio.sleep(0.25)
    await asyncio.gather(_pipe(client_r, backend_w), _pipe(backend_r, client_w))


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", type=int, required=True)
    parser.add_argument("--backend", type=int, required=True)
    parser.add_argument("--retry-seconds", type=float, default=20.0)
    args = parser.parse_args()

    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, args.backend, args.retry_seconds),
        "127.0.0.1", args.listen,
    )
    print(f"proxy up: {args.listen} -> 127.0.0.1:{args.backend} "
          f"(backend retry window {args.retry_seconds:.0f}s)", flush=True)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
