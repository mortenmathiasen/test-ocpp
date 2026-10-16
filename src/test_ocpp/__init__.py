"""Test a connection to an OCPP central system / CSMS over WS or WSS."""

__version__ = "0.1.0"

from .client import (  # noqa: E402
    SUBPROTOCOLS,
    CallError,
    ConnectionResult,
    build_url,
    check_connection,
)

__all__ = [
    "SUBPROTOCOLS",
    "CallError",
    "ConnectionResult",
    "build_url",
    "check_connection",
    "__version__",
]
