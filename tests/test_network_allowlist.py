"""Prove the network-allowlist fixture actually blocks outbound connections."""

import socket

import pytest

import wrapped


def test_package_imports():
    assert wrapped.__version__


def test_outbound_connection_is_blocked():
    with pytest.raises(RuntimeError, match="Blocked outbound network call"), socket.socket() as s:
        s.connect(("93.184.216.34", 80))


def test_loopback_is_allowed():
    # Connecting to a closed local port must fail with a socket error,
    # not the allowlist RuntimeError — i.e. the guard let it through.
    with pytest.raises(OSError), socket.socket() as s:
        s.settimeout(0.2)
        s.connect(("127.0.0.1", 1))
