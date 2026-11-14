"""Evidence end-to-end through the public HTTP API (scenario 7 surface).

Canonical: .pi/architecture/modules/evidence.md#api-endpoints
Reference: docs/contracts/evidence-contract-freeze.md §2.9

These go through the real composition root (middleware, scope checks, shared error envelope, SQLite,
Alembic migration `003_evidence`):

    E-2  sealing a delivered fact creates exactly one envelope
    E-4  the same delivery replayed is a duplicate, not a second proof
    E-6  an untouched envelope verifies as VERIFIED with its anchor transaction
    E-7  a locally edited payload is a 409 HMAC_MISMATCH naming "payload"
    E-8  the anchor table has one row per hash (asserted in the persistence suite)
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from src.apps.console_api.app import build
from src.authority.domain.events import PaymentAllowed
from src.evidence.domain.ids import EnvelopeId, new_id
from src.shared.infrastructure.config import Settings, load_settings

OWNER = {"Authorization": "Bearer demo-owner-token"}
CONSOLE = {"Authorization": "Bearer demo-payer-token"}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings: Settings = load_settings(
        env="ci",
        console_database_url=f"sqlite+aiosqlite:///{tmp_path / 'bursar.db'}",
        hmac_key="test-hmac-key-not-a-secret",
        settlement_private_key="0x" + "11" * 32,
        rigorix_api_key="test",
    )
    with TestClient(build(settings)) as test_client:
        yield test_client


def _seal(client: TestClient, event: PaymentAllowed | None = None) -> Any:
    """Drive the runtime subscriber exactly as the delivery worker would."""
    delivered = event or PaymentAllowed(
        intent_id="intent-1", amount_micro_usdc=42_500_000, reservation_id="res-1"
    )
    portal = client.portal
    assert portal is not None
    subscriber = client.app.state.evidence_subscriber  # type: ignore[attr-defined]

    async def _run() -> Any:
        return await subscriber.handle(delivered, actor="authority")

    return portal.call(_run)


class TestEvidenceHttp:
    def test_sealed_fact_is_listed_and_readable(self, client: TestClient) -> None:
        sealed = _seal(client)
        assert sealed.sealed is True

        listing = client.get("/v1/evidence", headers=OWNER)
        assert listing.status_code == 200, listing.text
        body = listing.json()
        assert len(body["items"]) == 1
        item = body["items"][0]
        assert item["envelope_id"] == sealed.envelope_id
        assert item["event_type"] == "PaymentAllowed"
        assert item["envelope_hash"] == sealed.envelope_hash
        # list view never leaks the fact body
        assert item["payload"] is None

        full = client.get(f"/v1/evidence/{sealed.envelope_id}?full=1", headers=OWNER)
        assert full.status_code == 200, full.text
        assert full.json()["payload"]["amount_micro_usdc"] == 42_500_000

    def test_replayed_delivery_produces_one_envelope(self, client: TestClient) -> None:
        event = PaymentAllowed(
            intent_id="intent-4", amount_micro_usdc=1_000_000, reservation_id="res-4"
        )
        first = _seal(client, event)
        second = _seal(client, event)
        third = _seal(client, event)

        assert first.duplicate is False
        assert second.duplicate is True and third.duplicate is True
        listing = client.get("/v1/evidence?intent_id=intent-4", headers=OWNER)
        assert len(listing.json()["items"]) == 1

    def test_untouched_envelope_verifies_with_its_anchor(self, client: TestClient) -> None:
        sealed = _seal(client)
        response = client.get(f"/v1/evidence/{sealed.envelope_id}/verify", headers=CONSOLE)

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["result"] == "VERIFIED"
        assert body["anchor_tx"] == sealed.anchor_tx

        anchor = client.get(f"/v1/evidence/{sealed.envelope_id}/anchor", headers=OWNER)
        assert anchor.status_code == 200, anchor.text
        assert anchor.json()["anchor_tx"] == sealed.anchor_tx

    def test_one_flipped_byte_is_a_named_hmac_mismatch(self, client: TestClient) -> None:
        """E-7: insert a row whose payload no longer matches the sealed HMAC."""
        original = _seal(client)
        tampered_id = str(EnvelopeId(new_id()))

        async def _insert_tampered() -> None:
            from sqlalchemy import text

            factory = client.app.state.session_factory  # type: ignore[attr-defined]
            async with factory() as session:
                await session.execute(
                    text(
                        "INSERT INTO evidence_envelopes (id, event_type, subject_intent_id, "
                        "subject_invoice_id, subject_payee_id, payload, constitution_version, "
                        "actor, occurred_at, hmac, previous_hash, anchor_mode) "
                        "SELECT :new_id, event_type, subject_intent_id, subject_invoice_id, "
                        "subject_payee_id, :payload, "
                        "constitution_version, actor, occurred_at, hmac, previous_hash, "
                        "anchor_mode FROM evidence_envelopes WHERE id = :old_id"
                    ),
                    {
                        "new_id": tampered_id,
                        "old_id": original.envelope_id,
                        "payload": '{"amount_micro_usdc":42500001}',
                    },
                )
                await session.commit()

        portal = client.portal
        assert portal is not None
        portal.call(_insert_tampered)
        response = client.get(f"/v1/evidence/{tampered_id}/verify", headers=CONSOLE)

        assert response.status_code == 409, response.text
        error = response.json()["error"]
        assert error["details"]["result"] == "HMAC_MISMATCH"
        assert error["details"]["field"] == "payload"
        # the tampered hash has no anchor; the original anchor row is untouched
        assert error["details"]["anchor_tx"] == ""
        original_anchor = client.get(f"/v1/evidence/{original.envelope_id}/anchor", headers=OWNER)
        assert original_anchor.json()["anchor_tx"] == original.anchor_tx
