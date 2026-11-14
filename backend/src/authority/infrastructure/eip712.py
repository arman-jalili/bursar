"""The approval binder — EIP-712 document plus secp256k1 recovery (A-13, A-15).

Canonical: .pi/architecture/modules/authority.md#domain-services
Reference: docs/contracts/authority-contract-freeze.md §2.10

Two halves, on purpose:

* `typed_data` returns the **frozen** `PaymentIntent.signed_payload()` verbatim. There is no second
  field list here: the same mapping must generate the Python verifier and the on-chain checker
  (ADR-007), and a hand-kept second list is how the two drift.
* `recover_signer` answers only *who signed*. It never grants authority: `Approval.verify` compares the
  recovered address to the mandate owner (A-15) and `Approval.consume` makes the approval single-use
  (A-14). A binder that also granted authority would make single-use untestable.

The digest recovered over is the intent's canonical `typed_data_hash()` — the one field every approval
stores. Full EIP-712 *struct* encoding (domain separator, type hashes) belongs to the Solidity/Python
codegen step; the binding guarantee (one digest over the signed fields) is what this adapter provides
and what A-13 requires.

Installing `eth-account` gives us `eth-keys` (secp256k1 recovery) and `eth-utils` (keccak). No private
key ever reaches this process: recovery is public-key arithmetic over the signature the owner produced.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from eth_keys import keys
from eth_utils import keccak, to_checksum_address

from src.authority.domain.errors import ApprovalBindingMismatch
from src.authority.domain.payment_intent import PaymentIntent
from src.authority.domain.services import ApprovalBinder
from src.mandate.domain.values import EvmAddress

__all__ = ["EcdsaApprovalBinder", "sign_digest"]


class EcdsaApprovalBinder(ApprovalBinder):
    """EIP-712-shaped document + `r || s || v` recovery over the frozen canonical digest."""

    def typed_data(self, intent: PaymentIntent) -> Mapping[str, Any]:
        """The exact document the owner signs — the intent's own payload, no re-derivation."""
        return intent.signed_payload()

    def recover_signer(self, *, typed_data_hash: str, signature_hex: str) -> EvmAddress:
        """Recover the signing address, or refuse without a side effect (A-13/A-15).

        A malformed signature is an `ApprovalBindingMismatch` (409 `APPROVAL_INVALID`), not a 500:
        a caller sending garbage is a refusal case the console must be able to render.
        """
        try:
            digest = bytes.fromhex(typed_data_hash.removeprefix("0x"))
            raw = bytes.fromhex(signature_hex.removeprefix("0x"))
        except ValueError as exc:
            raise ApprovalBindingMismatch("signature", detail="not hex") from exc

        if len(digest) != 32 or len(raw) != 65:
            raise ApprovalBindingMismatch(
                "signature", detail="expected 32-byte digest and 65-byte signature"
            )

        v = raw[64]
        if v >= 27:
            v -= 27
        if v not in (0, 1):
            raise ApprovalBindingMismatch("signature", detail="invalid recovery id")

        signature = keys.Signature(
            vrs=(v, int.from_bytes(raw[0:32], "big"), int.from_bytes(raw[32:64], "big"))
        )
        try:
            public_key = signature.recover_public_key_from_msg_hash(digest)
        except Exception as exc:  # eth-keys raises ValueError for an unrecoverable point
            raise ApprovalBindingMismatch("signature", detail="unrecoverable") from exc

        # Checksum case matters: `EvmAddress` preserves case and compares by value (Mandate stores the
        # owner checksummed), so recovering the lowercase form would reject the real owner.
        address = to_checksum_address(keccak(public_key.to_bytes())[-20:])
        return EvmAddress(address)


def sign_digest(typed_data_hash: str, private_key_hex: str) -> str:
    """Sign the frozen digest — for fixtures and the local demo signer, never for a server path.

    Kept next to the verifier so a test can produce the exact bytes `recover_signer` consumes without
    depending on a wallet toolchain. The private key is a test fixture: this function is not called by
    any request path.
    """
    from eth_account import Account  # local import: the runtime path never needs signing

    digest = bytes.fromhex(typed_data_hash.removeprefix("0x"))
    signed = Account.unsafe_sign_hash(digest, private_key=private_key_hex)
    return "0x" + bytes(signed.signature).hex()
