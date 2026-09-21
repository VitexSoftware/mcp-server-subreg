"""Structural tests that don't require a real Subreg session."""

from __future__ import annotations

import asyncio

import pytest

from mcp_server_subreg.server import check_domain, delete_domain, domains_list, mcp, renew_domain


def test_tools_are_registered() -> None:
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "check_domain",
        "info_domain",
        "domains_list",
        "pricelist",
        "get_pricelist",
        "get_credit",
        "users_list",
        "info_user",
        "get_dns_zone",
        "info_contact",
        "contacts_list",
        "info_order",
        "get_tld_info",
        "register_domain",
        "renew_domain",
        "delete_domain",
        "add_dns_record",
        "delete_dns_record",
        "create_contact",
        "update_contact",
        "credit_correction",
    }


def test_tool_call_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBREG_LOCATION", raising=False)
    monkeypatch.delenv("SUBREG_URI", raising=False)
    monkeypatch.delenv("SUBREG_LOGIN", raising=False)
    monkeypatch.delenv("SUBREG_PASSWORD", raising=False)
    from mcp_server_subreg import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="SUBREG_LOCATION"):
        domains_list()


def test_readonly_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBREG_READONLY", raising=False)
    with pytest.raises(RuntimeError, match="read-only"):
        renew_domain("example.com")
    with pytest.raises(RuntimeError, match="read-only"):
        delete_domain("example.com")


def test_readonly_empty_is_fail_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBREG_READONLY", "")
    with pytest.raises(RuntimeError, match="read-only"):
        delete_domain("example.com")


def test_readonly_guard_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUBREG_READONLY", "false")
    monkeypatch.delenv("SUBREG_LOCATION", raising=False)
    monkeypatch.delenv("SUBREG_URI", raising=False)
    monkeypatch.delenv("SUBREG_LOGIN", raising=False)
    monkeypatch.delenv("SUBREG_PASSWORD", raising=False)
    from mcp_server_subreg import server

    server._get_client.cache_clear()
    # readonly guard no longer blocks; the next failure is missing credentials
    with pytest.raises(RuntimeError, match="SUBREG_LOCATION"):
        delete_domain("example.com")


def test_check_domain_requires_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUBREG_LOCATION", raising=False)
    monkeypatch.delenv("SUBREG_URI", raising=False)
    monkeypatch.delenv("SUBREG_LOGIN", raising=False)
    monkeypatch.delenv("SUBREG_PASSWORD", raising=False)
    from mcp_server_subreg import server

    server._get_client.cache_clear()
    with pytest.raises(RuntimeError, match="SUBREG_LOCATION"):
        check_domain("example.com")
