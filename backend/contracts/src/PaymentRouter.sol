// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title PaymentRouter — Lock 3, the commit-point lock
/// @notice Moves USDC from the settlement operator to a payee exactly once per invoice, and refuses
///         anything the off-chain layers were not allowed to decide.
///
/// Canonical: `docs/architecture/modules/settlement.md#components`
/// Reference: `docs/contracts/settlement-contract-freeze.md` (SC-5, SC-6, SC-9, SC-11)
/// Decision: `docs/architecture/decisions/ADR-007-compliance-engine-architecture.md`
///
/// Three properties, and nothing else, are the contract's reason to exist:
///
///  1. **One invoice, one payment.** `nullifier` is the once-only marker derived off-chain from the
///     invoice identity. `spentNullifiers[nullifier]` is flipped before the token call, so a replay
///     reverts with `NullifierSpent` even when the whole application is bypassed (scenario 6, SC-5/SC-6).
///  2. **The second lock stays shut.** For payments that require it, the router verifies an EIP-712
///     signature from the immutable `owner` over the exact bytes it is about to move — order id,
///     nullifier, payer, payee, amount. A stolen operator key still cannot pay a payee the owner did
///     not sign for (A-15, S-2, SC-9).
///  3. **One write-side fact.** `Anchored` is emitted on every path that *returns* instead of
///     reverting: a settled payment, and a reference-only write (`anchor`). A revert emits nothing —
///     an event that survived a revert would be a receipt for a payment nobody made (SC-6, SC-8).
///
/// Named errors, not `require` strings: the gateway maps a refused transaction to a domain refusal by
/// decoding the error selector, so a reworded message cannot silently change a product outcome.
///
/// The token is passed in the constructor rather than hardcoded: Anvil and Base Sepolia must never
/// share a router or a USDC address (SC-11), and the same bytecode has to serve both.
interface IERC20 {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);

    function balanceOf(address account) external view returns (uint256);
}

contract PaymentRouter {
    // ── errors: the refusal vocabulary, on-chain ────────────────────────────
    /// @dev The invoice's nullifier is already spent — the on-chain half of scenario 6 (SC-5, SC-6).
    error NullifierSpent(bytes32 nullifier);

    /// @dev The payment requires the owner's EIP-712 signature and none was supplied (SC-9, A-15).
    error OwnerSignatureRequired(bytes32 orderId);

    /// @dev `ecrecover` did not return the immutable owner: the signature is not the owner's (A-15).
    error OwnerSignatureInvalid(address recovered, address owner);

    /// @dev A zero amount would move nothing while consuming the nullifier (SC-9).
    error AmountNotPositive(uint256 amount);

    /// @dev A zero payee would burn the transfer; a zero router token would make `pay` a no-op.
    error ZeroAddress(string field);

    /// @dev The token refused the movement (`transferFrom` returned false) — nothing is recorded.
    error TransferFailed(address payee, uint256 amount);

    // ── events ──────────────────────────────────────────────────────────────
    /// @notice Emitted on a settled payment and on a reference-only anchor write.
    /// @param orderId keccak256 of the off-chain settlement order id (`bytes32 indexed`).
    /// @param nullifier the invoice's once-only marker (`bytes32 indexed`).
    /// @param txRef a reference to what was written: for `pay`, keccak256 of the exact movement; for
    ///        `anchor`, the anchored hash itself (no funds moved, so no order/nullifier context).
    event Anchored(bytes32 indexed orderId, bytes32 indexed nullifier, bytes32 txRef);

    // ── EIP-712 ─────────────────────────────────────────────────────────────
    /// @dev `EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)`.
    bytes32 public constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    /// @dev `Payment(bytes32 orderId,bytes32 nullifier,address payer,address payee,uint256 amount)`.
    ///      `payer` is the caller, so a signature can never be replayed by another operator.
    bytes32 public constant PAYMENT_TYPEHASH =
        keccak256("Payment(bytes32 orderId,bytes32 nullifier,address payer,address payee,uint256 amount)");

    bytes32 public constant DOMAIN_NAME_HASH = keccak256("Bursar PaymentRouter");
    bytes32 public constant DOMAIN_VERSION_HASH = keccak256("1");

    /// @notice The EIP-712 domain separator: name, version, this chain id, this contract (SC-11).
    ///         Cached in the constructor so a chain-id change is a redeploy, not a silent re-bind.
    bytes32 public immutable domainSeparator;

    /// @notice The household owner. The only address an owner signature may recover to (A-15).
    address public immutable owner;

    /// @notice The ERC-20 USDC this router moves on this chain (SC-11).
    IERC20 public immutable usdc;

    mapping(bytes32 => bool) private _spentNullifiers;

    constructor(address owner_, address usdc_) {
        if (owner_ == address(0)) revert ZeroAddress("owner");
        if (usdc_ == address(0)) revert ZeroAddress("usdc");
        owner = owner_;
        usdc = IERC20(usdc_);
        domainSeparator = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                DOMAIN_NAME_HASH,
                DOMAIN_VERSION_HASH,
                block.chainid,
                address(this)
            )
        );
    }

    // ── write: the payment ──────────────────────────────────────────────────

    /// @notice Move `amount` micro-USDC from the caller (the settlement operator) to `payee`, once.
    /// @param orderId `keccak256` of the off-chain order id — the anchoring key.
    /// @param nullifier the invoice's once-only marker (SC-5).
    /// @param payee the address frozen on the signed intent (S-2) — never re-read at submit time.
    /// @param amount the amount frozen on the signed intent, in micro-USDC (SC-9).
    /// @param requiresOwnerSignature when true, `ownerSignature` must recover to `owner` (A-15).
    /// @param ownerSignature a 65-byte `r || s || v` EIP-712 signature, or empty when not required.
    /// @return txRef keccak256 of the exact movement, as emitted in `Anchored`.
    function pay(
        bytes32 orderId,
        bytes32 nullifier,
        address payee,
        uint256 amount,
        bool requiresOwnerSignature,
        bytes calldata ownerSignature
    ) external returns (bytes32 txRef) {
        // The commit point. Checked and burned before any external call: a re-entrant replay inside
        // the token's transfer hook must not see an unspent marker (checks-effects-interactions).
        if (_spentNullifiers[nullifier]) revert NullifierSpent(nullifier);
        if (payee == address(0)) revert ZeroAddress("payee");
        if (amount == 0) revert AmountNotPositive(amount);

        if (requiresOwnerSignature) {
            if (ownerSignature.length == 0) revert OwnerSignatureRequired(orderId);
            address recovered =
                _recover(paymentDigest(orderId, nullifier, msg.sender, payee, amount), ownerSignature);
            if (recovered != owner) revert OwnerSignatureInvalid(recovered, owner);
        }

        _spentNullifiers[nullifier] = true;

        if (!usdc.transferFrom(msg.sender, payee, amount)) revert TransferFailed(payee, amount);

        txRef = keccak256(abi.encode(orderId, nullifier, msg.sender, payee, amount));
        emit Anchored(orderId, nullifier, txRef);
    }

    /// @notice Write a 32-byte reference on-chain and emit `Anchored` — no funds move.
    ///
    /// The revert-free path: an evidence/envelope hash, or the hash of a refusal that never became a
    /// transaction, still gets an independent timestamp. It spends no nullifier, so an anchor can never
    /// be mistaken for a settlement (ADR-006, SC-10).
    /// @param anchoredHash the 32-byte reference to timestamp.
    /// @return anchoredHash returned unchanged, so a caller can bind the ledger write to its input.
    function anchor(bytes32 anchoredHash) external returns (bytes32) {
        // No order context: an anchor names an artefact, not a payment. `txRef` carries the hash.
        emit Anchored(bytes32(0), bytes32(0), anchoredHash);
        return anchoredHash;
    }

    // ── views ───────────────────────────────────────────────────────────────

    /// @notice True once an invoice's nullifier has been consumed (SC-5) — the read `ChainGateway`
    ///         makes so the application can refuse a replay one layer before the contract does.
    function spentNullifiers(bytes32 nullifier) external view returns (bool) {
        return _spentNullifiers[nullifier];
    }

    /// @notice The EIP-712 digest the owner signs for one payment (A-15).
    /// @dev The Python signer/verifier uses the same field order and the same type string; a hand-kept
    ///      second list here is how the two drift (ADR-007).
    function paymentDigest(
        bytes32 orderId,
        bytes32 nullifier,
        address payer,
        address payee,
        uint256 amount
    ) public view returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(PAYMENT_TYPEHASH, orderId, nullifier, payer, payee, amount)
        );
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    /// @notice The struct hash and digest in one call, for the off-chain verifier.
    function hashPayment(
        bytes32 orderId,
        bytes32 nullifier,
        address payer,
        address payee,
        uint256 amount
    ) external view returns (bytes32 structHash, bytes32 digest) {
        structHash = keccak256(abi.encode(PAYMENT_TYPEHASH, orderId, nullifier, payer, payee, amount));
        digest = keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }

    /// @dev Recover the signer, or the zero address for anything malformed.
    ///
    /// Two refusals matter here and both are silent in plain `ecrecover`: a signature whose `s` is in
    /// the upper half of the curve order is valid but malleable (a third party can produce a second,
    /// different signature for the same digest), and a `v` outside {27, 28} recovers garbage. Both
    /// return the zero address, which can never equal an immutable non-zero `owner`.
    function _recover(bytes32 digest, bytes calldata signature) private pure returns (address) {
        if (signature.length != 65) return address(0);
        bytes32 r;
        bytes32 s;
        uint8 v;
        // Only calldata is read, so this block is memory-safe.
        assembly ("memory-safe") {
            r := calldataload(signature.offset)
            s := calldataload(add(signature.offset, 0x20))
            v := byte(0, calldataload(add(signature.offset, 0x40)))
        }
        if (v < 27) v += 27;
        if (v != 27 && v != 28) return address(0);
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }
        return ecrecover(digest, v, r, s);
    }
}
