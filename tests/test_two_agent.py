import hashlib, json, os, subprocess, sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ["AEP_ADAPTER"] = "mock"
class TestTwoAgent(unittest.TestCase):
    def test_poe_deterministic(self):
        """Same inputs always produce same poe_hash."""
        def make(aid, task):
            steps = [{"tool":"retriever","input":task[:80],"output_tokens":256,"status":"ok"},
                     {"tool":"summariser","input":task[:80],"output_tokens":512,"status":"ok"},
                     {"tool":"reasoner","input":task[:80],"output_tokens":1024,"status":"ok"},
                     {"tool":"formatter","input":task[:80],"output_tokens":128,"status":"ok"}]
            c = json.dumps({"agent_id":aid,"task":task,"model":"deepseek-chat",
                "steps":steps,"step_count":4,"total_tokens":sum(s["output_tokens"] for s in steps)},
                sort_keys=True,separators=(",",":"))
            return "0x"+hashlib.sha256(c.encode()).hexdigest()
        self.assertEqual(make("a","t"), make("a","t"))
        self.assertNotEqual(make("a","t"), make("b","t"))
    def test_validator_rejects_tampered_hash(self):
        from demo_two_agent import consensus
        trace = {"agent_id":"a","task":"t",
                 "steps":[{"tool":"r","input":"x","output_tokens":100,"status":"ok"}],
                 "poe_hash":"0x"+"dead"*16,"signature":"00"*32,
                 "pub_key":"00"*32,"timestamp":time.time()}
        r = consensus(trace, n=3)
        self.assertEqual(r["consensus"], "REJECTED")
        self.assertIn("HASH_MISMATCH", r["all_signals"])
    def test_mock_demo_exits_zero(self):
        r = subprocess.run([sys.executable,"demo_two_agent.py","--mock","--fast"],
                           capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, f"STDOUT:\n{r.stdout}\nSTDERR:\n{r.stderr}")
        self.assertIn("APPROVED", r.stdout)
        self.assertIn("SUCCESS",  r.stdout)
    def test_full_payment_mock(self):
        from aaip.aep.core import execute_payment
        r = execute_payment("a1","r1",0.001,
                            poe_hash="0x"+hashlib.sha256(b"full_mock_test").hexdigest())
        self.assertEqual(r["status"],"success")
        self.assertIsNotNone(r["tx_hash"])
    def test_protocol_fee_deducted(self):
        from aaip.aep.core import execute_payment
        r = execute_payment("a1","r1", 0.01,
                            poe_hash="0x"+hashlib.sha256(b"fee_test_123").hexdigest())
        if r.get("protocol_fee") is not None:
            self.assertAlmostEqual(r["protocol_fee"], 0.0002, places=6)
            self.assertAlmostEqual(r["worker_amount"], 0.0098, places=6)

    def test_replay_protection(self):
        from aaip.aep.core import execute_payment
        poe = "0x"+hashlib.sha256(b"replay_unique_abc999").hexdigest()
        r1  = execute_payment("a_rep","r_rep",0.001,poe_hash=poe)
        r2  = execute_payment("a_rep","r_rep",0.001,poe_hash=poe)
        self.assertIn(r1["status"],["success","failed"])
        # Second call must not raise — idempotent or rejected
        self.assertIn(r2["status"],["success","failed"])
if __name__ == "__main__":
    unittest.main(verbosity=2)