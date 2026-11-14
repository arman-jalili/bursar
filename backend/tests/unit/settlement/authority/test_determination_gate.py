"""G-4 — `AuthorityHttpAdapter` reads the determination live and fails closed (SC-1).

Canonical: .pi/architecture/modules/settlement.md#dependencies
Reference: docs/contracts/settlement-contract-freeze.md §2.8

`httpx.MockTransport` is the seam: the adapter's transport is injectable, so every failure mode below is
produced deterministically and nothing reaches a socket.

The rule under test is SC-1: an order may exist only from a determination that **permits dispatch**,
read now. There is no cached verdict and no default. A timeout, a non-200, a malformed body, an answer for
another intent, or a verdict outside Authority's closed set is a refusal — never an `allow`.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from src.authority.domain.ids import IntentId
from src.authority.domain.values import DeterminationVerdict
from src.settlement.domain.errors import SettlementRefusal
from src.settlement.domain.views import DeterminationView
from src.settlement.infrastructure.authority.determination_gate import AuthorityHttpAdapter
from src.shared.infrastructure.config import Settings, load_settings

INTENT_ID = IntentId("intent-rigorix-1")


def a_settings(*, timeout_seconds: float = 5.0) -> Settings:
    return load_settings(
        precondition_url="http://authority.test:8001/v1/precondition/check",
        precondition_timeout_seconds=timeout_seconds,
        household_id="hh-test",
    )


def an_adapter(handler: Callable[[httpx.Request], httpx.Response]) -> AuthorityHttpAdapter:
    return AuthorityHttpAdapter.from_settings(a_settings(), transport=httpx.MockTransport(handler))


def a_determination_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "determination_id": "det-1",
        "intent_id": str(INTENT_ID),
        "verdict": "allow",
        "reason_codes": [],
        "constitution_version": 3,
        "payee_status": "active",
    }
    body.update(overrides)
    return body


def an_intent_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "intent_id": str(INTENT_ID),
        "invoice_id": "inv-2026-0042",
        "payee_id": "payee-1",
        "payee_address": "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
        "amount_micro_usdc": 42_500_000,
        "bank_digest": "cd" * 32,
        "is_new_payee": False,
        "requires_owner_signature": True,
        "constitution_version": 3,
    }
    body.update(overrides)
    return body


class TestAllowedDetermination:
    async def test_the_live_allow_read_permits_dispatch(self) -> None:
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            assert request.headers["authorization"].startswith("Bearer ")
            return httpx.Response(200, json=a_determination_body())

        view = await an_adapter(handler).determination_for(INTENT_ID)

        assert seen == [f"/v1/intents/{INTENT_ID}/determination"]
        assert isinstance(view, DeterminationView)
        assert view.verdict is DeterminationVerdict.ALLOW
        assert view.determination_id == "det-1"
        assert view.permits_dispatch() is True

    async def test_an_escalate_without_an_approval_bit_does_not_permit_dispatch(self) -> None:
        """Fail closed: an `escalate` is a permission only once the owner's approval is granted."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=a_determination_body(verdict="escalate"))

        view = await an_adapter(handler).determination_for(INTENT_ID)

        assert view.verdict is DeterminationVerdict.ESCALATE
        assert view.approval_granted is False
        assert view.permits_dispatch() is False

    async def test_a_deny_is_read_as_a_deny_and_never_as_permission(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=a_determination_body(verdict="deny"))

        view = await an_adapter(handler).determination_for(INTENT_ID)

        assert view.verdict is DeterminationVerdict.DENY
        assert view.permits_dispatch() is False


class TestFailClosed:
    async def test_a_non_200_determination_is_a_refusal_naming_the_reason(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, json={"detail": "mandate unavailable"})

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert "HTTP 503" in str(refused.value)
        assert "mandate unavailable" in str(refused.value)
        assert refused.value.reason_code == "authority_refused"
        assert refused.value.http_status == 409

    async def test_a_timeout_is_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("read timed out", request=request)

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert refused.value.reason_code == "authority_timeout"
        assert "timed out" in str(refused.value)

    async def test_an_unreachable_authority_is_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert refused.value.reason_code == "authority_unreachable"

    async def test_an_unknown_verdict_is_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=a_determination_body(verdict="maybe"))

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert refused.value.reason_code == "authority_malformed"
        assert "maybe" in str(refused.value)

    async def test_a_non_object_body_is_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=["allow"])

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert refused.value.reason_code == "authority_malformed"

    async def test_a_verdict_for_another_intent_is_a_refusal(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=a_determination_body(intent_id="intent-other"))

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).determination_for(INTENT_ID)

        assert refused.value.reason_code == "authority_intent_mismatch"


class TestIntentFacts:
    async def test_the_intent_is_read_into_the_frozen_view(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == f"/v1/intents/{INTENT_ID}"
            return httpx.Response(200, json=an_intent_body())

        view = await an_adapter(handler).intent_for(INTENT_ID)

        assert view.intent_id == INTENT_ID
        assert view.invoice_id == "inv-2026-0042"
        assert view.amount.micro_usdc == 42_500_000
        assert view.payee_address.value == "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
        assert view.bank_digest.hash == "cd" * 32
        assert view.requires_owner_signature is True
        # The nullifier scope: Mandate's household, from configuration in this single-household build.
        assert view.household_id == "hh-test"
        # The amended seed is the invoice identity; the view never invents a different hash.
        assert view.invoice_hash == "inv-2026-0042"

    async def test_a_non_200_intent_read_is_a_refusal_not_a_partial_view(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"detail": "intent not found"})

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).intent_for(INTENT_ID)

        assert refused.value.reason_code == "authority_refused"

    async def test_an_intent_without_an_amount_is_a_refusal(self) -> None:
        body = an_intent_body()
        del body["amount_micro_usdc"]

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=body)

        with pytest.raises(SettlementRefusal) as refused:
            await an_adapter(handler).intent_for(INTENT_ID)

        assert refused.value.reason_code == "authority_malformed"
