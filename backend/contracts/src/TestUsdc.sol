// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title TestUsdc — a 6-decimal ERC-20 for the PaymentRouter tests
/// @notice Deliberately tiny: the router only needs `transferFrom`, `approve`, `transfer` and
///         `balanceOf`. It stands in for USDC on an in-process EVM so the suite needs no network and
///         no Anvil (see `tests/unit/settlement/chain/test_payment_router_contract.py`).
///
/// Reference: `docs/contracts/settlement-contract-freeze.md` (SC-9, SC-10)
/// Canonical: `.pi/architecture/modules/settlement.md#components`
///
/// It is a **test fixture**, not a token design: `mint` is unguarded, decimals are fixed at 6 to match
/// USDC, and no fee/blacklist behaviour is modelled because the router must not depend on any.
contract TestUsdc {
    string public constant name = "Test USD Coin";
    string public constant symbol = "USDC";
    uint8 public constant decimals = 6;

    uint256 public totalSupply;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);

    error InsufficientBalance(address from, uint256 available, uint256 required);
    error InsufficientAllowance(address spender, uint256 available, uint256 required);

    function mint(address to, uint256 amount) external returns (bool) {
        totalSupply += amount;
        balanceOf[to] += amount;
        emit Transfer(address(0), to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _move(msg.sender, to, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        uint256 approved = allowance[from][msg.sender];
        if (approved < amount) revert InsufficientAllowance(msg.sender, approved, amount);
        // An infinite allowance is the common ERC-20 idiom; only finite ones are decremented.
        if (approved != type(uint256).max) {
            allowance[from][msg.sender] = approved - amount;
        }
        _move(from, to, amount);
        return true;
    }

    function _move(address from, address to, uint256 amount) private {
        uint256 available = balanceOf[from];
        if (available < amount) revert InsufficientBalance(from, available, amount);
        unchecked {
            balanceOf[from] = available - amount;
            balanceOf[to] += amount;
        }
        emit Transfer(from, to, amount);
    }
}
