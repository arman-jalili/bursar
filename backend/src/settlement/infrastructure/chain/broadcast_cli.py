"""`payments.broadcast` — send one already-signed transaction. Nothing else.

Canonical: `docs/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 (amended in §7)

This is the governed step's whole body (SC-2: `DISPATCH_COMMAND` renders
`payments.broadcast --raw-tx <hex>`, a module constant). It exists because the *signing* happens
in-process — that is where the tx hash comes from — while the *broadcast* has to happen inside Rigorix's
`run_command`, so the payment action keeps its HMAC-signed audit envelope. Splitting the two is what lets
the order persist its hash before anything is sent (SC-3).

What it deliberately does not do — each of these would be a second payment path:

* it does not read the database, look up an order, or re-derive which order the bytes belong to;
* it does not sign, so it cannot produce bytes that were not already recorded;
* it does not choose, derive or verify a network: the signed bytes already carry the chain id, and the
  RPC endpoint is configuration.

Re-sending the same bytes is a node-level replay of the same transaction (same hash, same nonce), which
is why an operator recovering a `signed` order runs this command again instead of re-dispatching. The
on-chain nullifier is what actually refuses a second payment (SC-5).

Usage::

    payments.broadcast --raw-tx 0x02f8...

Exit: 0 = accepted (the tx hash is printed on stdout); 1 = refused (the reason is printed on stderr).
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable, Sequence

from hexbytes import HexBytes
from web3 import Web3

from src.settlement.domain.errors import SettlementRefusal
from src.shared.domain.errors import ErrorCode, ValidationError
from src.shared.infrastructure.config import Settings, get_settings

__all__ = ["broadcast_raw_transaction", "main", "parse_args", "require_signed_hex"]

#: `0x`-prefixed, non-empty, even-length hex: the only payload this command accepts.
_SIGNED_HEX = re.compile(r"^0x(?:[0-9a-fA-F]{2})+$")


def require_signed_hex(raw_transaction: str) -> str:
    """The payload, or a `ValidationError` — checked before a socket is opened or a sender is called.

    Raises:
        ValidationError: the payload is not `0x`-prefixed hex. That is a malformed argument, not a
            payment, and it is refused before anything else happens.
    """
    if not _SIGNED_HEX.match(raw_transaction):
        raise ValidationError(
            "--raw-tx must be 0x-prefixed hex of the signed transaction bytes",
            raw_tx=raw_transaction[:80],
            length=str(len(raw_transaction)),
        )
    return raw_transaction


def broadcast_raw_transaction(rpc_url: str, raw_transaction: str) -> str:
    """Send the bytes to `rpc_url` and return the node's tx hash.

    Raises:
        ValidationError: the payload is not `0x`-prefixed hex (see `require_signed_hex`).
        SettlementRefusal: the node rejected the bytes or the RPC failed. The node's own reason is
            carried in `details["reason"]`, never paraphrased away.
    """
    payload = require_signed_hex(raw_transaction)
    try:
        sent = Web3(Web3.HTTPProvider(rpc_url)).eth.send_raw_transaction(HexBytes(payload))
    except Exception as exc:  # provider boundary: every failure is a refusal
        reason = " ".join(str(exc).split())[:200] or type(exc).__name__
        raise SettlementRefusal(
            ErrorCode.CONFLICT,
            "The node refused the signed transaction; nothing was broadcast.",
            details={
                "stage": "broadcast",
                "reason": reason,
                "error_type": type(exc).__name__,
                "rpc_url": rpc_url,
            },
        ) from exc
    return "0x" + bytes(sent).hex()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """One option, no positionals, no abbreviations: there is nothing else to say to this command."""
    parser = argparse.ArgumentParser(
        prog="payments.broadcast",
        description="Broadcast one already-signed settlement transaction through the configured RPC.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--raw-tx",
        required=True,
        metavar="HEX",
        help="0x-prefixed hex of the signed transaction bytes (nothing is signed here).",
    )
    # The governed step runs inside Rigorix's sandbox, which does not inherit the deployment's
    # environment, so a `BURSAR_RPC_URL` default alone silently sends the broadcast to a
    # non-existent 127.0.0.1:8545. The rendered command carries the endpoint explicitly.
    parser.add_argument(
        "--rpc-url",
        default=None,
        metavar="URL",
        help="JSON-RPC endpoint to send the bytes to (defaults to the configured BURSAR_RPC_URL).",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    sender: Callable[[str, str], str] = broadcast_raw_transaction,
) -> int:
    """CLI entry point: print the hash, or print the refusal and exit non-zero.

    `settings` and `sender` are injection seams for tests; the defaults are the configured RPC and the
    real node call. Even with them, no test reaches a network.
    """
    args = parse_args(argv)
    resolved = settings or get_settings()
    try:
        rpc_url = str(getattr(args, "rpc_url", None) or resolved.rpc_url)
        tx_hash = sender(rpc_url, require_signed_hex(str(args.raw_tx)))
    except SettlementRefusal as refused:
        reason = refused.details.get("reason") or str(refused)
        print(f"payments.broadcast: refused: {reason}", file=sys.stderr)
        return 1
    except ValidationError as malformed:
        print(f"payments.broadcast: refused: {malformed}", file=sys.stderr)
        return 1
    print(tx_hash)
    return 0


if __name__ == "__main__":  # pragma: no cover - the console script is the entry point
    raise SystemExit(main())
