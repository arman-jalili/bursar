"""Seed the real demo world through the public APIs.

Run against a fresh stack (``docker compose down -v`` first if you need a clean ledger):

    SEED_CONSOLE_URL=http://127.0.0.1:8000 SEED_AUTHORITY_URL=http://127.0.0.1:8001 \
        python scripts/seed_demo.py

Everything here goes through the same endpoints the product uses: register a payee, pre-approve
it (owner reapplication), record an invoice, propose an attempt, and let Authority decide. The
scenes are real determinations, not fixtures:

    normal     Wien Energie, eligible, inside the cap        -> allow (then dispatched)
    scam       Apotheke's presented digest does not match     -> quarantined -> deny
    split      the Control Room sandbox (kept local on purpose)
    new payee  Zahnarzt, new + above the line                 -> escalate (owner signs in the UI)
    freeze     Hausmeister frozen after an allowance          -> deny on the next evaluation
"""

from __future__ import annotations

import json
import os
import sys

import httpx

CONSOLE = os.environ.get("SEED_CONSOLE_URL", "http://127.0.0.1:8000")
AUTHORITY = os.environ.get("SEED_AUTHORITY_URL", "http://127.0.0.1:8001")
OWNER = {"Authorization": "Bearer demo-owner-token"}
AGENT = {"Authorization": "Bearer demo-agent-token"}
OWNER_ADDRESS = os.environ.get(
    "BURSAR_OWNER_ADDRESS", "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
)

# Anvil accounts 2..6: distinct payee addresses.
ADDRESSES = {
    "wien": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
    "apotheke": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
    "zahnarzt": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
    "hausmeister": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
}


def call(method: str, url: str, headers: dict[str, str], body: object | None = None) -> object:
    response = httpx.request(method, url, headers=headers, json=body, timeout=30)
    if response.status_code >= 400:
        raise SystemExit(f"{method} {url} -> {response.status_code}: {response.text[:400]}")
    return response.json()


def create_household() -> str:
    body = call(
        "POST",
        f"{CONSOLE}/v1/households",
        {**OWNER, "content-type": "application/json"},
        {
            "owner_address": OWNER_ADDRESS,
            "owner_name": "Mira Weiss",
            "payer_name": "Herr Weiss",
            "agent_key_id": "key-1",
            "cap_micro_usdc": 500_000_000,
            "threshold_micro_usdc": 100_000_000,
            "owner_proof": "signed:mandate",
        },
    )
    return str(body["household_id"])


def register(
    household_id: str, key: str, name: str, routing: str, *, preapprove: bool
) -> tuple[str, str]:
    body = call(
        "POST",
        f"{CONSOLE}/v1/households/{household_id}/payees",
        {**OWNER, "content-type": "application/json"},
        {
            "name": name,
            "address": ADDRESSES[key],
            "routing_scheme": "sepa",
            "routing_account_number": routing,
            "owner_proof": "signed:payee",
        },
    )
    payee_id = str(body["payee_id"])
    digest = str(body["verified_digest"])
    if preapprove:
        call(
            "POST",
            f"{CONSOLE}/v1/payees/{payee_id}/reapprove",
            {**OWNER, "content-type": "application/json"},
            {
                "routing_scheme": "sepa",
                "routing_account_number": routing,
                "owner_proof": "signed:preapprove",
            },
        )
    return payee_id, digest


def record_invoice(payee_id: str, amount: int, number: str, digest: str) -> str:
    body = call(
        "POST",
        f"{CONSOLE}/v1/invoices",
        {**OWNER, "content-type": "application/json"},
        {
            "payee_id": payee_id,
            "amount_micro_usdc": amount,
            "due_date": "2026-11-14",
            "document": {"kind": "invoice", "number": number},
            "presented_digest": digest,
        },
    )
    return str(body["invoice"]["invoice_id"])


def propose_and_evaluate(invoice_id: str, amount: int) -> tuple[str, dict]:
    attempt = call(
        "POST",
        f"{CONSOLE}/v1/attempts",
        {**AGENT, "content-type": "application/json"},
        {"invoice_id": invoice_id, "proposed_amount_micro_usdc": amount},
    )
    attempt_id = str(attempt["attempt_id"])
    response = httpx.post(
        f"{AUTHORITY}/v1/attempts/{attempt_id}/evaluate",
        headers=AGENT,
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if response.status_code >= 500:
        raise SystemExit(f"evaluate {attempt_id} -> {response.status_code}: {body}")
    return attempt_id, body


def dispatch(intent_id: str) -> None:
    response = httpx.post(
        f"{CONSOLE}/v1/intents/{intent_id}/dispatch",
        headers=OWNER,
        timeout=90,
    )
    label = "dispatched" if response.status_code < 400 else f"dispatch {response.status_code}"
    print(f"  normal bill: {label} {response.text[:200]}")


def main() -> int:
    print("household")
    household = create_household()

    print("payees")
    wien, wien_digest = register(
        household, "wien", "Wien Energie", "AT611904300234573201", preapprove=True
    )
    apo, apo_digest = register(
        household, "apotheke", "Apotheke Heiligen Geist", "AT483200000012345864", preapprove=True
    )
    zahn, zahn_digest = register(
        household, "zahnarzt", "Zahnarzt Dr. Keller", "AT201100000123456789", preapprove=False
    )
    haus, haus_digest = register(
        household, "hausmeister", "Hausmeister service", "AT923200000098765432", preapprove=True
    )

    print("scene: normal bill")
    inv = record_invoice(wien, 84_200_000, "INV-0304", wien_digest)
    _, verdict = propose_and_evaluate(inv, 84_200_000)
    print(f"  {verdict.get('verdict')} {verdict.get('reason_codes', '')}")
    if (
        os.environ.get("SEED_DISPATCH", "1") == "1"
        and verdict.get("intent_id")
        and verdict.get("verdict") == "allow"
    ):
        dispatch(str(verdict["intent_id"]))

    print("scene: scam invoice (digest mismatch qu")
    call(
        "POST",
        f"{CONSOLE}/v1/payees/{apo}/presented-digest",
        {**AGENT, "content-type": "application/json"},
        {"presented_digest": "0" * 64, "invoice_id": "INV-0998"},
    )
    inv = record_invoice(apo, 48_500_000, "INV-0998", apo_digest)
    _, verdict = propose_and_evaluate(inv, 48_500_000)
    print(f"  {verdict.get('verdict')} {verdict.get('reason_codes', '')}")

    print("scene: new payee above the line")
    inv = record_invoice(zahn, 240_000_000, "INV-0311", zahn_digest)
    _, verdict = propose_and_evaluate(inv, 240_000_000)
    print(f"  {verdict.get('verdict')} {verdict.get('reason_codes', '')}")

    print("scene: freeze at the next decision")
    inv = record_invoice(haus, 60_000_000, "INV-0412", haus_digest)
    propose_and_evaluate(inv, 60_000_000)
    call("POST", f"{CONSOLE}/v1/payees/{haus}/freeze", OWNER)
    inv = record_invoice(haus, 60_000_000, "INV-0413", haus_digest)
    _, verdict = propose_and_evaluate(inv, 60_000_000)
    print(f"  {verdict.get('verdict')} {verdict.get('reason_codes', '')}")

    print("seeded", json.dumps({"household": household, "wien": wien, "zahnarzt": zahn}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
