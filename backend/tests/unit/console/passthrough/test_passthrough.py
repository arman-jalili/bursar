"""CON-03 — the signature endpoint forwards the received body unmodified.

Canonical: .pi/architecture/modules/console.md#key-use-case-sequence--owner-approves-on-a-phone
Reference: docs/contracts/console-contract-freeze.md §1 (CON-03), §2.5, §2.11

The owner signs EIP-712 typed data. A single re-ordered key, a re-serialised float or an injected
`approval_id` changes the bytes Authority verifies, and the refusal that follows looks like the
owner's fault. The console therefore takes `bytes` and gives back `bytes`.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from src.console.application.dto import SignatureOutcome
from src.console.application.services import (
    ProjectApprovalInbox,
    ProjectEvidence,
    ProjectPayerBills,
)
from src.console.interfaces.api import (
    CONSOLE_ROUTES,
    SIGNATURE_PATH,
    ConsoleDeps,
    submit_signature,
)

#: Recorded example of the body the wallet produced. Key order is part of the fixture.
RECORDED_BODY = b'{"signature":"0xdeadbeef","intent_id":"intent-1","amount":"320.00"}'


class _Recorder:
    """Records the bytes it is handed — the only way to prove a passthrough."""

    def __init__(self) -> None:
        self.received: bytes | None = None

    async def list_pending(self, owner_scope: str) -> tuple[Mapping[str, object], ...]:
        return ()

    async def submit_signature(
        self, approval_id: str, raw_body: bytes, content_type: str
    ) -> Mapping[str, object]:
        self.received = raw_body
        return {"granted": True, "reason_codes": ()}

    async def reasons_for(self, intent_id: str) -> tuple[str, ...]:
        return ()


def _deps(recorder: _Recorder) -> ConsoleDeps:
    return ConsoleDeps(
        approval_inbox=ProjectApprovalInbox(recorder, recorder, recorder),  # type: ignore[arg-type]
        payer_bills=ProjectPayerBills(recorder, recorder),  # type: ignore[arg-type]
        evidence=ProjectEvidence(recorder),  # type: ignore[arg-type]
    )


class TestPassthrough:
    async def test_the_received_body_reaches_authority_byte_for_byte(self) -> None:
        """CON-03: the recorded request body must equal the received one, not a re-encoding."""
        recorder = _Recorder()
        outcome = await submit_signature(
            _deps(recorder),
            "ap-1",
            raw_body=RECORDED_BODY,
            content_type="application/json",
            owner_scope="owner-token",
        )
        assert recorder.received == RECORDED_BODY
        assert outcome == SignatureOutcome(granted=True, reason_plain=None, reason_codes=())

    def test_the_signature_route_is_the_only_write_and_needs_the_sign_scope(self) -> None:
        """CON-03: if another row mutates, the passthrough guarantee no longer covers the module."""
        writes = [route for route in CONSOLE_ROUTES if route.mutating]
        assert len(writes) == 1
        assert writes[0].path == SIGNATURE_PATH
        assert writes[0].method == "POST"
        assert writes[0].scope == "authority:sign"

    def test_the_signature_route_never_constructs_a_signed_field(self) -> None:
        """CON-03: the path names an approval, not an amount, payee or digest to fill in."""
        for field in ("amount", "payee_address", "bank_digest", "nonce", "expiry"):
            assert field not in SIGNATURE_PATH


@pytest.mark.contract
def test_the_passthrough_has_no_second_write_path() -> None:
    """CON-03/CON-04: a second POST would be a second place to rewrite a signature."""
    posts = [route.path for route in CONSOLE_ROUTES if route.method == "POST"]
    assert posts == [SIGNATURE_PATH]
