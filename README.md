# OCPP WS/WSS connection tester

`test-ocpp` connects using Open Charge Point Protocol (OCPP) to a Charging Station Management System (CSMS) as a Charging Station, either over WebSocket Secure (`wss://`, TLS) or plain WebSocket (`ws://`), then:

1. Negotiates the OCPP subprotocol (`ocpp1.6` or `ocpp2.0.1`)
2. Sends a `BootNotification`
3. Sends a `Heartbeat`

It prints every message sent and received, the negotiated subprotocol, and the TLS version and cipher (or `TLS: none` for `ws://`). It exits with `0` on success and `1` on failure.

## Installation

Requires Python 3.9+. Install the `test-ocpp` command with [pipx](https://pipx.pypa.io/):

```bash
pipx install test-ocpp
```

Or into a virtual environment with pip:

```bash
python3 -m venv .venv
.venv/bin/pip install test-ocpp
.venv/bin/test-ocpp --help
```

Don't `pip install` against the system Python. On Debian/Ubuntu it fails with `externally-managed-environment`.

### From a source checkout

```bash
git clone https://github.com/mortenmathiasen/test-ocpp.git
cd test-ocpp
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

In a checkout, `./test-ocpp ...` works like the installed `test-ocpp ...` without activating the venv: if `websockets` is missing, it restarts itself with `.venv/bin/python`. `python -m test_ocpp ...` also works wherever the package is installed.

## Usage

```
test-ocpp URL CHARGE_POINT_ID [options]
```

The charge point ID is appended to the URL, so `wss://host/ocpp` + `CP001` connects to `wss://host/ocpp/CP001`. A trailing slash on the base URL doesn't matter. If the server needs the URL to end in a slash (`wss://host/ocpp/CP001/`), add `--trailing-slash`.

### TLS or no TLS

The URL scheme picks the transport: `wss://` uses TLS and `ws://` doesn't. If you leave out the scheme (`csms.example.com/ocpp`), `test-ocpp` uses `wss://`. `--tls` and `--no-tls` override the scheme, so you can switch transports without editing the URL. The certificate options (`--cert`, `--key`, `--ca`, `--insecure`) only apply with TLS. With `ws://` they're ignored and `test-ocpp` prints a warning.

### Port

The port can be any port from 1 to 65535. Put it in the URL (`wss://host:8443/ocpp`) or pass `--port`, which overrides any port in the URL. Without either, the port is 443 for `wss://` and 80 for `ws://`.

| Option | Description |
| --- | --- |
| `--tls` | Connect with TLS (`wss://`), overriding the URL scheme |
| `--no-tls` | Connect without TLS (`ws://`), overriding the URL scheme |
| `--port PORT` | Server port, overriding any port in the URL |
| `--trailing-slash` | End the URL with `/` after the charge point ID |
| `--ocpp {1.6,2.0.1}` | OCPP version (default `1.6`) |
| `--username USER` | Basic auth username (default: the charge point ID). On its own, sends an empty password |
| `--password PASS` | Basic auth password (security profile 1/2) |
| `--cert FILE` | Client certificate PEM (security profile 3) |
| `--key FILE` | Client private key PEM |
| `--ca FILE` | CA bundle used to verify the server certificate |
| `--insecure` | Skip server certificate verification |
| `--vendor NAME` | Vendor sent in BootNotification (default `TestVendor`) |
| `--model NAME` | Model sent in BootNotification (default `TestModel`) |
| `--timeout SECONDS` | Connect and response timeout (default `15`) |

## Examples

OCPP 1.6 connection without authentication. With neither `--username` nor `--password`, no `Authorization` header is sent:

```bash
test-ocpp wss://csms.example.com/ocpp CP001
```

Non-standard port, either in the URL or with `--port`:

```bash
test-ocpp wss://csms.example.com:8443/ocpp CP001
test-ocpp wss://csms.example.com/ocpp CP001 --port 8443
```

Without TLS, for example Home Assistant on its default port 9000 without SSL. These two commands are equivalent:

```bash
test-ocpp ws://homeassistant.local:9000 CP001
test-ocpp wss://homeassistant.local:9000 CP001 --no-tls
```

Server that requires a trailing slash. This connects to `wss://csms.example.com/ocpp/CP001/`:

```bash
test-ocpp wss://csms.example.com/ocpp CP001 --trailing-slash
```

OCPP 2.0.1:

```bash
test-ocpp wss://csms.example.com/ocpp CP001 --ocpp 2.0.1
```

Basic auth with a username and no password. This sends `station-a:` (an empty password):

```bash
test-ocpp wss://csms.example.com/ocpp CP001 --username station-a
```

Basic auth (security profile 2). The username defaults to the charge point ID:

```bash
test-ocpp wss://csms.example.com/ocpp CP001 --password secret
test-ocpp wss://csms.example.com/ocpp CP001 --username station-a --password secret
```

Client certificate (security profile 3), with a private CA:

```bash
test-ocpp wss://csms.example.com/ocpp CP001 \
    --cert client.pem --key client.key --ca ca.pem
```

Server with a self-signed certificate. Pass the certificate with `--ca` to trust it, or use `--insecure` to skip verification:

```bash
test-ocpp wss://localhost:9000 CP001 --ca server.pem
test-ocpp wss://localhost:9000 CP001 --insecure
```

Custom vendor/model and a longer timeout:

```bash
test-ocpp wss://csms.example.com/ocpp CP001 \
    --vendor Acme --model FastCharger --timeout 30
```

Use in a shell script or CI check:

```bash
if test-ocpp wss://csms.example.com/ocpp CP001 --password secret > /dev/null; then
    echo "CSMS reachable"
fi
```

## Example output

```
Connecting to wss://localhost:9443/CP001 (subprotocol ocpp1.6)
Connected. Negotiated subprotocol: ocpp1.6
TLS: TLSv1.3 TLS_AES_256_GCM_SHA384
--> [2, "0efb16e6-...", "BootNotification", {"chargePointVendor": "TestVendor", "chargePointModel": "TestModel"}]
<-- [3, "0efb16e6-...", {"status": "Accepted", "currentTime": "2026-10-12T00:00:00Z", "interval": 300}]
BootNotification status: Accepted
--> [2, "033cea3a-...", "Heartbeat", {}]
<-- [3, "033cea3a-...", {"currentTime": "2026-10-12T00:00:00Z"}]
Heartbeat server time: 2026-10-12T00:00:00Z
SUCCESS
```

## Troubleshooting

| Output | Likely cause |
| --- | --- |
| `The 'websockets' package ... is not installed` | Running `./test-ocpp` from a checkout without `.venv`. Follow [From a source checkout](#from-a-source-checkout) |
| `server rejected handshake with HTTP 401` | Wrong or missing credentials (`--username` / `--password`) |
| `server rejected handshake with HTTP 404` | Wrong URL path or unknown charge point ID |
| `TLS error: ... CERTIFICATE_VERIFY_FAILED` | Server certificate isn't trusted. Pass `--ca`, or use `--insecure` for testing only |
| `WARNING: server did not accept the requested subprotocol` | Server doesn't support the chosen `--ocpp` version |
| `Connect call failed ... [Errno 111]` | Nothing is listening on that host and port. Check the port |
| `ValueError: Port out of range` / `URL must look like ws[s]://...` | Malformed URL. Use `wss://host[:port][/path]` or `ws://host[:port][/path]` |
| `server closed the connection (code 1000 ...)` right after `BootNotification` | The server accepted the connection but rejected the charge point. Usually the charge point ID isn't registered, authentication is missing, the OCPP version is wrong, or the server needs `--trailing-slash`. With Home Assistant, accept the charger first (see [Home Assistant OCPP](#home-assistant-ocpp)). Check the server logs |
| `ConnectionResetError` or `TLS error: ... WRONG_VERSION_NUMBER` with `wss://` | The server may not use TLS on that port. Try `ws://` or `--no-tls` |
| `TimeoutError` | Server unreachable, a firewall is blocking the connection, or no response within `--timeout` |
| `BootNotification failed: ...` | Server returned a CALLERROR, for example for an invalid payload |

If the server sends its own requests during the test, `test-ocpp` replies with a `NotImplemented` CALLERROR and keeps waiting for its own responses.

## Python API

The same check is available from Python, for example in your own test suite:

```python
import asyncio
from test_ocpp import check_connection

result = asyncio.run(check_connection(
    "wss://csms.example.com/ocpp", "CP001",
    ocpp="2.0.1", password="secret", timeout=10,
))
print(result.subprotocol, result.tls_version, result.boot_notification["status"])
```

`check_connection` takes the same options as the command line, as keyword arguments (`port`, `tls`, `trailing_slash`, `username`, `password`, `cert`, `key`, `ca`, `insecure`, `vendor`, `model`, `timeout`). It returns a `ConnectionResult` with `url`, `subprotocol`, `tls_version`, `tls_cipher`, `boot_notification` and `heartbeat`. Pass `log=print` to see the messages as the CLI prints them.

On failure it raises instead of returning: `websockets.exceptions.InvalidStatus` (HTTP error during the handshake), `websockets.exceptions.ConnectionClosed`, `ssl.SSLError`, `OSError`, `asyncio.TimeoutError`, `test_ocpp.CallError` (the server answered with a CALLERROR) or `ValueError` (malformed URL).

## Home Assistant OCPP

With the [Home Assistant OCPP integration](https://github.com/lbbrhzn/ocpp), the first connection from a new charge point ID is expected to fail with `server closed the connection (code 1000, no reason given)`. Home Assistant starts a discovery flow for the unknown charger and then closes the connection.

1. In Home Assistant, open **Settings → Devices & services** and add the discovered **OCPP** charger.
2. Wait for the integration to reload, then run `test-ocpp` again with the same charge point ID.

Home Assistant uses the last path segment of the URL as the charge point ID and ignores slashes, so `--trailing-slash` makes no difference.

## References

- [Open Charge Alliance](https://openchargealliance.org): publisher of the OCPP specifications

## License

MIT. See [LICENSE](https://github.com/mortenmathiasen/test-ocpp/blob/main/LICENSE).
