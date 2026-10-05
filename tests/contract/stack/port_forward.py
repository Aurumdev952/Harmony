"""Forwards the published loopback port to web on the internal network.

Docker cannot publish a port from a container whose only network is
`internal: true`, and attaching web to a routable network would give it
egress (Mailgun, Urlbox, CloudFront). This forwarder is the only container on
both networks and runs nothing but this loop.
"""

import asyncio
import os

TARGET_HOST = os.environ.get("FORWARD_TO_HOST", "web")
TARGET_PORT = int(os.environ.get("FORWARD_TO_PORT", "5000"))


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(65536):
            writer.write(chunk)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


async def handle(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    try:
        upstream_reader, upstream_writer = await asyncio.open_connection(
            TARGET_HOST, TARGET_PORT
        )
    except OSError:
        client_writer.close()
        return
    await asyncio.gather(
        pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer)
    )


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", 5000)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
