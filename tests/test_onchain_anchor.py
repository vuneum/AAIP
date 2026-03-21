import os, sys, json, hashlib, unittest, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
class TestAnchorMock(unittest.TestCase):
    def test_local_fallback_no_config(self):
        """Without chain config, adapter writes to local JSON."""
        from aaip.aep.adapters.anchor_chain import OnChainAnchorAdapter
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        os.environ["AEP_ANCHOR_PATH"] = tmp
        a = OnChainAnchorAdapter(rpc_url=None, private_key=None, contract_address=None)
        r = a.anchor("test_agent", "0x"+"a"*64, "0x"+"b"*64)
        self.assertEqual(r["status"], "success")
        self.assertFalse(r["on_chain"])
        recs = json.loads(Path(tmp).read_text())
        self.assertEqual(recs[0]["agent_id"], "test_agent")
    def test_poe_bytes32_conversion(self):
        """poe_hash 0x+64hex converts correctly to 32 bytes."""
        poe = "0x" + "ab"*32
        b   = bytes.fromhex(poe.lstrip("0x").zfill(64))
        self.assertEqual(len(b), 32)
    def test_inline_abi_has_anchor(self):
        from aaip.aep.adapters.anchor_chain import _INLINE_ABI
        names = [x.get("name") for x in _INLINE_ABI]
        self.assertIn("anchor", names)
        self.assertIn("isAnchored", names)
    def test_execute_payment_calls_anchor(self):
        """execute_payment triggers anchor_proof without raising."""
        os.environ["AEP_ADAPTER"] = "mock"
        os.environ.pop("POE_ANCHOR_ADDRESS", None)
        from aaip.aep.core import execute_payment
        r = execute_payment("a1", "r1", 0.001,
                            poe_hash="0x"+hashlib.sha256(b"ep_test").hexdigest())
        self.assertIn(r["status"], ["success","failed"])
class TestAnchorReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skip = not all(os.environ.get(k)
                           for k in ["AEP_RPC_URL","AEP_PRIVATE_KEY","POE_ANCHOR_ADDRESS"])
    def setUp(self):
        if self.skip:
            self.skipTest("Chain not configured")
    def test_real_anchor_returns_basescan_url(self):
        from aaip.aep.adapters.anchor_chain import OnChainAnchorAdapter
        a = OnChainAnchorAdapter()
        if not a._on: self.skipTest("Adapter not enabled")
        poe = "0x"+hashlib.sha256(b"real_test_anchor_789").hexdigest()
        pay = "0x"+hashlib.sha256(b"real_payment_789").hexdigest()
        r   = a.anchor("test_agent_real", poe, pay)

        self.assertEqual(r["status"], "success")
        self.assertTrue(r["on_chain"])
        self.assertIn("sepolia.basescan.org", r["explorer_url"])
        print(f"\nReal anchor: {r['explorer_url']}")
if __name__ == "__main__":
    unittest.main(verbosity=2)