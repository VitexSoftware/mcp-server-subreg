"""MCP server exposing the Subreg.cz domain registrar SOAP API as tools.

Credentials are read once from the environment at startup
(``SUBREG_LOCATION``, ``SUBREG_URI``, ``SUBREG_LOGIN``, ``SUBREG_PASSWORD``)
and never exposed as tool parameters, so an LLM driving this server can act
on a Subreg account without ever seeing or choosing the login credentials.

By default the server runs read-only: tools that register, renew, delete,
or otherwise mutate domains, DNS records, contacts, or account credit raise
a clear error unless ``SUBREG_READONLY=false`` is set in the environment.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

from fastmcp import FastMCP
from subreg import Commands, Orders, SubregError

mcp = FastMCP("Subreg")


class _SubregClient(Commands, Orders):
    """Combined client exposing both raw commands and order wrappers.

    ``Commands`` and ``Orders`` both subclass ``subreg.Client`` independently;
    this merges them into one client so a single instance can call either
    surface. Where both define the same method name (e.g. ``renew_domain``,
    ``check_domain``), ``Commands``'/``Orders``' uniform ``params: dict``
    signature wins over ``Client``'s typed convenience methods, per MRO.
    """


def _readonly() -> bool:
    return os.environ.get("SUBREG_READONLY", "true") not in ("0", "false", "False", "")


def _require_writable() -> None:
    if _readonly():
        raise RuntimeError(
            "This server is running in read-only mode (SUBREG_READONLY=true). "
            "Set SUBREG_READONLY=false to enable domain/DNS/contact/billing mutations."
        )


@lru_cache(maxsize=1)
def _get_client() -> _SubregClient:
    """Create (once) and return the logged-in Subreg session for this process."""
    location = os.environ.get("SUBREG_LOCATION")
    uri = os.environ.get("SUBREG_URI")
    login = os.environ.get("SUBREG_LOGIN")
    password = os.environ.get("SUBREG_PASSWORD")
    if not location or not uri or not login or not password:
        raise RuntimeError(
            "SUBREG_LOCATION, SUBREG_URI, SUBREG_LOGIN and SUBREG_PASSWORD "
            "environment variables are required."
        )
    return _SubregClient(
        {
            "location": location,
            "uri": uri,
            "login": login,
            "password": password,
            "autologin": True,
        }
    )


def _call(fn, *args: Any, **kwargs: Any) -> Any:
    try:
        return fn(*args, **kwargs)
    except SubregError as exc:
        raise RuntimeError(str(exc)) from exc


# --------------------------------------------------------------------------
# Read-only tools
# --------------------------------------------------------------------------


@mcp.tool
def check_domain(domain: str) -> Any:
    """Check whether a domain is available for registration."""
    return _call(_get_client().check_domain, {"domain": domain})


@mcp.tool
def info_domain(domain: str) -> Any:
    """Fetch registration details (status, expiration, nameservers, ...) for a domain."""
    return _call(_get_client().info_domain, {"domain": domain})


@mcp.tool
def domains_list() -> Any:
    """List all domains held under the authenticated Subreg account."""
    return _call(_get_client().domains_list)


@mcp.tool
def pricelist() -> Any:
    """Fetch the full TLD pricelist for the authenticated account."""
    return _call(_get_client().pricelist)


@mcp.tool
def get_pricelist(pricelist: str) -> Any:
    """Fetch a named/specific pricelist (e.g. a reseller pricelist)."""
    return _call(_get_client().get_pricelist, {"pricelist": pricelist})


@mcp.tool
def get_credit() -> Any:
    """Fetch the current account credit balance."""
    return _call(_get_client().get_credit, {})


@mcp.tool
def info_user(user_id: int | None = None) -> Any:
    """Fetch info about the authenticated user, or a specific sub-user by id."""
    params = {"id": user_id} if user_id is not None else {}
    return _call(_get_client().info_user, params)


@mcp.tool
def get_dns_zone(domain: str) -> Any:
    """Fetch DNS zone records for a domain hosted on Subreg DNS."""
    return _call(_get_client().get_dns_zone, {"domain": domain})


@mcp.tool
def info_contact(contact_id: str) -> Any:
    """Fetch details for a contact object by its Subreg contact id."""
    return _call(_get_client().info_contact, {"id": contact_id})


@mcp.tool
def contacts_list() -> Any:
    """List contact objects registered under the authenticated account."""
    return _call(_get_client().contacts_list, {})


@mcp.tool
def info_order(order_id: str) -> Any:
    """Fetch the status and details of a previously submitted order."""
    return _call(_get_client().info_order, {"id": order_id})


@mcp.tool
def get_tld_info(tld: str) -> Any:
    """Fetch registration rules (min/max period, required fields, ...) for a TLD."""
    return _call(_get_client().get_tld_info, {"tld": tld})


# --------------------------------------------------------------------------
# Mutating tools (require SUBREG_READONLY=false)
# --------------------------------------------------------------------------


@mcp.tool
def register_domain(
    domain: str,
    registrant_id: str,
    contacts_admin_id: str,
    contacts_tech_id: str,
    auth_id: str,
    ns_hosts: list[str] | None = None,
    nsset: str | None = None,
    period: int = 1,
) -> Any:
    """Register (order) a new domain. Requires SUBREG_READONLY=false.

    registrant_id/contacts_admin_id/contacts_tech_id/auth_id are Subreg
    contact object ids (see info_contact/contacts_list). period is in years.
    """
    _require_writable()
    return _call(
        _get_client().register_domain,
        domain,
        registrant_id,
        contacts_admin_id,
        contacts_tech_id,
        auth_id,
        ns_hosts=ns_hosts,
        nsset=nsset,
        period=period,
    )


@mcp.tool
def renew_domain(domain: str, years: int = 1) -> Any:
    """Renew an existing domain for the given number of years. Requires SUBREG_READONLY=false."""
    _require_writable()
    return _call(_get_client().renew_domain, {"domain": domain, "params": {"period": years}})


@mcp.tool
def delete_domain(domain: str) -> Any:
    """Delete (cancel) a domain registration. Requires SUBREG_READONLY=false."""
    _require_writable()
    return _call(_get_client().delete_domain, {"domain": domain})


@mcp.tool
def add_dns_record(
    domain: str,
    name: str,
    type: str,
    content: str,
    ttl: int | None = None,
    prio: int | None = None,
) -> Any:
    """Add a DNS record to a zone hosted on Subreg DNS. Requires SUBREG_READONLY=false."""
    _require_writable()
    params: dict[str, Any] = {"domain": domain, "name": name, "type": type, "content": content}
    if ttl is not None:
        params["ttl"] = ttl
    if prio is not None:
        params["prio"] = prio
    return _call(_get_client().add_dns_record, params)


@mcp.tool
def delete_dns_record(domain: str, record_id: str) -> Any:
    """Delete a DNS record from a zone by its record id. Requires SUBREG_READONLY=false."""
    _require_writable()
    return _call(_get_client().delete_dns_record, {"domain": domain, "id": record_id})


@mcp.tool
def create_contact(params: dict[str, Any]) -> Any:
    """Create a new contact object. Requires SUBREG_READONLY=false.

    params follows the Subreg Create_Contact schema (name, email, address,
    phone, etc.) — see https://subreg.cz/manual/?cmd=Create_Contact.
    """
    _require_writable()
    return _call(_get_client().create_contact, params)


@mcp.tool
def update_contact(contact_id: str, params: dict[str, Any]) -> Any:
    """Update an existing contact object. Requires SUBREG_READONLY=false.

    params follows the Subreg Update_Contact schema — see
    https://subreg.cz/manual/?cmd=Update_Contact.
    """
    _require_writable()
    return _call(_get_client().update_contact, {"id": contact_id, **params})


@mcp.tool
def credit_correction(username: str, amount: int, reason: str) -> Any:
    """Adjust a sub-user's credit balance. Requires SUBREG_READONLY=false.

    amount is added to the current balance; use a negative value to subtract.
    """
    _require_writable()
    return _call(
        _get_client().credit_correction,
        {"username": username, "amount": str(amount), "reason": reason},
    )


def main() -> None:
    import sys

    if "-h" in sys.argv[1:] or "--help" in sys.argv[1:]:
        print(__doc__)
        print("Usage: mcp-server-subreg")
        print(
            "Environment: SUBREG_LOCATION, SUBREG_URI, SUBREG_LOGIN, SUBREG_PASSWORD, "
            "SUBREG_READONLY (default: true)"
        )
        return
    mcp.run()


if __name__ == "__main__":
    main()
