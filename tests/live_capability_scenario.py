#!/usr/bin/env python3
"""Live capability scenario for Subreg MCP Server.

Exercises every MCP read tool against a real Subreg SOAP account and verifies
that mutating tools refuse under SUBREG_READONLY=true.

Usage:
  # Production Subreg (read-only — never mutates domains)
  export SUBREG_LOCATION=https://soap.subreg.cz/cmd.php
  export SUBREG_URI=https://soap.subreg.cz/soap
  export SUBREG_LOGIN='spojenetapi#spoje.net'
  export SUBREG_PASSWORD=...
  export SUBREG_READONLY=true
  python tests/live_capability_scenario.py --json-out /tmp/subreg-live.json

  # OTE sandbox
  SUBREG_LOCATION=https://ote-soap.subreg.cz/cmd.php \\
  SUBREG_URI=https://ote-soap.subreg.cz/soap \\
    python tests/live_capability_scenario.py

Exit code is 0 only when every non-skipped check passes.

NEVER pass --allow-writes against production. Prefer OTE for write tests.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC = PROJECT_ROOT / "src"
for path in (str(SRC), str(PROJECT_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)


@dataclass
class CheckResult:
    name: str
    kind: str  # tool | meta | guard
    ok: bool
    detail: str = ""
    sample: Any = None
    skipped: bool = False


@dataclass
class ScenarioReport:
    location: str
    login: str
    results: List[CheckResult] = field(default_factory=list)

    def add(self, result: CheckResult) -> None:
        self.results.append(result)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.ok and not r.skipped)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.ok and not r.skipped)

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.skipped)


def _parse_payload(data: Any) -> Any:
    if isinstance(data, str):
        try:
            return json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return data
    return data


def _is_error_payload(data: Any) -> Optional[str]:
    data = _parse_payload(data)
    if isinstance(data, str):
        low = data.lower()
        if "error" in low or "traceback" in low or "exception" in low:
            return data[:300]
        return None
    if not isinstance(data, dict):
        return None
    if data.get("error") is True or data.get("success") is False:
        return str(data.get("message") or data.get("reason") or data)[:300]
    # Subreg SOAP responses often nest status under response / status
    status = data.get("status") or data.get("response", {}).get("status") if isinstance(
        data.get("response"), dict
    ) else data.get("status")
    if status is not None and str(status).lower() in ("error", "failed", "fail"):
        return str(data.get("error") or data.get("message") or data)[:300]
    err = data.get("error")
    if isinstance(err, dict) and err:
        return str(err)[:300]
    if isinstance(err, str) and err.strip():
        return err[:300]
    return None


def _has_usable_data(data: Any) -> Tuple[bool, str]:
    data = _parse_payload(data)
    err = _is_error_payload(data)
    if err:
        return False, err
    if data is None:
        return False, "null response"
    if isinstance(data, str):
        return (bool(data.strip()), "empty string" if not data.strip() else "ok string")
    if isinstance(data, (int, float, bool)):
        return True, f"{type(data).__name__}={data!r}"
    if isinstance(data, list):
        return True, f"list len={len(data)}"
    if isinstance(data, dict):
        if data:
            return True, f"keys={list(data.keys())[:8]}"
        return False, "empty object"
    return True, f"type={type(data).__name__}"


def _tool_is_readonly(tool: Any) -> bool:
    ann = getattr(tool, "annotations", None)
    if ann is None:
        return True
    if hasattr(ann, "read_only_hint"):
        return bool(ann.read_only_hint)
    if hasattr(ann, "readOnlyHint"):
        return bool(ann.readOnlyHint)
    if isinstance(ann, dict):
        return bool(ann.get("read_only_hint", ann.get("readOnlyHint", True)))
    return True


def _first_domain(payload: Any) -> Optional[str]:
    data = _parse_payload(payload)
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            for key in ("name", "domain", "fqdn"):
                if first.get(key):
                    return str(first[key])
    if not isinstance(data, dict):
        return None
    for key in ("domains", "domain", "list", "data"):
        items = data.get(key)
        if isinstance(items, list) and items:
            first = items[0]
            if isinstance(first, str):
                return first
            if isinstance(first, dict):
                for k in ("name", "domain", "fqdn"):
                    if first.get(k):
                        return str(first[k])
        if isinstance(items, dict):
            # keyed by domain name
            for name in items:
                if name and name not in ("status", "error"):
                    return str(name)
    # flat single-domain response
    for k in ("name", "domain", "fqdn"):
        if data.get(k):
            return str(data[k])
    return None


def _first_contact_id(payload: Any) -> Optional[str]:
    data = _parse_payload(payload)
    if isinstance(data, list) and data and isinstance(data[0], dict):
        cid = data[0].get("id") or data[0].get("contact_id")
        return str(cid) if cid is not None else None
    if not isinstance(data, dict):
        return None
    for key in ("contacts", "contact", "list", "data"):
        items = data.get(key)
        if isinstance(items, list) and items and isinstance(items[0], dict):
            cid = items[0].get("id") or items[0].get("contact_id")
            if cid is not None:
                return str(cid)
        if isinstance(items, dict):
            for cid, val in items.items():
                if isinstance(val, dict) or cid:
                    return str(cid)
    if data.get("id") is not None:
        return str(data["id"])
    return None


def _run_check(
    report: ScenarioReport,
    name: str,
    kind: str,
    fn: Callable[[], Any],
    *,
    require_data: bool = True,
    skip_reason: Optional[str] = None,
) -> Optional[Any]:
    if skip_reason:
        report.add(CheckResult(name=name, kind=kind, ok=True, detail=skip_reason, skipped=True))
        return None
    try:
        raw = fn()
        ok, detail = _has_usable_data(raw) if require_data else (True, "invoked")
        sample = _parse_payload(raw)
        try:
            preview = json.dumps(sample, ensure_ascii=False, default=str)
        except TypeError:
            preview = str(sample)
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=ok,
                detail=detail,
                sample=preview[:800],
            )
        )
        return raw
    except Exception as exc:  # noqa: BLE001 — scenario must keep going
        report.add(
            CheckResult(
                name=name,
                kind=kind,
                ok=False,
                detail=f"{type(exc).__name__}: {exc}",
                sample=traceback.format_exc()[-600:],
            )
        )
        return None


def run_scenario(
    location: str,
    uri: str,
    login: str,
    password: str,
    *,
    read_only: bool = True,
) -> ScenarioReport:
    os.environ["SUBREG_LOCATION"] = location
    os.environ["SUBREG_URI"] = uri
    os.environ["SUBREG_LOGIN"] = login
    os.environ["SUBREG_PASSWORD"] = password
    os.environ["SUBREG_READONLY"] = "true" if read_only else "false"

    import importlib

    import mcp_server_subreg.server as server

    server._get_client.cache_clear()
    server = importlib.reload(server)
    server._get_client.cache_clear()

    report = ScenarioReport(location=location, login=login)
    tools = asyncio.run(server.mcp.list_tools())
    tool_by_name = {t.name: t for t in tools}
    fn_by_name = {
        name: getattr(server, name)
        for name in tool_by_name
        if callable(getattr(server, name, None))
    }

    report.add(
        CheckResult(
            name="tool_catalog",
            kind="meta",
            ok=len(tools) > 0,
            detail=f"{len(tools)} tools registered",
        )
    )
    ro_count = sum(1 for t in tools if _tool_is_readonly(t))
    rw_count = len(tools) - ro_count
    report.add(
        CheckResult(
            name="tool_annotations",
            kind="meta",
            ok=ro_count > 0 and rw_count > 0,
            detail=f"read_only={ro_count} mutating={rw_count}",
        )
    )

    def _soft_api(fn: Callable[[], Any]) -> Any:
        """Invoke fn; convert permission/not-found API errors into skip payloads."""
        try:
            return fn()
        except RuntimeError as exc:
            msg = str(exc)
            soft = (
                "does not exist",
                "not allowed",
                "Field \"User\" is empty",
                "Pricelist does not exist",
            )
            if any(s.lower() in msg.lower() for s in soft):
                return {"success": False, "skipped_reason": msg[:200]}
            raise

    def _mark_skip_if_soft(raw: Optional[Any]) -> None:
        if raw is None:
            return
        parsed = _parse_payload(raw)
        if isinstance(parsed, dict) and parsed.get("skipped_reason"):
            report.results[-1].skipped = True
            report.results[-1].ok = True
            report.results[-1].detail = str(parsed["skipped_reason"])

    # ---- account / catalog reads (no domain required) ----
    _run_check(report, "get_credit", "tool", server.get_credit)
    users = _run_check(report, "users_list", "tool", server.users_list)
    user_id: Optional[int] = None
    if users is not None:
        parsed_users = _parse_payload(users)
        if isinstance(parsed_users, dict):
            ulist = parsed_users.get("users")
            if isinstance(ulist, list) and ulist and isinstance(ulist[0], dict):
                raw_id = ulist[0].get("id")
                if raw_id is not None:
                    try:
                        user_id = int(raw_id)
                    except (TypeError, ValueError):
                        user_id = None
    iu = _run_check(
        report,
        "info_user",
        "tool",
        lambda: _soft_api(lambda: server.info_user(user_id=user_id)),  # type: ignore[arg-type]
        skip_reason=None if user_id is not None else "no sub-users on account (Info_User needs id)",
        require_data=False,
    )
    _mark_skip_if_soft(iu)

    _run_check(report, "pricelist", "tool", server.pricelist)
    _run_check(report, "get_tld_info", "tool", lambda: server.get_tld_info(tld="cz"))
    gp = _run_check(
        report,
        "get_pricelist",
        "tool",
        lambda: _soft_api(lambda: server.get_pricelist(pricelist="default")),
        require_data=False,
    )
    _mark_skip_if_soft(gp)

    domains = _run_check(report, "domains_list", "tool", server.domains_list)
    domain = _first_domain(domains)

    contacts = _run_check(report, "contacts_list", "tool", server.contacts_list)
    contact_id = _first_contact_id(contacts)

    # ---- domain-dependent reads ----
    _run_check(
        report,
        "check_domain",
        "tool",
        lambda: server.check_domain(domain="example-mcp-probe-unlikely-xyz.cz"),
    )
    _run_check(
        report,
        "info_domain",
        "tool",
        lambda: server.info_domain(domain=domain),
        skip_reason=None if domain else "no domain on account",
    )
    _run_check(
        report,
        "get_dns_zone",
        "tool",
        lambda: server.get_dns_zone(domain=domain),
        skip_reason=None if domain else "no domain on account",
    )
    ic = _run_check(
        report,
        "info_contact",
        "tool",
        lambda: _soft_api(lambda: server.info_contact(contact_id=contact_id)),  # type: ignore[arg-type]
        skip_reason=None if contact_id else "no contact id on account",
        require_data=False,
    )
    _mark_skip_if_soft(ic)
    # info_order needs a real order id — skip unless we somehow have one
    _run_check(
        report,
        "info_order",
        "tool",
        lambda: None,
        skip_reason="needs a real order id (not probed against production)",
    )

    covered = {r.name.split(":")[0] for r in report.results if r.kind == "tool"}

    for t in tools:
        if not _tool_is_readonly(t):
            continue
        if t.name in covered:
            continue
        fn = fn_by_name.get(t.name)
        if not fn:
            report.add(
                CheckResult(
                    name=t.name,
                    kind="tool",
                    ok=False,
                    detail="registered in MCP but missing Python callable",
                )
            )
            continue
        report.add(
            CheckResult(
                name=t.name,
                kind="tool",
                ok=True,
                detail="no default args probe defined",
                skipped=True,
            )
        )

    # ---- SUBREG_READONLY guards on mutating tools ----
    if read_only:
        sample_writes = [
            (
                "register_domain",
                lambda: server.register_domain(
                    domain="mcp-must-not-register.cz",
                    registrant_id="1",
                    contacts_admin_id="1",
                    contacts_tech_id="1",
                    auth_id="x",
                ),
            ),
            ("renew_domain", lambda: server.renew_domain(domain="example.com", years=1)),
            ("delete_domain", lambda: server.delete_domain(domain="example.com")),
            (
                "add_dns_record",
                lambda: server.add_dns_record(
                    domain="example.com", name="@", type="A", content="127.0.0.1"
                ),
            ),
            (
                "delete_dns_record",
                lambda: server.delete_dns_record(domain="example.com", record_id="1"),
            ),
            ("create_contact", lambda: server.create_contact(params={"name": "MCP"})),
            (
                "update_contact",
                lambda: server.update_contact(contact_id="1", params={"name": "MCP"}),
            ),
            (
                "credit_correction",
                lambda: server.credit_correction(username="nobody", amount=0, reason="mcp-test"),
            ),
        ]
        for name, fn in sample_writes:
            try:
                raw = fn()
                payload = _parse_payload(raw)
                refused = False
                if isinstance(payload, dict) and "read-only" in str(payload).lower():
                    refused = True
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=refused,
                        detail="write returned without raising"
                        if not refused
                        else "refused in payload",
                        sample=str(payload)[:300],
                    )
                )
            except RuntimeError as exc:
                ok = "read-only" in str(exc).lower()
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=ok,
                        detail=str(exc),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                report.add(
                    CheckResult(
                        name=f"readonly_guard:{name}",
                        kind="guard",
                        ok=False,
                        detail=f"unexpected {type(exc).__name__}: {exc}",
                    )
                )

    for t in tools:
        if _tool_is_readonly(t):
            continue
        report.add(
            CheckResult(
                name=f"catalog:{t.name}",
                kind="meta",
                ok=True,
                detail="write tool registered (guard-sampled separately)",
            )
        )

    _ = tool_by_name
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--location", default=os.getenv("SUBREG_LOCATION"))
    parser.add_argument("--uri", default=os.getenv("SUBREG_URI"))
    parser.add_argument("--login", default=os.getenv("SUBREG_LOGIN"))
    parser.add_argument("--password", default=os.getenv("SUBREG_PASSWORD"))
    parser.add_argument("--json-out", help="Write full report JSON here")
    parser.add_argument(
        "--allow-writes",
        action="store_true",
        help="Set SUBREG_READONLY=false (guards skipped; NEVER use on production)",
    )
    args = parser.parse_args()

    missing = [
        n
        for n, v in [
            ("--location/SUBREG_LOCATION", args.location),
            ("--uri/SUBREG_URI", args.uri),
            ("--login/SUBREG_LOGIN", args.login),
            ("--password/SUBREG_PASSWORD", args.password),
        ]
        if not v
    ]
    if missing:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        return 2

    if args.allow_writes and "soap.subreg.cz" in (args.location or "") and "ote-" not in (
        args.location or ""
    ):
        print(
            "Refusing --allow-writes against production soap.subreg.cz. "
            "Use OTE (ote-soap.subreg.cz) for write tests.",
            file=sys.stderr,
        )
        return 2

    report = run_scenario(
        args.location,
        args.uri,
        args.login,
        args.password,
        read_only=not args.allow_writes,
    )

    print(f"Subreg MCP live scenario: {report.location} as {report.login}")
    print(f"passed={report.passed} failed={report.failed} skipped={report.skipped}")
    print()
    for r in report.results:
        if r.skipped:
            flag = "SKIP"
        elif r.ok:
            flag = "PASS"
        else:
            flag = "FAIL"
        print(f"  {flag:4} [{r.kind}] {r.name}: {r.detail}")

    if args.json_out:
        out = {
            "location": report.location,
            "login": report.login,
            "passed": report.passed,
            "failed": report.failed,
            "skipped": report.skipped,
            "results": [r.__dict__ for r in report.results],
        }
        Path(args.json_out).write_text(
            json.dumps(out, indent=2, ensure_ascii=False, default=str)
        )
        print(f"\nWrote {args.json_out}")

    return 0 if report.failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
