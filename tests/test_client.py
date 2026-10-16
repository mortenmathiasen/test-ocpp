import asyncio
import json

import pytest
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from test_ocpp import CallError, build_url, check_connection
from test_ocpp.cli import main


@pytest.mark.parametrize("base, kwargs, expected", [
    ("wss://host/ocpp", {}, "wss://host/ocpp/CP1"),
    ("wss://host/ocpp/", {}, "wss://host/ocpp/CP1"),
    ("host/ocpp", {}, "wss://host/ocpp/CP1"),
    ("ws://host:9000", {}, "ws://host:9000/CP1"),
    ("wss://host:9000", {"tls": False}, "ws://host:9000/CP1"),
    ("ws://host", {"tls": True}, "wss://host/CP1"),
    ("wss://host:1/ocpp", {"port": 8443}, "wss://host:8443/ocpp/CP1"),
    ("wss://[::1]/ocpp", {"port": 8443}, "wss://[::1]:8443/ocpp/CP1"),
    ("wss://host/ocpp", {"trailing_slash": True}, "wss://host/ocpp/CP1/"),
])
def test_build_url(base, kwargs, expected):
    assert build_url(base, "CP1", **kwargs) == expected


@pytest.mark.parametrize("base", ["http://host", "wss://", "wss://host:99999"])
def test_build_url_invalid(base):
    with pytest.raises(ValueError):
        build_url(base, "CP1")


def fake_csms(boot_reply=None, close_on_boot=False, seen=None):
    async def handler(ws):
        if seen is not None:
            seen["path"] = ws.request.path
            seen["auth"] = ws.request.headers.get("Authorization")
        async for raw in ws:
            msg = json.loads(raw)
            if msg[0] != 2:
                continue  # client's reply to our Reset
            msg_id, action = msg[1], msg[2]
            if action == "BootNotification":
                if close_on_boot:
                    await ws.close()
                    return
                # Send our own CALL first; the client must answer and keep waiting.
                await ws.send(json.dumps([2, "srv-1", "Reset", {"type": "Soft"}]))
                reply = boot_reply or [3, msg_id, {"status": "Accepted", "interval": 300}]
                reply[1] = msg_id
                await ws.send(json.dumps(reply))
            elif action == "Heartbeat":
                await ws.send(json.dumps([3, msg_id, {"currentTime": "2026-01-01T00:00:00Z"}]))
    return handler


def run_against(handler, coro_factory):
    async def go():
        async with serve(handler, "127.0.0.1", 0,
                         subprotocols=["ocpp1.6", "ocpp2.0.1"]) as server:
            port = server.sockets[0].getsockname()[1]
            return await coro_factory(f"ws://127.0.0.1:{port}/ocpp")
    return asyncio.run(go())


def test_check_connection_success():
    seen = {}
    result = run_against(
        fake_csms(seen=seen),
        lambda url: check_connection(url, "CP1", password="secret", timeout=5),
    )
    assert result.subprotocol == "ocpp1.6"
    assert result.boot_notification["status"] == "Accepted"
    assert result.heartbeat["currentTime"] == "2026-01-01T00:00:00Z"
    assert result.tls_version is None
    assert seen["path"] == "/ocpp/CP1"
    assert seen["auth"] == "Basic Q1AxOnNlY3JldA=="  # CP1:secret


def test_check_connection_ocpp201():
    result = run_against(
        fake_csms(), lambda url: check_connection(url, "CP1", ocpp="2.0.1", timeout=5),
    )
    assert result.subprotocol == "ocpp2.0.1"


def test_check_connection_no_auth_header():
    seen = {}
    run_against(fake_csms(seen=seen), lambda url: check_connection(url, "CP1", timeout=5))
    assert seen["auth"] is None


def test_check_connection_call_error():
    handler = fake_csms(boot_reply=[4, None, "FormationViolation", "bad", {}])
    with pytest.raises(CallError, match="FormationViolation"):
        run_against(handler, lambda url: check_connection(url, "CP1", timeout=5))


def test_check_connection_closed():
    with pytest.raises(ConnectionClosed):
        run_against(fake_csms(close_on_boot=True),
                    lambda url: check_connection(url, "CP1", timeout=5))


def test_cli_success(capsys):
    async def cli(url):
        return await asyncio.to_thread(main, [url, "CP1", "--timeout", "5"])
    assert run_against(fake_csms(), cli) == 0
    assert capsys.readouterr().out.endswith("SUCCESS\n")


def test_cli_closed(capsys):
    async def cli(url):
        return await asyncio.to_thread(main, [url, "CP1", "--timeout", "5"])
    assert run_against(fake_csms(close_on_boot=True), cli) == 1
    assert "server closed the connection" in capsys.readouterr().out
