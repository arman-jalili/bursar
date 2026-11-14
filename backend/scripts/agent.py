#!/usr/bin/env python3
"""The proposer — a real process, so "an automation proposes" is not a claim.

What it does, and nothing else:

  read unpaid invoices  ->  POST /v1/attempts (as the agent)  ->  ask the authority to evaluate

It never approves, never signs, never dispatches. Proposing is the only verb it has, which is the
point of the demo: the proposer can suggest anything, and the engine still has the final word. It
also means this script cannot move money even if it is wrong.

Usage:

    python scripts/agent.py                 # propose every unpaid invoice
    python scripts/agent.py --dry-run       # print what it would propose
    python scripts/agent.py --once <invoice_id>

Environment (defaults match the demo stack):

    BURSAR_CONSOLE_API_URL   http://127.0.0.1:8000
    BURSAR_AUTHORITY_URL     http://127.0.0.1:8001
    BURSAR_AGENT_TOKEN       demo-agent-token
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

import httpx

CONSOLE = os.environ.get("BURSAR_CONSOLE_API_URL", "http://127.0.0.1:8000").rstrip("/")
AUTHORITY = os.environ.get("BURSAR_AUTHORITY_URL", "http://127.0.0.1:8001").rstrip("/")
TOKEN = os.environ.get("BURSAR_AGENT_TOKEN", "demo-agent-token")

#: The agent's credential, not the owner's. It can propose; it cannot approve.
HEADERS = {"authorization": f"Bearer {TOKEN}", "content-type": "application/json"}

#: No status vocabulary here on purpose. `/v1/invoices/open` decides what is open; a proposer that
#: re-implements the rule is a second source of truth that goes stale silently (it did, once).



def call(method: str, url: str, body: dict[str, Any] | None = None) -> tuple[int, Any]:
    response = httpx.request(method, url, headers=HEADERS, json=body, timeout=30)
    try:
        parsed: Any = response.json()
    except ValueError:
        parsed = response.text
    return response.status_code, parsed


def unpaid_invoices() -> list[dict[str, Any]]:
    """Read the bills this household has not paid. One endpoint, no interpretation."""
    # `/v1/invoices/open` is scoped `billing:read`, the grant the agent token holds. The full
    # `/v1/invoices` read requires `console:read` — a proposer does not need the whole ledger.
    status, body = call("GET", f"{CONSOLE}/v1/invoices/open")
    if status >= 400:
        raise SystemExit(f"GET /v1/invoices/open -> {status}: {body}")
    items = body.get("items", body.get("invoices", body)) if isinstance(body, dict) else body
    return list(items)


def propose(invoice: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """Post one proposal, then ask the engine. The proposer never decides anything itself."""
    invoice_id = str(invoice.get("invoice_id") or invoice.get("id"))
    amount = int(invoice.get("amount_micro_usdc") or 0)
    if dry_run:
        print(f"  would propose {invoice_id} for {amount} micro-USDC")
        return {"invoice_id": invoice_id, "dry_run": True}

    status, attempt = call(
        "POST",
        f"{CONSOLE}/v1/attempts",
        {"invoice_id": invoice_id, "proposed_amount_micro_usdc": amount},
    )
    if status >= 400:
        print(f"  {invoice_id}: proposal refused {status} {json.dumps(attempt)[:160]}")
        return {"invoice_id": invoice_id, "error": status}

    attempt_id = str(attempt.get("attempt_id"))
    status, determination = call("POST", f"{AUTHORITY}/v1/attempts/{attempt_id}/evaluate")

    # A refusal is a 409 with reason codes, not a failure to parse. Reading it as an error would
    # teach the operator to retry the one thing the engine just refused.
    if status >= 400 and isinstance(determination, dict):
        details = (determination.get("error") or {}).get("details") or {}
        verdict = str(details.get("reason_codes") or "refused")
    else:
        verdict = str((determination or {}).get("verdict", "?")) if isinstance(determination, dict) else "?"

    print(f"  {invoice_id} -> attempt {attempt_id[:8]}… -> {verdict}")
    return {"invoice_id": invoice_id, "attempt_id": attempt_id, "verdict": verdict}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Propose payments for unpaid invoices.")
    parser.add_argument("--dry-run", action="store_true", help="print, do not post")
    parser.add_argument("--once", metavar="INVOICE_ID", help="propose a single invoice")
    args = parser.parse_args(argv)

    print(f"proposer → {CONSOLE} (authority {AUTHORITY}, token {TOKEN[:4]}…)")
    if args.once:
        invoices = [{"invoice_id": args.once, "amount_micro_usdc": 0}]
    else:
        invoices = unpaid_invoices()

    if not invoices:
        print("nothing to propose: every invoice already has a decision")
        return 0

    print(f"{len(invoices)} invoice(s) to propose")
    results = [propose(invoice, dry_run=args.dry_run) for invoice in invoices]

    proposed = sum(1 for r in results if "attempt_id" in r)
    refused = sum(1 for r in results if "error" in r)
    print(f"done: {proposed} proposed, {refused} refused by the API")
    print("the owner decides from here; this process cannot approve or dispatch")
    return 0


if __name__ == "__main__":
    sys.exit(main())