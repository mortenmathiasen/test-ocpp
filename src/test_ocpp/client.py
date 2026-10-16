"""Connect to an OCPP central system / CSMS as a charge point and check it responds."""

from __future__ import annotations

import asyncio
import base64
import json
import ssl
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Optional
from urllib.parse import urlsplit, urlunsplit

from websockets.asyncio.client import connect

SUBPROTOCOLS = {"1.6": "ocpp1.6", "2.0.1": "ocpp2.0.1"}

# OCPP-J message type ids
CALL, CALLRESULT, CALLERROR = 2, 3, 4


class CallError(RuntimeError):
    """The server answered a request with a CALLERROR."""


@dataclass
class ConnectionResult:
    url: str
    subprotocol: Optional[str]
    tls_version: Optional[str]
    tls_cipher: Optional[str]
    boot_notification: dict
    heartbeat: dict


def _silent(_msg: str) -> None:
    pass


def boot_payload(version: str, vendor: str, model: str) -> dict:
    if version == "1.6":
        return {"chargePointVendor": vendor, "chargePointModel": model}
    return {
        "reason": "PowerUp",
        "chargingStation": {"vendorName": vendor, "model": model},
    }


def build_ssl_context(ca=None, cert=None, key=None, insecure=False) -> ssl.SSLContext:
    ctx = ssl.create_default_context(cafile=ca)
    if insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if cert:
        ctx.load_cert_chain(cert, key)
    return ctx


def build_url(base, charge_point_id, port=None, trailing_slash=False, tls=None) -> str:
    if "://" not in base:
        base = "wss://" + base
    parts = urlsplit(base)
    if parts.scheme not in ("ws", "wss") or not parts.hostname:
        raise ValueError(f"URL must look like ws[s]://host[:port][/path], got {base!r}")
    if tls is not None:
        parts = parts._replace(scheme="wss" if tls else "ws")
    if port is not None:
        host = f"[{parts.hostname}]" if ":" in parts.hostname else parts.hostname
        parts = parts._replace(netloc=f"{host}:{port}")
    else:
        parts.port  # raises ValueError on an invalid port in the URL
    path = parts.path.rstrip("/") + "/" + charge_point_id
    if trailing_slash:
        path += "/"
    return urlunsplit(parts._replace(path=path))


def basic_auth_header(charge_point_id, username=None, password=None) -> dict:
    # No username/password: connect without an Authorization header.
    # username alone: Basic auth with an empty password.
    if username is None and password is None:
        return {}
    user = username or charge_point_id
    token = base64.b64encode(f"{user}:{password or ''}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


async def call(ws, action, payload, timeout, log: Callable[[str], Any] = _silent):
    msg_id = str(uuid.uuid4())
    request = [CALL, msg_id, action, payload]
    log(f"--> {json.dumps(request)}")
    await ws.send(json.dumps(request))

    # Server may send its own CALLs meanwhile; skip until our reply arrives.
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout)
        log(f"<-- {raw}")
        msg = json.loads(raw)
        if msg[0] == CALL:
            # Reply NotImplemented so the server isn't left hanging.
            await ws.send(json.dumps(
                [CALLERROR, msg[1], "NotImplemented", "Test client", {}]
            ))
            continue
        if msg[1] != msg_id:
            continue
        if msg[0] == CALLERROR:
            raise CallError(f"{action} failed: {msg[2]} {msg[3]}")
        return msg[2]


async def check_connection(
    url: str,
    charge_point_id: str,
    *,
    ocpp: str = "1.6",
    port: Optional[int] = None,
    tls: Optional[bool] = None,
    trailing_slash: bool = False,
    username: Optional[str] = None,
    password: Optional[str] = None,
    cert: Optional[str] = None,
    key: Optional[str] = None,
    ca: Optional[str] = None,
    insecure: bool = False,
    vendor: str = "TestVendor",
    model: str = "TestModel",
    timeout: float = 15,
    log: Callable[[str], Any] = _silent,
) -> ConnectionResult:
    """Connect as a charge point, send BootNotification and Heartbeat.

    Raises websockets' ConnectionClosed / InvalidStatus, ssl.SSLError,
    OSError, asyncio.TimeoutError, CallError or ValueError on failure.
    Pass ``log=print`` to see every message sent and received.
    """
    if ocpp not in SUBPROTOCOLS:
        raise ValueError(f"ocpp must be one of {', '.join(SUBPROTOCOLS)}, got {ocpp!r}")
    url = build_url(url, charge_point_id, port, trailing_slash, tls)
    headers = basic_auth_header(charge_point_id, username, password)

    ssl_ctx = build_ssl_context(ca, cert, key, insecure) if url.startswith("wss://") else None
    if ssl_ctx is None and (cert or key or ca or insecure):
        log("WARNING: --cert/--key/--ca/--insecure are ignored without TLS (ws://)")
    subprotocol = SUBPROTOCOLS[ocpp]

    log(f"Connecting to {url} (subprotocol {subprotocol})")
    async with connect(
        url,
        subprotocols=[subprotocol],
        additional_headers=headers,
        ssl=ssl_ctx,
        open_timeout=timeout,
    ) as ws:
        log(f"Connected. Negotiated subprotocol: {ws.subprotocol}")
        if ws.subprotocol != subprotocol:
            log("WARNING: server did not accept the requested subprotocol")
        tls_version = tls_cipher = None
        if ssl_ctx:
            tls_obj = ws.transport.get_extra_info("ssl_object")
            tls_version, tls_cipher = tls_obj.version(), tls_obj.cipher()[0]
            log(f"TLS: {tls_version} {tls_cipher}")
        else:
            log("TLS: none (plain ws://)")

        boot = await call(
            ws, "BootNotification", boot_payload(ocpp, vendor, model), timeout, log,
        )
        log(f"BootNotification status: {boot.get('status')}")

        hb = await call(ws, "Heartbeat", {}, timeout, log)
        log(f"Heartbeat server time: {hb.get('currentTime')}")

    return ConnectionResult(url, ws.subprotocol, tls_version, tls_cipher, boot, hb)
