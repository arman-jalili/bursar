"""The chat agent + capacity-gate demo surface (`/v1/agent/*`).

This is a composition-level demo adapter, not a bounded context: it parses a sentence with an LLM
(or a local fallback), writes a real invoice, lets Authority decide, and — when the determination
allows — dispatches through the governed Rigorix step. Every number it returns is read back from
the live ledger after the operation.

The page it powers is deliberately about **one** capability: capacity. The model is therefore
small: a household, four payees, a daily cap, and a ledger.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, select

from src.authority.infrastructure.models import (
    ApprovalRow,
    CapLedgerRow,
    ReservationRow,
)
from src.console.interfaces.deps import require_scope
from src.mandate.infrastructure.models import (
    ConstitutionVersionRow,
    HouseholdRow,
    PayeeRow,
)
from src.settlement.infrastructure.models import SettlementOrderRow
from src.shared.domain.errors import ErrorCode, RefusalError

__all__ = ["router"]

router = APIRouter(prefix="/v1/agent", tags=["agent"])

SELF = os.environ.get("AGENT_CONSOLE_URL", "http://127.0.0.1:8000")
AUTHORITY = os.environ.get("BURSAR_CONSOLE_AUTHORITY_URL", "http://127.0.0.1:8001")
OWNER_TOKEN = "demo-owner-token"
AGENT_TOKEN = "demo-agent-token"
OWNER_ADDRESS = os.environ.get(
    "BURSAR_OWNER_ADDRESS", "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
)

#: The four payees the chat understands. Keys are what the model returns; matching is by name.
PAYEES: tuple[dict[str, str], ...] = (
    {
        "key": "energy",
        "name": "Wien Energie",
        "address": "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
        "routing": "AT611904300234573201",
        "hint": "the electricity bill",
    },
    {
        "key": "dentist",
        "name": "Zahnarzt Dr. Keller",
        "address": "0x15d34AAf54267DB7D7c367839AAf71A00a2C6A65",
        "routing": "AT201100000123456789",
        "hint": "the dentist",
    },
    {
        "key": "pharmacy",
        "name": "Apotheke Heiligen Geist",
        "address": "0x90F79bf6EB2c4f870365E785982E1f101E93b906",
        "routing": "AT483200000012345864",
        "hint": "the pharmacy / prescriptions",
    },
    {
        "key": "handyman",
        "name": "Hausmeister service",
        "address": "0x9965507D1a55bcC2695C58ba16FB37d819B0A4dc",
        "routing": "AT923200000098765432",
        "hint": "the handyman",
    },
)

DEFAULT_CAP_USDC = 30
DEFAULT_THRESHOLD_USDC = 30


class RunRequest(BaseModel):
    message: str


class WorldRequest(BaseModel):
    cap: float
    #: When set, payments above this still fit the cap but need the owner's signature. The
    #: precondition demo uses it so an approval exists before the dispatch-time check runs.
    threshold: float | None = None


class AuthorityRequest(BaseModel):
    payee: str
    status: str


class ApproveRequest(BaseModel):
    intent_id: str
    signature_hex: str


class ReleaseRequest(BaseModel):
    intent_id: str


def _micro(amount: float) -> int:
    return int(round(amount * 1_000_000))


def _usdc(micro: int | None) -> str:
    return f"{(micro or 0) / 1_000_000:.2f}"


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "content-type": "application/json"}


async def _post(url: str, token: str, body: object | None = None) -> tuple[int, dict[str, Any]]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(url, headers=_headers(token), json=body)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    return response.status_code, payload if isinstance(payload, dict) else {"raw": payload}


async def _get(url: str, token: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        response.raise_for_status()
        body = response.json()
    return body if isinstance(body, dict) else {"items": body}


def _session(request: Request):
    return request.app.state.session_factory


async def _ledger(session) -> dict[str, int]:
    today = datetime.now(UTC).date().isoformat()
    row = await session.get(CapLedgerRow, today)
    in_force = await session.scalar(
        select(ConstitutionVersionRow)
        .where(ConstitutionVersionRow.status == "in_force")
        .order_by(ConstitutionVersionRow.number.desc())
        .limit(1)
    )
    cap = row.cap_micro_usdc if row else (in_force.cap_micro_usdc if in_force else 0)
    committed = row.committed_micro_usdc if row else 0
    reserved = row.reserved_micro_usdc if row else 0
    return {
        "cap": cap,
        "committed": committed,
        "reserved": reserved,
        "headroom": max(0, cap - committed - reserved),
    }


async def _household(session) -> HouseholdRow | None:
    return await session.scalar(select(HouseholdRow).limit(1))


async def _bootstrap(request: Request) -> HouseholdRow:
    """Create the demo household/payees if they do not exist, and make the payees eligible.

    An operator pre-approval, not a payment: the chat is about capacity, so the new-payee signature
    rule would otherwise intercept every first payment. The direct status update is a demo control
    and is named as such.
    """
    factory = _session(request)
    async with factory() as session:
        household = await _household(session)
    if household is None:
        await _post(
            f"{SELF}/v1/households",
            OWNER_TOKEN,
            {
                "owner_address": OWNER_ADDRESS,
                "owner_name": "Mira Weiss",
                "payer_name": "Herr Weiss",
                "agent_key_id": "key-1",
                "cap_micro_usdc": _micro(DEFAULT_CAP_USDC),
                "threshold_micro_usdc": _micro(DEFAULT_THRESHOLD_USDC),
                "require_signature_for_new_payee": False,
                "owner_proof": "signed:world",
            },
        )
        async with factory() as session:
            household = await _household(session)
    assert household is not None

    async with factory() as session:
        existing = {
            row.name: row for row in (await session.scalars(select(PayeeRow))).all()
        }
    for spec in PAYEES:
        if spec["name"] in existing:
            continue
        await _post(
            f"{SELF}/v1/households/{household.id}/payees",
            OWNER_TOKEN,
            {
                "name": spec["name"],
                "address": spec["address"],
                "routing_scheme": "sepa",
                "routing_account_number": spec["routing"],
                "owner_proof": "signed:world",
            },
        )
    # Operator pre-approval: eligible means "known payee", so capacity is the only gate.
    from sqlalchemy import update

    async with factory() as session:
        await session.execute(update(PayeeRow).values(status="eligible"))
        await session.commit()
    return household


async def _map_payees(session) -> dict[str, PayeeRow]:
    rows = (await session.scalars(select(PayeeRow))).all()
    by_name = {row.name: row for row in rows}
    return by_name


async def _parse(message: str, payees: list[str]) -> tuple[dict[str, Any], str]:
    """Return {payee_name, amount} and the parser that produced it."""
    local = _local_parse(message, payees)
    key = os.environ.get("LLM_API_KEY", "")
    if key:
        try:
            parsed = await _llm_parse(message, payees, key)
            # A number in the sentence is unambiguous; never let the model change it.
            if local.get("amount") is not None:
                parsed["amount"] = local["amount"]
            return parsed, "llm"
        except Exception:
            pass
    return local, "local"


async def _llm_parse(message: str, payees: list[str], key: str) -> dict[str, Any]:
    base = os.environ.get("LLM_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
    primary = os.environ.get("LLM_MODEL", "google/gemma-4-26b-a4b-it:free")
    # A free model can be rate-limited upstream at any moment; the fallback keeps the demo live
    # without changing what the primary is.
    fallback = os.environ.get("LLM_FALLBACK_MODEL", "inclusionai/ling-3.2-flash:free")
    models = list(dict.fromkeys([primary, fallback])) if fallback else [primary]
    prompt = (
        "You turn one household payment sentence into JSON. Available payees: "
        + "; ".join(payees)
        + ". Reply with ONLY JSON: {\"payee\": <one of the payee names, or null>, "
        "\"amount\": <number in whole USDC, or null>}. Never invent a payee."
    )
    last_error: Exception | None = None
    async with httpx.AsyncClient(timeout=30) as client:
        for model in models:
            try:
                response = await client.post(
                    f"{base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {key}",
                        "content-type": "application/json",
                        "HTTP-Referer": "http://localhost:5173",
                        "X-Title": "Bursar",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "system", "content": prompt},
                            {"role": "user", "content": message},
                        ],
                        "temperature": 0,
                    },
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                # Free routed models vary: some wrap JSON in a fence or add a sentence around it.
                text = str(content).strip()
                match = re.search(r"\{.*\}", text, re.DOTALL)
                parsed = json.loads(match.group(0) if match else text)
                return {
                    "payee": parsed.get("payee"),
                    "amount": parsed.get("amount"),
                }
            except Exception as exc:  # noqa: BLE001 - try the next model, surface only if all fail
                last_error = exc
    assert last_error is not None
    raise last_error


def _local_parse(message: str, payees: list[str]) -> dict[str, Any]:
    text = message.lower()
    amount: float | None = None
    match = re.search(r"(?:€|usdc|\$)?\s*(\d+(?:[.,]\d{1,2})?)\s*(?:€|usdc|euro|eur)?", text)
    if match:
        amount = float(match.group(1).replace(",", "."))
    keywords = {
        "energy": ("energy", "electric", "wien", "strom"),
        "dentist": ("dentist", "zahn", "tooth"),
        "pharmacy": ("pharmacy", "apotheke", "prescription", "medicine"),
        "handyman": ("handyman", "hausmeister", "repair"),
    }
    chosen: str | None = None
    for spec in PAYEES:
        if any(word in text for word in keywords[spec["key"]]):
            chosen = spec["name"]
            break
    if chosen is None:
        for name in payees:
            if name.lower().split()[0] in text:
                chosen = name
                break
    return {"payee": chosen, "amount": amount}


def _resolve_payee(parsed: dict[str, Any], rows: dict[str, PayeeRow]) -> PayeeRow | None:
    raw = parsed.get("payee")
    if isinstance(raw, str):
        lowered = raw.strip().lower()
        for name, row in rows.items():
            if lowered == name.lower() or lowered in name.lower():
                return row
        for spec in PAYEES:
            if lowered == spec["key"] or lowered in spec["name"].lower():
                return rows.get(spec["name"])
    return None


def _trace(
    *,
    message: str,
    parsed: dict[str, Any],
    source: str,
    payee: PayeeRow | None,
    amount: float | None,
    before: dict[str, int],
    after: dict[str, int],
    verdict: str,
    reason_codes: list[str],
    steps: list[dict[str, Any]],
    determination_id: str = "",
    intent_id: str = "",
    order_id: str = "",
    execution_id: str = "",
    audit_uri: str = "",
    tx_hash: str | None = None,
    status: str = "",
    reply: str = "",
    approval: dict[str, Any] | None = None,
    findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "reply": reply,
        "parse": {
            "message": message,
            "payee": payee.name if payee else parsed.get("payee"),
            "amount": _usdc(_micro(amount)) if amount is not None else None,
            "source": source,
        },
        "gate": {
            "verdict": verdict,
            "reason_codes": reason_codes,
            "capacity": {
                "before": {k: _usdc(v) for k, v in before.items()},
                "after": {k: _usdc(v) for k, v in after.items()},
            },
            "steps": steps,
            "determination_id": determination_id,
            "intent_id": intent_id,
            "order_id": order_id,
            "execution_id": execution_id,
            "audit_uri": audit_uri,
            "tx_hash": tx_hash,
            "status": status,
            "approval": approval,
            "findings": findings or [],
        },
    }


async def _state(request: Request) -> dict[str, Any]:
    household = await _bootstrap(request)
    factory = _session(request)
    async with factory() as session:
        ledger = await _ledger(session)
        rows = await _map_payees(session)
        in_force = await session.scalar(
            select(ConstitutionVersionRow)
            .where(ConstitutionVersionRow.status == "in_force")
            .order_by(ConstitutionVersionRow.number.desc())
            .limit(1)
        )
    return {
        "household": household.id,
        "capacity": {k: _usdc(v) for k, v in ledger.items()},
        "threshold": _usdc(in_force.threshold_micro_usdc if in_force else 0),
        "payees": [
            {"id": row.id, "name": row.name, "status": row.status} for row in rows.values()
        ],
        "llm": {
            "ready": bool(os.environ.get("LLM_API_KEY")),
            "model": os.environ.get("LLM_MODEL", "google/gemma-4-26b-a4b-it:free"),
        },
    }


@router.get("/state", dependencies=[Depends(require_scope("console:read"))])
async def state(request: Request) -> dict[str, Any]:
    return await _state(request)


@router.post("/world", dependencies=[Depends(require_scope("console:read"))])
async def world(body: WorldRequest, request: Request) -> dict[str, Any]:
    """Set the cap and clear today's ledger — the reproducible world for the capacity example."""
    household = await _bootstrap(request)
    cap = max(1.0, min(10_000.0, float(body.cap)))
    threshold = cap if body.threshold is None else max(0.0, min(cap, float(body.threshold)))
    # A real constitution version, then a clean ledger for today.
    await _post(
        f"{SELF}/v1/households/{household.id}/constitution/versions",
        OWNER_TOKEN,
        {
            "cap_micro_usdc": _micro(cap),
            "threshold_micro_usdc": _micro(threshold),
            "require_signature_for_new_payee": False,
            "owner_proof": "signed:world",
        },
    )
    today = datetime.now(UTC).date().isoformat()
    factory = _session(request)
    async with factory() as session:
        await session.execute(delete(ReservationRow).where(ReservationRow.day == today))
        await session.execute(delete(CapLedgerRow).where(CapLedgerRow.day == today))
        await session.execute(delete(ApprovalRow))
        await session.commit()
    return await _state(request)


@router.post("/run", dependencies=[Depends(require_scope("console:read"))])
async def run(body: RunRequest, request: Request) -> dict[str, Any]:
    household = await _bootstrap(request)
    factory = _session(request)
    async with factory() as session:
        rows = await _map_payees(session)
        before = await _ledger(session)
    message = body.message.strip()
    if not message:
        return _trace(
            message=message,
            parsed={"payee": None, "amount": None},
            source="local",
            payee=None,
            amount=None,
            before=before,
            after=before,
            verdict="error",
            reason_codes=[],
            steps=[],
            reply="Tell me what to pay — for example “pay the energy bill 20”.",
        )

    parsed, source = await _parse(message, list(rows))
    payee = _resolve_payee(parsed, rows)
    raw_amount = parsed.get("amount")
    try:
        amount = float(raw_amount) if raw_amount is not None else None
    except (TypeError, ValueError):
        amount = None

    steps: list[dict[str, Any]] = [
        {
            "name": "parse",
            "ok": payee is not None and amount is not None,
            "detail": f"{source}: "
            + (f"{payee.name if payee else '?'} · {_usdc(_micro(amount)) if amount else '?'}" if payee else "no payee"),
        }
    ]
    if payee is None or amount is None or amount <= 0:
        return _trace(
            message=message,
            parsed=parsed,
            source=source,
            payee=payee,
            amount=amount,
            before=before,
            after=before,
            verdict="error",
            reason_codes=[],
            steps=steps,
            reply=(
                "I could not find a payee in that. The payees here are "
                + ", ".join(row.name for row in rows.values())
                + ". Include an amount, like “pay energy 20”."
            ),
        )

    async with factory() as session:
        payee_row = await session.get(PayeeRow, payee.id)
        digest = payee_row.verified_digest if payee_row else ""
    invoice_status, invoice_body = await _post(
        f"{SELF}/v1/invoices",
        OWNER_TOKEN,
        {
            "payee_id": payee.id,
            "amount_micro_usdc": _micro(amount),
            "due_date": datetime.now(UTC).date().isoformat(),
            "document": {"kind": "chat", "say": message, "nonce": uuid.uuid4().hex},
            "presented_digest": digest,
        },
    )
    if invoice_status >= 400:
        return _trace(
            message=message, parsed=parsed, source=source, payee=payee, amount=amount,
            before=before, after=before, verdict="error", reason_codes=[], steps=steps,
            reply=f"The invoice could not be recorded: {invoice_body}",
        )
    invoice_id = invoice_body["invoice"]["invoice_id"]
    steps.append({"name": "invoice", "ok": True, "detail": invoice_id})

    _, attempt_body = await _post(
        f"{SELF}/v1/attempts",
        AGENT_TOKEN,
        {"invoice_id": invoice_id, "proposed_amount_micro_usdc": _micro(amount)},
    )
    attempt_id = attempt_body.get("attempt_id")
    if not attempt_id:
        return _trace(
            message=message, parsed=parsed, source=source, payee=payee, amount=amount,
            before=before, after=before, verdict="error", reason_codes=[], steps=steps,
            reply=f"The proposal was refused: {attempt_body}",
        )
    steps.append({"name": "propose", "ok": True, "detail": attempt_id})

    eval_status, eval_body = await _post(
        f"{AUTHORITY}/v1/attempts/{attempt_id}/evaluate", AGENT_TOKEN
    )
    async with factory() as session:
        after = await _ledger(session)

    if eval_status >= 500:
        return _trace(
            message=message, parsed=parsed, source=source, payee=payee, amount=amount,
            before=before, after=after, verdict="error", reason_codes=[], steps=steps,
            reply=f"Authority could not decide: {eval_body}",
        )

    verdict = str(eval_body.get("verdict", "deny"))
    details = (eval_body.get("error") or {}).get("details", {}) if eval_body.get("error") else {}
    reason_codes = [
        code
        for code in str(details.get("reason_codes") or ",".join(eval_body.get("reason_codes") or [])).split(",")
        if code
    ]
    determination_id = str(details.get("determination_id") or eval_body.get("determination_id") or "")
    intent_id = str(details.get("intent_id") or eval_body.get("intent_id") or "")

    if verdict == "deny" or eval_status == 409:
        steps.append(
            {
                "name": "capacity",
                "ok": False,
                "detail": f"{', '.join(reason_codes) or 'refused'} — {_usdc(before['headroom'])} free before",
            }
        )
        steps.append({"name": "rigorix", "ok": False, "detail": "not asked to run"})
        reason = reason_codes[0] if reason_codes else "refused"
        return _trace(
            message=message, parsed=parsed, source=source, payee=payee, amount=amount,
            before=before, after=after, verdict="deny", reason_codes=reason_codes,
            steps=steps, determination_id=determination_id, intent_id=intent_id,
            reply=f"Refused. {reason}. Nothing ran and nothing moved.",
        )

    if verdict == "escalate":
        steps.append(
            {"name": "capacity", "ok": True, "detail": "inside the cap; the owner's signature is required"}
        )
        steps.append({"name": "rigorix", "ok": False, "detail": "waiting for the owner"})
        approval: dict[str, Any] | None = None
        async with factory() as session:
            row = await session.scalar(
                select(ApprovalRow)
                .where(ApprovalRow.intent_id == intent_id, ApprovalRow.consumed_at.is_(None))
                .order_by(ApprovalRow.expires_at.desc())
                .limit(1)
            )
        if row is not None:
            approval = {
                "approval_id": row.id,
                "typed_data_hash": row.typed_data_hash,
                "expires_at": row.expires_at.isoformat(),
            }
        return _trace(
            message=message, parsed=parsed, source=source, payee=payee, amount=amount,
            before=before, after=after, verdict="escalate", reason_codes=reason_codes,
            steps=steps, determination_id=determination_id, intent_id=intent_id,
            approval=approval,
            reply="This one needs your signature before it can move. No money left the account.",
        )

    steps.append(
        {"name": "capacity", "ok": True, "detail": f"{_usdc(_micro(amount))} ≤ {_usdc(before['headroom'])} free"}
    )
    dispatch_status, dispatch_body = await _post(
        f"{SELF}/v1/intents/{intent_id}/dispatch", OWNER_TOKEN
    )
    dispatched = dispatch_status < 400
    error = dispatch_body.get("error") if isinstance(dispatch_body.get("error"), dict) else {}
    error_details = (error or {}).get("details") or {}
    steps.append(
        {
            "name": "rigorix",
            "ok": dispatched,
            "detail": (
                f"governed step {dispatch_body.get('status')}" if dispatched
                else f"refused: {(error or {}).get('message', 'unknown')}"
            ),
        }
    )
    tx_hash = dispatch_body.get("tx_hash") if dispatched else None
    execution_id = str(
        dispatch_body.get("execution_id") or (error_details or {}).get("execution_id") or ""
    )
    audit_uri = str(dispatch_body.get("audit_uri") or (error_details or {}).get("audit_uri") or "")
    order_id = str(dispatch_body.get("order_id") or "")
    release_status = str(dispatch_body.get("status") or "")
    findings: list[dict[str, Any]] = []
    if not dispatched and execution_id:
        # The governed step refused before dispatch, but it still wrote a signed envelope: the
        # precondition finding is the evidence for the refusal.
        findings = _findings(execution_id)
    if dispatched and tx_hash:
        steps.append({"name": "chain", "ok": True, "detail": str(tx_hash)})
    elif findings:
        steps.append(
            {
                "name": "chain",
                "ok": False,
                "detail": "no transaction broadcast — the precondition refused first",
            }
        )
    return _trace(
        message=message, parsed=parsed, source=source, payee=payee, amount=amount,
        before=before, after=after, verdict="allow" if dispatched else "dispatch_failed",
        reason_codes=reason_codes, steps=steps, determination_id=determination_id,
        intent_id=intent_id, order_id=order_id,
        execution_id=execution_id, audit_uri=audit_uri,
        tx_hash=tx_hash, status=release_status, findings=findings,
        reply=(
            f"Allowed. {_usdc(_micro(amount))} to {payee.name} ran through Rigorix."
            if dispatched
            else "Capacity allowed it, but the governed step did not run."
        ),
    )


def _audit_dir() -> Path:
    return Path(os.environ.get("RIGORIX_AUDIT_DIR", "/tmp/rigorix-demo/.rigorix/audit"))


def _findings(execution_id: str) -> list[dict[str, Any]]:
    """The precondition findings on one execution's signed envelope (empty when none)."""
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", execution_id):
        return []
    try:
        envelope = json.loads((_audit_dir() / f"{execution_id}.json").read_text())
    except (OSError, ValueError):
        return []
    findings = envelope.get("precondition_findings")
    return [item for item in findings if isinstance(item, dict)] if isinstance(findings, list) else []


def _authority_file() -> Path:
    # The operator's authority lives outside the repo; the console only reads/writes this demo
    # status file at the operator's request.
    return Path(os.environ.get("BURSAR_PRECONDITION_DIR", "/tmp/bursar-preconditions")) / "authority.json"


def _read_authority() -> dict[str, str]:
    try:
        data = json.loads(_authority_file().read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(key).lower(): str(value) for key, value in data.items()}


async def _authority_view() -> dict[str, Any]:
    statuses = _read_authority()
    return {
        "check": "payee-authorized",
        "authority_path": str(_authority_file()),
        "payees": [
            {
                "key": spec["key"],
                "name": spec["name"],
                "address": spec["address"],
                "status": statuses.get(spec["address"].lower(), "unknown"),
            }
            for spec in PAYEES
        ],
    }


@router.get("/authority", dependencies=[Depends(require_scope("console:read"))])
async def authority() -> dict[str, Any]:
    """The operator's dispatch-time payee authority, read from the file the check reads."""
    return await _authority_view()


@router.post("/authority", dependencies=[Depends(require_scope("console:read"))])
async def set_authority(body: AuthorityRequest) -> dict[str, Any]:
    """Freeze or reactivate a payee — the operator's action, outside the agent's reach.

    This writes the same file the precondition reads at dispatch time. It is a demo control:
    the authority being outside the repository is the point.
    """
    status = body.status.strip().lower()
    if status not in {"active", "frozen"}:
        raise HTTPException(status_code=400, detail="status must be 'active' or 'frozen'")
    wanted = body.payee.strip().lower()
    spec = next(
        (
            item
            for item in PAYEES
            if wanted in (item["key"], item["name"].lower(), item["address"].lower())
        ),
        None,
    )
    if spec is None:
        raise HTTPException(status_code=404, detail="unknown payee")
    statuses = _read_authority()
    statuses[spec["address"].lower()] = status
    path = _authority_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(sorted(statuses.items())), indent=2) + "\n")
    return await _authority_view()


@router.post("/approve", dependencies=[Depends(require_scope("console:read"))])
async def approve(body: ApproveRequest, request: Request) -> dict[str, Any]:
    """Submit the owner's signature for this intent's open request (A-13 … A-15).

    Authority verifies the signature against the bound intent and the mandate owner; the console
    only forwards it. Capacity is reserved on success — before anything is broadcast.
    """
    factory = _session(request)
    async with factory() as session:
        row = await session.scalar(
            select(ApprovalRow)
            .where(ApprovalRow.intent_id == body.intent_id)
            .order_by(ApprovalRow.expires_at.desc())
            .limit(1)
        )
    if row is None:
        raise HTTPException(status_code=404, detail="no signature request for this intent")
    status, payload = await _post(
        f"{AUTHORITY}/v1/approvals/{row.id}/signature",
        OWNER_TOKEN,
        {"signature_hex": body.signature_hex},
    )
    if status >= 400:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        raise RefusalError(
            ErrorCode.CONFLICT,
            str((error or {}).get("message") or "Authority refused the signature."),
            details={"approval_id": row.id},
        )
    async with factory() as session:
        ledger = await _ledger(session)
    return {
        "approval_id": row.id,
        "granted": bool(payload.get("granted")),
        "events": payload.get("events", []),
        "capacity": {key: _usdc(value) for key, value in ledger.items()},
    }


@router.post("/release", dependencies=[Depends(require_scope("console:read"))])
async def release(body: ReleaseRequest, request: Request) -> dict[str, Any]:
    """Dispatch the approved intent through the governed step.

    This is the moment the dispatch-time precondition runs: the approval got the payment here,
    but the operator's authority is checked again immediately before the broadcast.
    """
    factory = _session(request)
    async with factory() as session:
        before = await _ledger(session)
    status, payload = await _post(f"{SELF}/v1/intents/{body.intent_id}/dispatch", OWNER_TOKEN)
    async with factory() as session:
        after = await _ledger(session)

    dispatched = status < 400
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    details = (error or {}).get("details") or {}
    execution_id = str(payload.get("execution_id") or (details or {}).get("execution_id") or "")
    audit_uri = str(payload.get("audit_uri") or (details or {}).get("audit_uri") or "")
    order_id = str(payload.get("order_id") or "")
    tx_hash = payload.get("tx_hash") if dispatched else None
    order_status = str(payload.get("status") or "")
    findings: list[dict[str, Any]] = []
    if not dispatched:
        async with factory() as session:
            order = await session.scalar(
                select(SettlementOrderRow)
                .where(SettlementOrderRow.intent_id == body.intent_id)
                .limit(1)
            )
        if order is not None:
            order_id = order.id
            order_status = order.status
            # Signed, not broadcast: the hash exists, and the bytes were never sent.
            tx_hash = order.tx_hash
        if execution_id:
            findings = _findings(execution_id)

    steps: list[dict[str, Any]] = [
        {
            "name": "approval",
            "ok": True,
            "detail": "owner signature verified · capacity reserved",
        },
    ]
    if dispatched:
        steps.append({"name": "rigorix", "ok": True, "detail": "governed step submitted"})
        if tx_hash:
            steps.append({"name": "chain", "ok": True, "detail": str(tx_hash)})
    else:
        steps.append(
            {
                "name": "rigorix",
                "ok": False,
                "detail": f"refused: {(error or {}).get('message', 'unknown')}",
            }
        )
        steps.append(
            {
                "name": "chain",
                "ok": False,
                "detail": "no transaction broadcast — the precondition refused first",
            }
        )

    return {
        "gate": {
            "verdict": "allow" if dispatched else "refused_at_dispatch",
            "steps": steps,
            "capacity": {
                "before": {key: _usdc(value) for key, value in before.items()},
                "after": {key: _usdc(value) for key, value in after.items()},
            },
            "intent_id": body.intent_id,
            "order_id": order_id,
            "tx_hash": tx_hash,
            "execution_id": execution_id,
            "audit_uri": audit_uri,
            "status": order_status,
            "findings": findings,
        },
        "refusal": (
            None
            if dispatched
            else {
                "message": str((error or {}).get("message") or "the governed step refused"),
                "broadcast": False,
                "findings": findings,
            }
        ),
    }


@router.get("/envelope/{execution_id}", dependencies=[Depends(require_scope("console:read"))])
async def envelope(execution_id: str) -> dict[str, Any]:
    """Return the signed Rigorix audit envelope for one governed run.

    The file is the artifact Rigorix wrote under its own repository; this endpoint does not
    re-sign or reshape it. The browser verifier is what checks the HMAC.
    """
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", execution_id):
        raise HTTPException(status_code=400, detail="execution_id must be a UUID")
    path = _audit_dir() / f"{execution_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no signed envelope for this execution")
    return {"execution_id": execution_id, "envelope": json.loads(path.read_text())}


@router.get("/trail", dependencies=[Depends(require_scope("console:read"))])
async def trail() -> dict[str, Any]:
    """The chained governed executions, oldest first, with their signed envelopes.

    One producer writes one chain: every envelope carries its `sequence` and the `prev_hash` of the
    one before it. The page verifies both the HMAC and those links in the browser.
    """
    from pathlib import Path

    audit_dir = Path(os.environ.get("RIGORIX_AUDIT_DIR", "/tmp/rigorix-demo/.rigorix/audit"))
    items: list[dict[str, Any]] = []
    if audit_dir.exists():
        for path in audit_dir.glob("*.json"):
            try:
                envelope = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            if envelope.get("template_id") != "bursar-payment-dispatch":
                continue
            items.append(
                {
                    "execution_id": envelope.get("execution_id"),
                    "sequence": envelope.get("sequence"),
                    "timestamp": envelope.get("timestamp"),
                    "prev_hash": envelope.get("prev_hash"),
                    "template_id": envelope.get("template_id"),
                    "envelope": envelope,
                }
            )
    items.sort(key=lambda item: str(item.get("timestamp") or ""))
    return {"items": items[-30:]}


@router.post("/trail/clear", dependencies=[Depends(require_scope("console:read"))])
async def clear_trail() -> dict[str, int]:
    """Delete the governed-run envelopes. A demo control for starting a fresh chain."""
    from pathlib import Path

    audit_dir = Path(os.environ.get("RIGORIX_AUDIT_DIR", "/tmp/rigorix-demo/.rigorix/audit"))
    cleared = 0
    if audit_dir.exists():
        for path in audit_dir.glob("*.json"):
            try:
                envelope = json.loads(path.read_text())
            except (ValueError, OSError):
                continue
            if envelope.get("template_id") != "bursar-payment-dispatch":
                continue
            try:
                path.unlink()
                cleared += 1
            except OSError:
                continue
    return {"cleared": cleared}
