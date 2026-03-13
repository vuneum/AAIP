"""
Tests for AgentIdentity, DeterministicPoE, PoEVerifier, and ValidatorPanel.
Run with: pytest tests/test_identity_poe_validators.py -v
No external deps required — pure-python ed25519 path tested.
"""

import hashlib
import secrets
import time

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_honest_poe(identity=None):
    from aaip.identity import AgentIdentity
    from aaip.poe.deterministic import DeterministicPoE
    if identity is None:
        identity = AgentIdentity.generate()
    poe = DeterministicPoE(identity)
    poe.begin("Analyse AI frameworks and summarise findings")
    poe.record_tool("web_search")
    poe.record_tool("read_url")
    poe.record_model("gpt-4o")
    poe.record_step()
    poe.set_output("LangChain, CrewAI, AutoGPT lack cryptographic PoE. AAIP fills the gap.")
    poe.finish()
    return poe, identity


# ---------------------------------------------------------------------------
# AgentIdentity
# ---------------------------------------------------------------------------

class TestAgentIdentity:

    def test_generate_produces_valid_keypair(self):
        from aaip.identity import AgentIdentity
        ident = AgentIdentity.generate()
        assert len(ident._seed) == 32
        assert len(ident._pub) == 32
        assert len(ident.public_key_hex) == 64
        assert len(ident.agent_id) == 16

    def test_agent_id_is_sha256_prefix(self):
        from aaip.identity import AgentIdentity
        ident = AgentIdentity.generate()
        expected = hashlib.sha256(ident._pub).hexdigest()[:16]
        assert ident.agent_id == expected

    def test_different_seeds_produce_different_identities(self):
        from aaip.identity import AgentIdentity
        id1 = AgentIdentity.generate()
        id2 = AgentIdentity.generate()
        assert id1.agent_id != id2.agent_id
        assert id1.public_key_hex != id2.public_key_hex

    def test_sign_returns_64_bytes(self):
        from aaip.identity import AgentIdentity
        ident = AgentIdentity.generate()
        sig = ident.sign(b"test data")
        assert len(sig) == 64

    def test_verify_valid_signature(self):
        from aaip.identity import AgentIdentity
        ident = AgentIdentity.generate()
        data = b"poe hash bytes 1234"
        sig  = ident.sign(data)
        assert ident.verify(data, sig) is True

    def test_verify_rejects_tampered_message(self):
        from aaip.identity import AgentIdentity
        ident = AgentIdentity.generate()
        sig   = ident.sign(b"original")
        assert ident.verify(b"tampered", sig) is False

    def test_verify_rejects_wrong_identity(self):
        from aaip.identity import AgentIdentity
        id1 = AgentIdentity.generate()
        id2 = AgentIdentity.generate()
        sig = id1.sign(b"data")
        assert id2.verify(b"data", sig) is False

    def test_sign_hex_returns_128_char_string(self):
        from aaip.identity import AgentIdentity
        ident  = AgentIdentity.generate()
        sig_hex = ident.sign_hex(b"data")
        assert len(sig_hex) == 128
        assert all(c in "0123456789abcdef" for c in sig_hex)


# ---------------------------------------------------------------------------
# Pure-Python ed25519 primitives
# ---------------------------------------------------------------------------

class TestPurePythonEd25519:

    def test_pubkey_deterministic_from_seed(self):
        from aaip.identity import _ed25519_pubkey
        seed = secrets.token_bytes(32)
        assert _ed25519_pubkey(seed) == _ed25519_pubkey(seed)

    def test_pubkey_length(self):
        from aaip.identity import _ed25519_pubkey
        assert len(_ed25519_pubkey(secrets.token_bytes(32))) == 32

    def test_sign_verify_roundtrip(self):
        from aaip.identity import _ed25519_sign, _ed25519_verify, _ed25519_pubkey
        seed = secrets.token_bytes(32)
        pub  = _ed25519_pubkey(seed)
        msg  = b"test message"
        sig  = _ed25519_sign(seed, msg)
        assert _ed25519_verify(pub, msg, sig) is True

    def test_verify_rejects_wrong_message(self):
        from aaip.identity import _ed25519_sign, _ed25519_verify, _ed25519_pubkey
        seed = secrets.token_bytes(32)
        pub  = _ed25519_pubkey(seed)
        sig  = _ed25519_sign(seed, b"correct")
        assert _ed25519_verify(pub, b"wrong", sig) is False

    def test_verify_rejects_wrong_pubkey(self):
        from aaip.identity import _ed25519_sign, _ed25519_verify, _ed25519_pubkey
        seed1 = secrets.token_bytes(32)
        seed2 = secrets.token_bytes(32)
        pub2  = _ed25519_pubkey(seed2)
        sig   = _ed25519_sign(seed1, b"msg")
        assert _ed25519_verify(pub2, b"msg", sig) is False

    def test_verify_rejects_truncated_signature(self):
        from aaip.identity import _ed25519_sign, _ed25519_verify, _ed25519_pubkey
        seed = secrets.token_bytes(32)
        pub  = _ed25519_pubkey(seed)
        sig  = _ed25519_sign(seed, b"msg")
        assert _ed25519_verify(pub, b"msg", sig[:32]) is False

    def test_signature_length_is_64_bytes(self):
        from aaip.identity import _ed25519_sign
        sig = _ed25519_sign(secrets.token_bytes(32), b"data")
        assert len(sig) == 64


# ---------------------------------------------------------------------------
# DeterministicPoE
# ---------------------------------------------------------------------------

class TestDeterministicPoE:

    def test_poe_hash_is_64_char_hex(self):
        poe, _ = make_honest_poe()
        assert len(poe.poe_hash) == 64
        assert all(c in "0123456789abcdef" for c in poe.poe_hash)

    def test_signature_is_128_char_hex(self):
        poe, _ = make_honest_poe()
        assert len(poe.signature) == 128

    def test_to_dict_has_required_fields(self):
        poe, _ = make_honest_poe()
        d = poe.to_dict()
        required = ["aaip_version", "agent_id", "task", "tools_used", "model_used",
                    "output_hash", "step_count", "timestamp", "poe_hash", "signature", "public_key"]
        for field in required:
            assert field in d, f"Missing field: {field}"

    def test_tools_sorted_in_canonical_json(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import DeterministicPoE
        ident = AgentIdentity.generate()
        poe   = DeterministicPoE(ident)
        poe.begin("task")
        poe.record_tool("z_tool")
        poe.record_tool("a_tool")
        poe.set_output("result")
        poe.finish()
        d = poe.to_dict()
        assert d["tools_used"] == sorted(d["tools_used"])

    def test_output_hash_is_sha256_of_output(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import DeterministicPoE
        ident  = AgentIdentity.generate()
        poe    = DeterministicPoE(ident)
        output = "The final answer is 42."
        poe.begin("task"); poe.record_tool("t"); poe.set_output(output); poe.finish()
        expected = hashlib.sha256(output.encode()).hexdigest()
        assert poe.to_dict()["output_hash"] == expected

    def test_different_outputs_different_hashes(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import DeterministicPoE
        ident  = AgentIdentity.generate()
        def build(output):
            p = DeterministicPoE(ident)
            p.begin("task"); p.record_tool("t"); p.set_output(output); p.finish()
            return p.poe_hash
        assert build("output A") != build("output B")

    def test_poe_version_is_2_0(self):
        poe, _ = make_honest_poe()
        assert poe.to_dict()["aaip_version"] == "2.0"

    def test_step_count_increments(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import DeterministicPoE
        ident = AgentIdentity.generate()
        poe   = DeterministicPoE(ident)
        poe.begin("task")
        poe.record_step(); poe.record_step(); poe.record_step()
        poe.record_tool("t"); poe.set_output("o"); poe.finish()
        # record_tool also increments step_count, so 3 manual + 1 tool = 4
        assert poe.to_dict()["step_count"] == 4


# ---------------------------------------------------------------------------
# PoEVerifier fraud signals
# ---------------------------------------------------------------------------

class TestPoEVerifier:

    def test_honest_poe_is_verified(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        result  = PoEVerifier().verify(poe.to_dict())
        assert result.verdict == "verified"
        assert result.signals == []
        assert result.approved is True

    def test_hash_mismatch_detected(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        d = poe.to_dict(); d["output_hash"] = "ff" * 32
        result = PoEVerifier().verify(d)
        assert "HASH_MISMATCH" in result.signals
        assert result.verdict == "invalid"

    def test_future_timestamp_detected(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        d = poe.to_dict(); d["timestamp"] = int(time.time()) + 9999
        result = PoEVerifier().verify(d)
        assert "FUTURE_TIMESTAMP" in result.signals

    def test_negative_step_count_detected(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        d = poe.to_dict(); d["step_count"] = -5
        result = PoEVerifier().verify(d)
        assert "NEGATIVE_STEP_COUNT" in result.signals

    def test_no_tools_no_model_detected(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import DeterministicPoE, PoEVerifier
        ident = AgentIdentity.generate()
        poe   = DeterministicPoE(ident)
        poe.begin("task"); poe.set_output("output"); poe.finish()
        result = PoEVerifier().verify(poe.to_dict())
        assert "NO_TOOLS_AND_NO_MODEL" in result.signals

    def test_empty_task_detected(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        d = poe.to_dict(); d["task"] = ""
        result = PoEVerifier().verify(d)
        assert "NO_TASK" in result.signals

    def test_missing_fields_detected(self):
        from aaip.poe.deterministic import PoEVerifier
        result = PoEVerifier().verify({"agent_id": "abc"})
        assert any("MISSING_FIELDS" in s for s in result.signals)

    def test_signature_invalid_wrong_pubkey(self):
        from aaip.identity import AgentIdentity
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        id2    = AgentIdentity.generate()
        d      = poe.to_dict()
        d["public_key"] = id2.public_key_hex
        result = PoEVerifier().verify(d)
        assert "SIGNATURE_INVALID" in result.signals

    def test_signature_invalid_tampered_hash(self):
        from aaip.poe.deterministic import PoEVerifier
        poe, _ = make_honest_poe()
        d      = poe.to_dict()
        d["poe_hash"] = "00" * 32   # valid hex but wrong hash
        result = PoEVerifier().verify(d)
        assert "SIGNATURE_INVALID" in result.signals or "HASH_MISMATCH" in result.signals


# ---------------------------------------------------------------------------
# ValidatorPanel
# ---------------------------------------------------------------------------

class TestValidatorPanel:

    def test_honest_poe_approved_3_validators(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        result  = ValidatorPanel(n=3).vote(poe.to_dict())
        assert result.consensus == "APPROVED"
        assert result.approve_count == 3
        assert result.passed is True

    def test_tampered_poe_rejected(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        d       = poe.to_dict(); d["output_hash"] = "bb" * 32
        result  = ValidatorPanel(n=3).vote(d)
        assert result.consensus == "REJECTED"
        assert result.passed is False

    def test_panel_sizes(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        for n in [3, 5, 7, 9]:
            result = ValidatorPanel(n=n).vote(poe.to_dict())
            assert result.total_validators == n
            assert result.consensus == "APPROVED"

    def test_all_validators_reject_fraud(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        d       = poe.to_dict(); d["step_count"] = -1
        result  = ValidatorPanel(n=5).vote(d)
        assert result.reject_count == 5
        assert result.approve_count == 0

    def test_vote_objects_have_correct_fields(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        result  = ValidatorPanel(n=3).vote(poe.to_dict())
        for vote in result.votes:
            assert hasattr(vote, "validator_id")
            assert hasattr(vote, "approved")
            assert hasattr(vote, "signals")
            assert hasattr(vote, "verdict")
            assert hasattr(vote, "hash_verified")

    def test_consensus_string_values(self):
        from aaip.validators import ValidatorPanel
        poe, _ = make_honest_poe()
        r1 = ValidatorPanel(n=3).vote(poe.to_dict())
        assert r1.consensus in ("APPROVED", "REJECTED")
        d = poe.to_dict(); d["output_hash"] = "cc" * 32
        r2 = ValidatorPanel(n=3).vote(d)
        assert r2.consensus == "REJECTED"
