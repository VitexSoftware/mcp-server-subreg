# mcp-server-subreg

MCP server exposing the [Subreg.cz](https://subreg.cz) domain registrar SOAP
API — via the [`subreg-client`](https://github.com/Spoje-NET/python3-subreg-client)
library — as tools for LLM agents built with [FastMCP](https://gofastmcp.com).

## Configuration

Credentials are read from the environment only, never accepted as tool
parameters:

| Variable | Required | Description |
|---|---|---|
| `SUBREG_LOCATION` | yes | SOAP endpoint, e.g. `https://soap.subreg.cz/cmd.php` |
| `SUBREG_URI` | yes | SOAP namespace URI, e.g. `https://soap.subreg.cz/soap` |
| `SUBREG_LOGIN` | yes | Subreg account login |
| `SUBREG_PASSWORD` | yes | Subreg account password |
| `SUBREG_READONLY` | no | `true` (default) blocks mutating tools; set to `false` to allow domain/DNS/contact/billing writes |

Use `https://ote-soap.subreg.cz/...` endpoints for Subreg's OTE sandbox
environment while testing.

## Tools

Read-only: `check_domain`, `info_domain`, `domains_list`, `pricelist`,
`get_pricelist`, `get_credit`, `info_user`, `get_dns_zone`, `info_contact`,
`contacts_list`, `info_order`, `get_tld_info`.

Mutating (require `SUBREG_READONLY=false`): `register_domain`,
`renew_domain`, `delete_domain`, `add_dns_record`, `delete_dns_record`,
`create_contact`, `update_contact`, `credit_correction`.

## Usage

```sh
pip install -e .
export SUBREG_LOCATION=https://soap.subreg.cz/cmd.php
export SUBREG_URI=https://soap.subreg.cz/soap
export SUBREG_LOGIN=...
export SUBREG_PASSWORD=...
mcp-server-subreg
```

## Development

```sh
pytest
```
