"""
SPDZ Aggregation Party
======================

Each AS node runs this code as either Party 0 (listener) or Party 1 (connector).
The party role, peer IP/port, and TLS certificates are injected via algorithm_env
in the vantage6 node config — the task input only carries the secret shares.

Protocol (secure sum)
---------------------
Given n CPs each with a secret value v_i:
  - Each CP splits v_i into (share_a_i, share_b_i) where share_a + share_b = v_i
  - AS-1 receives [share_a_1, share_a_2, ...]
  - AS-2 receives [share_b_1, share_b_2, ...]

  Party 0: partial_0 = sum(shares_received_by_AS1)
  Party 1: partial_1 = sum(shares_received_by_AS2)

  They exchange partial sums over a mTLS-secured direct TCP connection.
  Both compute: aggregate = partial_0 + partial_1 = sum(v_i)  ✓

Privacy: AS-1 alone sees only random noise.
         AS-2 alone sees only random noise.
         Neither can reconstruct individual v_i.

Security: mTLS — both parties authenticate with certificates;
          only the legitimate AS-1/AS-2 pair can communicate.
"""

import asyncio
import json
import os
import ssl
import struct
import tempfile

from vantage6.algorithm.tools.util import info

# ── Environment variable keys (set in vantage6 node config) ──────────────────
ENV_PARTY_ID    = 'SPDZ_PARTY_ID'      # "0" or "1"
ENV_LISTEN_PORT = 'SPDZ_LISTEN_PORT'   # port Party 0 listens on
ENV_PEER_HOST   = 'SPDZ_PEER_HOST'     # IP of the other party
ENV_PEER_PORT   = 'SPDZ_PEER_PORT'     # port of the other party
ENV_MY_CERT     = 'AS_MY_CERT'         # PEM certificate for this party
ENV_MY_KEY      = 'AS_MY_KEY'          # PEM private key for this party
ENV_PEER_CERT   = 'AS_PEER_CERT'       # PEM certificate of the peer (for verification)

# ── Wire protocol helpers ────────────────────────────────────────────────────

async def _send(writer: asyncio.StreamWriter, payload: dict) -> None:
    """Send a JSON-encoded message prefixed with a 4-byte big-endian length."""
    data = json.dumps(payload).encode('utf-8')
    header = struct.pack('>I', len(data))
    writer.write(header + data)
    await writer.drain()


async def _recv(reader: asyncio.StreamReader) -> dict:
    """Receive a length-prefixed JSON message."""
    header = await reader.readexactly(4)
    length = struct.unpack('>I', header)[0]
    data = await reader.readexactly(length)
    return json.loads(data.decode('utf-8'))


# ── TLS context builders ─────────────────────────────────────────────────────

def _write_pem_tempfile(content: str) -> str:
    """Write PEM string to a temp file, return the path."""
    f = tempfile.NamedTemporaryFile(mode='w', suffix='.pem', delete=False)
    f.write(content.strip() + '\n')
    f.close()
    return f.name


def _build_server_ssl_ctx(my_cert: str, my_key: str, peer_cert: str) -> ssl.SSLContext:
    """
    Build an SSL context for Party 0 (the listening server).
    Requires the peer (Party 1) to present a valid certificate.
    """
    cert_path = _write_pem_tempfile(my_cert)
    key_path  = _write_pem_tempfile(my_key)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert_path, key_path)
    ctx.load_verify_locations(cadata=peer_cert)   # peer cert as string
    ctx.verify_mode = ssl.CERT_REQUIRED

    # Clean up temp files immediately after loading
    os.unlink(cert_path)
    os.unlink(key_path)
    return ctx


def _build_client_ssl_ctx(my_cert: str, my_key: str, peer_cert: str) -> ssl.SSLContext:
    """
    Build an SSL context for Party 1 (the connecting client).
    Verifies that the server presents the expected certificate.
    """
    cert_path = _write_pem_tempfile(my_cert)
    key_path  = _write_pem_tempfile(my_key)

    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False          # self-signed cert, no hostname match
    ctx.load_cert_chain(cert_path, key_path)
    ctx.load_verify_locations(cadata=peer_cert)
    ctx.verify_mode = ssl.CERT_REQUIRED

    os.unlink(cert_path)
    os.unlink(key_path)
    return ctx


# ── Party 0 — listener ───────────────────────────────────────────────────────

async def _run_party0(shares: list, listen_port: int, ssl_ctx: ssl.SSLContext) -> float:
    """
    Party 0 protocol:
      1. Listen for one incoming mTLS connection from Party 1.
      2. Compute partial_0 = sum(my shares).
      3. Exchange partial sums concurrently (both send, both receive).
      4. Compute and return aggregate = partial_0 + partial_1.
    """
    partial_0 = sum(shares)
    info(f'SPDZ Party 0: partial_sum = {partial_0:.6f}  (from {len(shares)} shares)')

    aggregate_result: dict = {}
    connection_event = asyncio.Event()

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info('peername')
        info(f'SPDZ Party 0: Party 1 connected from {peer}')

        # Concurrent send + receive to avoid deadlock
        send_task = asyncio.create_task(_send(writer, {'partial': partial_0}))
        recv_task = asyncio.create_task(_recv(reader))
        await asyncio.gather(send_task, recv_task)
        msg = recv_task.result()

        partial_1 = msg['partial']
        aggregate  = partial_0 + partial_1
        info(f'SPDZ Party 0: partial_1 = {partial_1:.6f}  →  aggregate = {aggregate:.6f}')

        aggregate_result['value'] = aggregate
        writer.close()
        connection_event.set()   # signal that we're done

    server = await asyncio.start_server(
        _handle, '0.0.0.0', listen_port, ssl=ssl_ctx
    )
    info(f'SPDZ Party 0: listening on port {listen_port} (mTLS)')

    async with server:
        # Wait until one connection has been fully handled (or timeout)
        await asyncio.wait_for(connection_event.wait(), timeout=300)

    return aggregate_result['value']


# ── Party 1 — connector ───────────────────────────────────────────────────────

async def _connect_with_retry(
    host: str,
    port: int,
    ssl_ctx: ssl.SSLContext,
    retry_interval: float = 3.0,
    timeout: float = 120.0,
) -> tuple:
    """
    Try to connect to Party 0, retrying every `retry_interval` seconds
    until `timeout` seconds have elapsed.  This absorbs the container
    startup race condition without any sleep in the central task.
    """
    import time
    deadline = time.monotonic() + timeout
    attempt  = 0

    while time.monotonic() < deadline:
        try:
            reader, writer = await asyncio.open_connection(host, port, ssl=ssl_ctx)
            info(f'SPDZ Party 1: connected to {host}:{port} after {attempt} retries')
            return reader, writer
        except (ConnectionRefusedError, OSError) as exc:
            attempt += 1
            info(f'SPDZ Party 1: retry {attempt} ({exc}), next in {retry_interval}s...')
            await asyncio.sleep(retry_interval)

    raise TimeoutError(
        f'SPDZ Party 1: could not reach {host}:{port} within {timeout}s'
    )


async def _run_party1(
    shares: list,
    peer_host: str,
    peer_port: int,
    ssl_ctx: ssl.SSLContext,
) -> float:
    """
    Party 1 protocol:
      1. Connect to Party 0 (with retry loop).
      2. Compute partial_1 = sum(my shares).
      3. Exchange partial sums concurrently.
      4. Compute and return aggregate = partial_0 + partial_1.
    """
    partial_1 = sum(shares)
    info(f'SPDZ Party 1: partial_sum = {partial_1:.6f}  (from {len(shares)} shares)')

    reader, writer = await _connect_with_retry(peer_host, peer_port, ssl_ctx)

    send_task = asyncio.create_task(_send(writer, {'partial': partial_1}))
    recv_task = asyncio.create_task(_recv(reader))
    await asyncio.gather(send_task, recv_task)
    msg = recv_task.result()

    partial_0 = msg['partial']
    aggregate  = partial_0 + partial_1
    info(f'SPDZ Party 1: partial_0 = {partial_0:.6f}  →  aggregate = {aggregate:.6f}')

    writer.close()
    await writer.wait_closed()
    return aggregate


# ── vantage6 entry point ─────────────────────────────────────────────────────

def spdz_compute(shares: list) -> dict:
    """
    vantage6-callable SPDZ aggregation function.

    All configuration (party role, peer address, certificates) is read
    from environment variables set in the vantage6 node config so that
    the same Docker image works for both AS-1 and AS-2.

    Parameters
    ----------
    shares : list of float
        The additive shares this party received from the central orchestrator.
        AS-1 gets the 'for_as1' shares; AS-2 gets the 'for_as2' shares.

    Returns
    -------
    dict
        {'aggregate': float}  — the securely computed sum of all CP values.
    """
    # Read configuration from environment
    party_id    = int(os.environ.get(ENV_PARTY_ID, '0'))
    listen_port = int(os.environ.get(ENV_LISTEN_PORT, '14000'))
    peer_host   =     os.environ.get(ENV_PEER_HOST, '')
    peer_port   = int(os.environ.get(ENV_PEER_PORT, '14000'))
    my_cert     =     os.environ.get(ENV_MY_CERT, '')
    my_key      =     os.environ.get(ENV_MY_KEY, '')
    peer_cert   =     os.environ.get(ENV_PEER_CERT, '')

    # Validate required config
    if not my_cert or not my_key or not peer_cert:
        raise RuntimeError(
            'SPDZ: Missing certificate config. '
            'Set AS_MY_CERT, AS_MY_KEY, AS_PEER_CERT in algorithm_env.'
        )
    if party_id == 1 and not peer_host:
        raise RuntimeError(
            'SPDZ: Party 1 needs SPDZ_PEER_HOST in algorithm_env.'
        )

    info(f'SPDZ: Starting as Party {party_id}')
    info(f'SPDZ: Received {len(shares)} shares')

    if party_id == 0:
        ssl_ctx   = _build_server_ssl_ctx(my_cert, my_key, peer_cert)
        aggregate = asyncio.run(_run_party0(shares, listen_port, ssl_ctx))
    else:
        ssl_ctx   = _build_client_ssl_ctx(my_cert, my_key, peer_cert)
        aggregate = asyncio.run(
            _run_party1(shares, peer_host, peer_port, ssl_ctx)
        )

    info(f'SPDZ: Party {party_id} complete — aggregate = {aggregate:.6f}')
    return {'aggregate': aggregate}
