"""Test a connection to an OCPP central system / CSMS over WS or WSS.

Connects as a charge point, negotiates the OCPP subprotocol, sends a
BootNotification and a Heartbeat, and prints the responses.

Examples:
    test-ocpp wss://csms.example.com/ocpp CP001
    test-ocpp wss://csms.example.com/ocpp CP001 --ocpp 2.0.1 --password secret
    test-ocpp wss://localhost:9000 CP001 --insecure
    test-ocpp wss://csms.example.com/ocpp CP001 --port 8443
    test-ocpp wss://csms.example.com/ocpp CP001 --trailing-slash
    test-ocpp ws://homeassistant.local:9000 CP001
    test-ocpp csms.example.com/ocpp CP001 --no-tls
    test-ocpp wss://csms.example.com CP001 \\
        --cert client.pem --key client.key --ca ca.pem
"""

import argparse
import asyncio
import ssl
import sys

from websockets.exceptions import ConnectionClosed, InvalidStatus

from . import __version__
from .client import SUBPROTOCOLS, CallError, check_connection


def report_close(e, charge_point_id):
    if e.rcvd is not None:
        reason = f", reason: {e.rcvd.reason!r}" if e.rcvd.reason else ", no reason given"
        print(f"FAILED: server closed the connection (code {e.rcvd.code}{reason})")
    else:
        print("FAILED: connection dropped without a close frame")
    print(
        "The server accepted the WebSocket connection but closed it instead of replying.\n"
        "Common causes:\n"
        f"  - charge point ID {charge_point_id!r} is not registered on the server\n"
        "  - Home Assistant OCPP: accept the new charger under Settings -> Devices & services,\n"
        "    then run this test again\n"
        "  - the server requires authentication (--password, or --cert/--key)\n"
        "  - the server expects a different OCPP version (try --ocpp 2.0.1 or 1.6)\n"
        "  - the server expects a different URL form (try --trailing-slash)\n"
        "  - the server rejects the BootNotification fields (try --vendor/--model)\n"
        "Check the server logs for the exact reason."
    )


def build_parser():
    p = argparse.ArgumentParser(prog="test-ocpp", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    return p


def main(argv=None):
    p = build_parser()
    args = p.parse_args(argv)
    if args.port is not None and not 1 <= args.port <= 65535:
        p.error("--port must be between 1 and 65535")

    try:
        asyncio.run(check_connection(
            args.url, args.charge_point_id,
            ocpp=args.ocpp, port=args.port, tls=args.tls,
            trailing_slash=args.trailing_slash,
            username=args.username, password=args.password,
            cert=args.cert, key=args.key, ca=args.ca, insecure=args.insecure,
            vendor=args.vendor, model=args.model, timeout=args.timeout,
            log=print,
        ))
    except ConnectionClosed as e:
        report_close(e, args.charge_point_id)
        return 1
    except InvalidStatus as e:
        print(f"FAILED: server rejected handshake with HTTP {e.response.status_code}")
        return 1
    except ssl.SSLError as e:
        print(f"FAILED: TLS error: {e}")
        return 1
    except (OSError, asyncio.TimeoutError, CallError, ValueError) as e:
        print(f"FAILED: {type(e).__name__}: {e}")
        return 1
    print("SUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
