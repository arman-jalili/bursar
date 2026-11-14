"""SC-2 — `payments.broadcast` sends already-signed bytes and does nothing else.

Canonical: `docs/architecture/modules/settlement.md#ports-infrastructure-adapters`
Reference: `docs/contracts/settlement-contract-freeze.md` §2.8 and §7

The governed step runs this command, so what it must *not* be able to do is as important as what it does:
no database, no order lookup, no network re-derivation, no signing. The tests below pin that shape — one
required option, one payload, one call to the node — and never open a socket: the sender is injected.

A refusal prints the node's own reason and exits non-zero, so a Rigorix `Failed` step carries the truth
rather than a generic failure.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from src.settlement.domain.errors import SettlementRefusal
from src.settlement.infrastructure.chain import broadcast_cli
from src.settlement.infrastructure.chain.broadcast_cli import (
    broadcast_raw_transaction,
    main,
    parse_args,
)
from src.shared.domain.errors import ErrorCode, ValidationError
from src.shared.infrastructure.config import Settings, load_settings

RAW = "0x02f8" + "ab" * 60
TX_HASH = "0x" + "cd" * 32


def a_settings() -> Settings:
    return load_settings(rpc_url="http://127.0.0.1:8545")


class RecordingSender:
    """Stands in for the node: records the call and answers with a hash."""

    def __init__(self, *, answer: str = TX_HASH, refusal: str = "") -> None:
        self.answer = answer
        self.refusal = refusal
        self.calls: list[tuple[str, str]] = []

    def __call__(self, rpc_url: str, raw_transaction: str) -> str:
        self.calls.append((rpc_url, raw_transaction))
        if self.refusal:
            raise SettlementRefusal(
                ErrorCode.CONFLICT,
                "The node refused the signed transaction; nothing was broadcast.",
                details={"stage": "broadcast", "reason": self.refusal},
            )
        return self.answer


class TestCommandSurface:
    def test_it_takes_the_signed_bytes_and_nothing_else(self) -> None:
        """SC-2: no order id, no payee — nothing to re-derive a payment from.

        `--rpc-url` is the deployment endpoint rendered by settlement code, not a payment field;
        without it the configured `BURSAR_RPC_URL` applies.
        """
        args = parse_args(["--raw-tx", RAW])

        assert args.raw_tx == RAW
        assert args.rpc_url is None
        assert vars(args) == {"raw_tx": RAW, "rpc_url": None}

    def test_the_deployment_endpoint_can_be_rendered_into_the_command(self) -> None:
        """The governed step does not inherit the environment, so the endpoint may ride the argv."""
        args = parse_args(["--rpc-url", "http://anvil:8545", "--raw-tx", RAW])

        assert args.rpc_url == "http://anvil:8545"
        assert args.raw_tx == RAW

    def test_an_order_looking_argument_is_rejected(self) -> None:
        """There is no path by which a caller can point this command at an order or a network."""
        with pytest.raises(SystemExit):
            parse_args(["--raw-tx", RAW, "--order-id", "abc"])

    def test_the_payload_is_required(self) -> None:
        with pytest.raises(SystemExit):
            parse_args([])

    def test_abbreviations_are_not_accepted(self) -> None:
        """`--raw` must not silently mean `--raw-tx`: the command has exactly one spelling (SC-2)."""
        with pytest.raises(SystemExit):
            parse_args(["--raw", RAW])


class TestBroadcast:
    def test_it_sends_the_bytes_and_prints_the_hash(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sender = RecordingSender()

        code = main(["--raw-tx", RAW], settings=a_settings(), sender=sender)

        assert code == 0
        assert capsys.readouterr().out.strip() == TX_HASH
        # The configured RPC and the order's own bytes — nothing was signed or re-derived here.
        assert sender.calls == [("http://127.0.0.1:8545", RAW)]

    def test_a_node_refusal_prints_the_reason_and_exits_non_zero(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A refusal must reach the operator in the node's own words, not as a bare traceback."""
        sender = RecordingSender(refusal="already known")

        code = main(["--raw-tx", RAW], settings=a_settings(), sender=sender)

        assert code == 1
        assert "refused: already known" in capsys.readouterr().err

    def test_malformed_bytes_are_refused_before_the_node_is_called(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sender = RecordingSender()

        code = main(["--raw-tx", "not-hex"], settings=a_settings(), sender=sender)

        assert code == 1
        assert "refused" in capsys.readouterr().err
        assert sender.calls == []

    def test_the_real_sender_refuses_non_hex_bytes_without_a_socket(self) -> None:
        """The bytes are validated before `Web3` is even constructed, so a typo costs no connection."""
        with pytest.raises(ValidationError):
            broadcast_raw_transaction("http://127.0.0.1:1", "0xnothex")

    def test_an_odd_length_payload_is_refused(self) -> None:
        with pytest.raises(ValidationError):
            broadcast_raw_transaction("http://127.0.0.1:1", "0x02f8a")


def test_the_console_script_points_at_this_module() -> None:
    """The entry point Rigorix will call is the module constant's command (SC-2)."""
    import tomllib

    project = tomllib.loads((Path(__file__).resolve().parents[4] / "pyproject.toml").read_text())
    assert (
        project["project"]["scripts"]["payments.broadcast"]
        == "src.settlement.infrastructure.chain.broadcast_cli:main"
    )


def test_the_module_has_no_database_or_signing_import() -> None:
    """Its only job is "send these bytes": a session factory or a key here would be a second path."""
    source = Path(sys.modules[broadcast_cli.__name__].__file__ or "")
    text = source.read_text(encoding="utf-8")

    for forbidden in (
        "sqlalchemy",
        "session_scope",
        "Account.sign_transaction",
        "settlement_private_key",
        "SettlementOrder",
        "ChainNetwork",
    ):
        assert forbidden not in text, f"payments.broadcast must not depend on {forbidden}"
