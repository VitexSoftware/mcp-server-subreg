# mcp-server-subreg

![mcp-server-subreg](mcp-server-subreg.svg)

[![M8ven Verified](https://m8ven.ai/api/agent-verify/badge?score=73)](https://m8ven.ai/verified/verify?id=2004833ab8634413)

MCP server exposing the [Subreg.cz](https://subreg.cz) domain registrar SOAP
API — via the [`subreg-client`](https://github.com/Spoje-NET/python3-subreg-client)
library — as tools for LLM agents built with [FastMCP](https://gofastmcp.com).

## Configuration

Credentials are read from the environment only, never accepted as tool
parameters. Copy the template and fill in real values:

```sh
cp .env.example .env
# edit .env — never commit .env
```

| Variable | Required | Description |
|---|---|---|
| `SUBREG_LOCATION` | yes | SOAP endpoint, e.g. `https://soap.subreg.cz/cmd.php` |
| `SUBREG_URI` | yes | SOAP namespace URI, e.g. `https://soap.subreg.cz/soap` |
| `SUBREG_LOGIN` | yes | Subreg account login |
| `SUBREG_PASSWORD` | yes | Subreg account password |
| `SUBREG_READONLY` | no | `true` (default) blocks mutating tools; set to `false` to allow domain/DNS/contact/billing writes |

Use `https://ote-soap.subreg.cz/...` endpoints for Subreg's OTE sandbox
environment while testing writes. Prefer OTE (or a disposable account) for
any `SUBREG_READONLY=false` session — never mutate production domains from
an agent.

## Tools

Read-only: `check_domain`, `info_domain`, `domains_list`, `pricelist`,
`get_pricelist`, `get_credit`, `users_list`, `info_user`, `get_dns_zone`,
`info_contact`, `contacts_list`, `info_order`, `get_tld_info`.

Mutating (require `SUBREG_READONLY=false`): `register_domain`,
`renew_domain`, `delete_domain`, `add_dns_record`, `delete_dns_record`,
`create_contact`, `update_contact`, `credit_correction`.

`info_user` requires a numeric sub-user id (discover via `users_list`).
Subreg's `Info_User` rejects an empty payload.

## Usage

```sh
pip install -e .
export SUBREG_LOCATION=https://soap.subreg.cz/cmd.php
export SUBREG_URI=https://soap.subreg.cz/soap
export SUBREG_LOGIN=...
export SUBREG_PASSWORD=...
export SUBREG_READONLY=true
mcp-server-subreg
```

## Development

```sh
pytest
```

### Live capability scenario

Exercises every read tool against a real Subreg SOAP account and verifies
that mutating tools refuse under `SUBREG_READONLY=true`:

```sh
export SUBREG_LOCATION=https://soap.subreg.cz/cmd.php
export SUBREG_URI=https://soap.subreg.cz/soap
export SUBREG_LOGIN=...
export SUBREG_PASSWORD=...
export SUBREG_READONLY=true
python tests/live_capability_scenario.py --json-out /tmp/subreg-live.json
```

`--allow-writes` is refused against production `soap.subreg.cz` (use OTE).
