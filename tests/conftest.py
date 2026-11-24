"""Shared by every test: no test ever reaches the network through `requests`."""

import pytest
import requests

import app


class RealNetworkCall(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_real_network(monkeypatch):
    """Every request `requests` would send raises, unless the test runs under `responses`, which patches the same
    method after this guard and so answers it (an unmatched call fails there too). Tests reach Cloudflare through the
    in-memory fake, or `responses`, never the real API."""

    def refuse(self, request, *args, **kwargs):
        raise RealNetworkCall(f"a test tried a real {request.method} to {request.url}")

    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", refuse)


@pytest.fixture(autouse=True)
def fresh_login_brake(monkeypatch):
    """The login brake is process-wide: every test starts with no failed login behind it, whatever ran before."""
    monkeypatch.setattr(app, "_last_failure", float("-inf"))
