"""Answers as one host, `druid`, for the Druid services of the perf stack.

Harmony's Druid client derives every endpoint from one DRUID_HOST plus a fixed
port (db/druid/config.py: 8081 coordinator, 8082 broker, 8888 router), while
druid_setup/single runs each service in its own container. This forwarder is
the only container on both the Druid network and the web network, so web never
gets the Druid network's route out.
"""

import asyncio

ROUTES = {8081: 'coordinator', 8082: 'broker', 8888: 'router'}


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while chunk := await reader.read(1 << 16):
            writer.write(chunk)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        writer.close()


def handler(target_host: str, target_port: int):
    async def handle(
        client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
    ) -> None:
        try:
            upstream_reader, upstream_writer = await asyncio.open_connection(
                target_host, target_port
            )
        except OSError:
            client_writer.close()
            return
        await asyncio.gather(
            pipe(client_reader, upstream_writer), pipe(upstream_reader, client_writer)
        )

    return handle


async def main() -> None:
    # Inside the forwarder's container, reached only over the internal Compose
    # networks; druid.override.yaml publishes none of these ports.
    servers = [
        await asyncio.start_server(handler(host, port), '0.0.0.0', port)  # noqa: S104
        for port, host in ROUTES.items()
    ]
    await asyncio.gather(*(server.serve_forever() for server in servers))


if __name__ == '__main__':
    asyncio.run(main())
