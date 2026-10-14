#!/usr/bin/env python3
"""Test a connection to an OCPP central system / CSMS over WS or WSS.

Connects as a charge point, negotiates the OCPP subprotocol, sends a
BootNotification and a Heartbeat, and prints the responses.

Examples:
    python test_ocpp_connection.py wss://csms.example.com/ocpp CP001
    python test_ocpp_connection.py wss://csms.example.com/ocpp CP001 \
        --ocpp 2.0.1 --password secret
    python test_ocpp_connection.py wss://localhost:9000 CP001 --insecure
    python test_ocpp_connection.py wss://csms.example.com/ocpp CP001 --port 8443
    python test_ocpp_connection.py wss://csms.example.com/ocpp CP001 --trailing-slash
    python test_ocpp_connection.py ws://homeassistant.local:9000 CP001
    python test_ocpp_connection.py csms.example.com/ocpp CP001 --no-tls
    python test_ocpp_connection.py wss://csms.example.com CP001 \
        --cert client.pem --key client.key --ca ca.pem
"""

import argparse
import asyncio
import base64
import json
import os
import ssl
import sys
import uuid
from urllib.parse import urlsplit, urlunsplit

try:
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed, InvalidStatus
except ImportError:
    # Re-run under the project's .venv if it exists and isn't already in use.
    here = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(here, ".venv", "bin", "python")
    if os.path.exists(venv_python) and sys.prefix != os.path.join(here, ".venv"):
        os.execv(venv_python, [venv_python, *sys.argv])
    sys.exit(
        "The 'websockets' package (version 14 or later) is not installed. Set it up with:\n"
        f"  python3 -m venv {os.path.join(here, '.venv')}\n"
        f"  {venv_python} -m pip install -r {os.path.join(here, 'requirements.txt')}"
    )

SUBPROTOCOLS = {"1.6": "ocpp1.6", "2.0.1": "ocpp2.0.1"}

# OCPP-J message type ids
CALL, CALLRESULT, CALLERROR = 2, 3, 4


def boot_payload(version, vendor, model):
    if version == "1.6":
        return {"chargePointVendor": vendor, "chargePointModel": model}
    return {
        "reason": "PowerUp",
        "chargingStation": {"vendorName": vendor, "model": model},
    }


def build_ssl_context(args):
    ctx = ssl.create_default_context(cafile=args.ca)
    if args.insecure:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if args.cert:
        ctx.load_cert_chain(args.cert, args.key)
    return ctx


async def call(ws, action, payload, timeout):
    msg_id = str(uuid.uuid4())
    request = [CALL, msg_id, action, payload]
    print(f"--> {json.dumps(request)}")
    await ws.send(json.dumps(request))

    # Server may send its own CALLs meanwhile; skip until our reply arrives.
    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout)
        print(f"<-- {raw}")
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
            raise RuntimeError(f"{action} failed: {msg[2]} {msg[3]}")
        return msg[2]


def build_url(base, charge_point_id, port, trailing_slash=False, tls=None):
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


async def run(args):
    url = build_url(args.url, args.charge_point_id, args.port, args.trailing_slash, args.tls)
    headers = {}
    # No --username/--password: connect without an Authorization header.
    # --username alone: Basic auth with an empty password.
    if args.username is not None or args.password is not None:
        user = args.username or args.charge_point_id
        password = args.password or ""
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["Authorization"] = f"Basic {token}"

    ssl_ctx = build_ssl_context(args) if url.startswith("wss://") else None
    if ssl_ctx is None and (args.cert or args.key or args.ca or args.insecure):
        print("WARNING: --cert/--key/--ca/--insecure are ignored without TLS (ws://)")
    subprotocol = SUBPROTOCOLS[args.ocpp]

    print(f"Connecting to {url} (subprotocol {subprotocol})")
    async with connect(
        url,
        subprotocols=[subprotocol],
        additional_headers=headers,
        ssl=ssl_ctx,
        open_timeout=args.timeout,
    ) as ws:
        print(f"Connected. Negotiated subprotocol: {ws.subprotocol}")
        if ws.subprotocol != subprotocol:
            print("WARNING: server did not accept the requested subprotocol")
        if ssl_ctx:
            tls = ws.transport.get_extra_info("ssl_object")
            print(f"TLS: {tls.version()} {tls.cipher()[0]}")
        else:
            print("TLS: none (plain ws://)")

        boot = await call(
            ws, "BootNotification",
            boot_payload(args.ocpp, args.vendor, args.model), args.timeout,
        )
        print(f"BootNotification status: {boot.get('status')}")

        hb = await call(ws, "Heartbeat", {}, args.timeout)
        print(f"Heartbeat server time: {hb.get('currentTime')}")


def report_close(e, args):
    if e.rcvd is not None:
        reason = f", reason: {e.rcvd.reason!r}" if e.rcvd.reason else ", no reason given"
        print(f"FAILED: server closed the connection (code {e.rcvd.code}{reason})")
    else:
        print("FAILED: connection dropped without a close frame")
    print(
        "The server accepted the WebSocket connection but closed it instead of replying.\n"
        "Common causes:\n"
        f"  - charge point ID {args.charge_point_id!r} is not registered on the server\n"
        "  - Home Assistant OCPP: accept the new charger under Settings -> Devices & services,\n"
        "    then run this test again\n"
        "  - the server requires authentication (--password, or --cert/--key)\n"
        "  - the server expects a different OCPP version (try --ocpp 2.0.1 or 1.6)\n"
        "  - the server expects a different URL form (try --trailing-slash)\n"
        "  - the server rejects the BootNotification fields (try --vendor/--model)\n"
        "Check the server logs for the exact reason."
    )


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("url", help="server base URL, e.g. wss://host:port/ocpp or ws://host:port (no scheme: wss)")
    p.add_argument("--port", type=int, help="override the port in the URL (default: URL port, or 443 for wss / 80 for ws)")
    p.add_argument("charge_point_id", help="charge point identity appended to the URL")
    tls = p.add_mutually_exclusive_group()
    tls.add_argument("--tls", dest="tls", action="store_true", default=None,
                     help="connect with TLS (wss://), overriding the URL scheme")
    tls.add_argument("--no-tls", dest="tls", action="store_false",
                     help="connect without TLS (ws://), overriding the URL scheme")
    p.add_argument("--trailing-slash", action="store_true", help="end the URL with '/' after the charge point id")
    p.add_argument("--ocpp", choices=SUBPROTOCOLS, default="1.6", help="OCPP version (default 1.6)")
    p.add_argument("--username", help="basic auth user (default: charge point id); alone, sends an empty password")
    p.add_argument("--password", help="basic auth password (security profile 1/2); omit both to connect without auth")
    p.add_argument("--cert", help="client certificate PEM (security profile 3)")
    p.add_argument("--key", help="client private key PEM")
    p.add_argument("--ca", help="CA bundle to verify the server certificate")
    p.add_argument("--insecure", action="store_true", help="skip server certificate verification")
    p.add_argument("--vendor", default="TestVendor")
    p.add_argument("--model", default="TestModel")
    p.add_argument("--timeout", type=float, default=15, help="seconds (default 15)")
    args = p.parse_args()
    if args.port is not None and not 1 <= args.port <= 65535:
        p.error("--port must be between 1 and 65535")

    try:
        asyncio.run(run(args))
    except ConnectionClosed as e:
        report_close(e, args)
        sys.exit(1)
    except InvalidStatus as e:
        print(f"FAILED: server rejected handshake with HTTP {e.response.status_code}")
        sys.exit(1)
    except ssl.SSLError as e:
        print(f"FAILED: TLS error: {e}")
        sys.exit(1)
    except (OSError, asyncio.TimeoutError, RuntimeError, ValueError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        sys.exit(1)
    print("SUCCESS")


if __name__ == "__main__":
    main()
