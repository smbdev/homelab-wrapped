"""Shared test fixtures.

The network-allowlist fixture below is the project's privacy promise in code:
no test — and therefore no code under test — may open a socket to anything
that isn't local. It runs automatically on the whole suite.
"""

import socket

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def no_outbound_network(monkeypatch):
    """Fail any test that attempts a non-local socket connection.

    Local connections (loopback and unix sockets) are allowed so tests can
    talk to fixture servers they start themselves. Everything else raises.
    """
    real_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, (str, bytes)) and (
            host in _LOCAL_HOSTS or (isinstance(host, str) and host.startswith("/"))
        ):
            return real_connect(self, address, *args, **kwargs)
        raise RuntimeError(
            f"Blocked outbound network call to {address!r}. "
            "Homelab Wrapped never phones home; tests must use local fixtures."
        )

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
