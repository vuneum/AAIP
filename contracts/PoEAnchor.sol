// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
/// @title  PoEAnchor
/// @notice Immutable on-chain registry: links AAIP Proof-of-Execution
///         hashes to their AEP settlement transaction hashes.
///         Deployed on Base Sepolia (chainId 84532).
contract PoEAnchor {

    // ── State ──────────────────────────────────────────
    address public owner;
    mapping(address => bool) public authorised;

    mapping(bytes32 => bytes32) public anchors;
    mapping(bytes32 => string)  public anchorOwner;

    // ── Events ─────────────────────────────────────────
    event Anchored(
        string  indexed agentId,
        bytes32 indexed poeHash,
        bytes32         paymentTx,
        uint256         timestamp
    );
    event Authorised(address indexed addr);
    event Deauthorised(address indexed addr);
    event OwnershipTransferred(address indexed from, address indexed to);

    // ── Constructor ────────────────────────────────────
    constructor() {
        owner = msg.sender;
        authorised[msg.sender] = true;
        emit Authorised(msg.sender);
    }

    // ── Modifiers ──────────────────────────────────────
    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }

    modifier onlyAuthorised() {
        require(authorised[msg.sender], "not authorised");
        _;
    }

    // ── Owner management ──────────────────────────────
    function authorise(address addr) external onlyOwner {
        authorised[addr] = true;
        emit Authorised(addr);
    }

    function deauthorise(address addr) external onlyOwner {
        authorised[addr] = false;
        emit Deauthorised(addr);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        require(newOwner != address(0), "zero address");
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    // ── Core ───────────────────────────────────────────
    /// @notice Anchor a PoE hash to its settlement tx. Immutable once set.
    function anchor(
        string  calldata agentId,
        bytes32          poeHash,
        bytes32          paymentTx
    ) external onlyAuthorised {
        require(anchors[poeHash] == bytes32(0), "already anchored");
        anchors[poeHash]     = paymentTx;
        anchorOwner[poeHash] = agentId;
        emit Anchored(agentId, poeHash, paymentTx, block.timestamp);
    }

    function isAnchored(bytes32 poeHash) external view returns (bool) {
        return anchors[poeHash] != bytes32(0);
    }

    function getPaymentTx(bytes32 poeHash) external view returns (bytes32) {
        return anchors[poeHash];
    }
}