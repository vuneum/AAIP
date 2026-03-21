// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;
/// @title  PoEAnchor
/// @notice Immutable on-chain registry: links AAIP Proof-of-Execution
///         hashes to their AEP settlement transaction hashes.
///         Deployed on Base Sepolia (chainId 84532).
contract PoEAnchor {
    event Anchored(
        string  indexed agentId,
        bytes32 indexed poeHash,
        bytes32         paymentTx,
        uint256         timestamp
    );
    mapping(bytes32 => bytes32) public anchors;
    mapping(bytes32 => string)  public anchorOwner;
    /// @notice Anchor a PoE hash to its settlement tx. Immutable once set.
    function anchor(
        string  calldata agentId,
        bytes32          poeHash,
        bytes32          paymentTx
    ) external {
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