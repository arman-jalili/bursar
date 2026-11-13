"""Fixtures for the Mandate behaviour tests: parties, a fake owner proof, and a payee factory."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from src.mandate.domain.constitution import Constitution
from src.mandate.domain.entities import Agent, Owner, Payer
from src.mandate.domain.ids import AgentId, HouseholdId, OwnerId, PayerId, new_id
from src.mandate.domain.payee import Payee
from src.mandate.domain.values import (
    BankDigest,
    Cap,
    DisplayName,
    EvmAddress,
    PartyRef,
    PayeeAddress,
    PayeeName,
    Role,
    RoutingDetails,
    Threshold,
    usdc_to_micro,
)

OWNER_ADDRESS = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"
PAYEE_ADDRESS = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"


@dataclass
class FakeProof:
    """A stand-in for the EIP-712 verifier: says yes, or no, and records what it was asked."""

    valid: bool = True

    def __post_init__(self) -> None:
        self.seen: list[tuple[object, ...]] = []

    def signs(self, *subjects: object) -> bool:
        self.seen.append(subjects)
        return self.valid


@pytest.fixture
def household_id() -> HouseholdId:
    return HouseholdId(new_id())


@pytest.fixture
def owner(household_id: HouseholdId) -> Owner:
    return Owner(id=OwnerId(new_id()), address=EvmAddress(OWNER_ADDRESS), name=DisplayName("Dana"))


@pytest.fixture
def payer() -> Payer:
    return Payer(id=PayerId(new_id()), name=DisplayName("Mum"))


@pytest.fixture
def agent() -> Agent:
    return Agent(id=AgentId(new_id()), key_id="agent-key-1")


@pytest.fixture
def owner_actor(household_id: HouseholdId) -> PartyRef:
    return PartyRef(role=Role.OWNER, id="owner-1", household_id=household_id)


@pytest.fixture
def agent_actor(household_id: HouseholdId) -> PartyRef:
    return PartyRef(role=Role.AGENT, id="agent-1", household_id=household_id)


@pytest.fixture
def proof() -> FakeProof:
    return FakeProof(valid=True)


@pytest.fixture
def bad_proof() -> FakeProof:
    return FakeProof(valid=False)


@pytest.fixture
def cap() -> Cap:
    return Cap(micro_usdc=usdc_to_micro("150"))


@pytest.fixture
def threshold() -> Threshold:
    return Threshold(micro_usdc=usdc_to_micro("25"))


@pytest.fixture
def constitution(household_id: HouseholdId, cap: Cap, threshold: Threshold) -> Constitution:
    return Constitution.initial(household_id, cap, threshold)


def a_digest(account: str = "DE89370400440532013000") -> BankDigest:
    return BankDigest.from_routing_details(RoutingDetails(scheme="sepa", account_number=account))


@pytest.fixture
def payee(household_id: HouseholdId, owner_actor: PartyRef, proof: FakeProof) -> Payee:
    return Payee.register(
        household_id=household_id,
        name=PayeeName("Northwind Energy"),
        address=PayeeAddress(PAYEE_ADDRESS),
        digest=a_digest(),
        actor=owner_actor,
        proof=proof,
    )
