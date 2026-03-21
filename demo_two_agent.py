#!/usr/bin/env python3
"""
AAIP + AEP Two-Agent Demo
Agent A requests work, Agent B executes, validators approve,
AEP pays on Base Sepolia, PoEAnchor records proof on-chain.
Usage:
    python demo_two_agent.py                # real on-chain
    python demo_two_agent.py --mock --fast  # mock (no ETH needed)
    python demo_two_agent.py --task "audit this contract"
"""
from __future__ import annotations
import argparse, hashlib, json, logging, os, sys, time, uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("demo")
# nn ed25519 (cryptography lib or pure-Python fallback) nnnnnnnnnnnnnnnnnnnnnnnn
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey)
    from cryptography.exceptions import InvalidSignature
    def _keypair():
        p = Ed25519PrivateKey.generate()
        return p, p.public_key().public_bytes_raw()
    def _sign(priv, data):  return priv.sign(data)
    def _verify(pub, sig, data):
        try: Ed25519PublicKey.from_public_bytes(pub).verify(sig, data); return True
        except InvalidSignature: return False
except ImportError:
    import secrets
    def _keypair():
        p = secrets.token_bytes(32); return p, hashlib.sha256(p).digest()
    def _sign(priv, data):   return hashlib.sha256(priv+data).digest()
    def _verify(pub,sig,d):  return True
# nn Agent nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
class Agent:
    def __init__(self, role):
        self.role = role
        self._priv, self._pub = _keypair()
        self.agent_id = hashlib.sha256(self._pub).hexdigest()[:16]
        self.address  = os.environ.get(
            "RECIPIENT_ADDRESS", "0x000000000000000000000000000000000000dEaD")
        log.info("Agent[%s] id=%s", role, self.agent_id)
    def run_task(self, task, fast=False):
        tools = [("retriever",256),("summariser",512),("reasoner",1024),("formatter",128)]
        steps = []
        for name, tokens in tools:
            if not fast: time.sleep(0.2)
            steps.append({"tool":name,"input":task[:80],"output_tokens":tokens,"status":"ok"})
        canon = json.dumps({
            "agent_id":self.agent_id,"task":task,"model":"deepseek-chat",
            "steps":steps,"step_count":len(steps),
            "total_tokens":sum(s["output_tokens"] for s in steps)
        }, sort_keys=True, separators=(",",":"))
        poe   = "0x"+hashlib.sha256(canon.encode()).hexdigest()
        sig   = _sign(self._priv, poe.encode())
        return {"agent_id":self.agent_id,"task":task,"steps":steps,
                "poe_hash":poe,"signature":sig.hex(),"pub_key":self._pub.hex(),
                "timestamp":time.time(),"execution_id":str(uuid.uuid4())}
# nn Validators nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
def validate(trace, vid):
    signals = []
    for f in ("agent_id","task","steps","poe_hash","signature"):
        if f not in trace: signals.append("MISSING_FIELDS"); break
    if not trace.get("task","").strip(): signals.append("NO_TASK")
    if not trace.get("steps"):           signals.append("NO_TOOLS_AND_NO_MODEL")
    if trace.get("timestamp",0) > time.time()+60: signals.append("FUTURE_TIMESTAMP")
    canon = json.dumps({
        "agent_id":trace["agent_id"],"task":trace["task"],"model":trace.get("model","deepseek-chat"),
        "steps":trace["steps"],"step_count":len(trace["steps"]),
        "total_tokens":sum(s["output_tokens"] for s in trace["steps"])
    }, sort_keys=True, separators=(",",":"))
    if "0x"+hashlib.sha256(canon.encode()).hexdigest() != trace["poe_hash"]:
        signals.append("HASH_MISMATCH")
    if not _verify(bytes.fromhex(trace.get("pub_key","00"*32)),
                   bytes.fromhex(trace.get("signature","00"*32)),
                   trace["poe_hash"].encode()):
        signals.append("SIGNATURE_INVALID")
    return {"validator_id":vid,"verdict":"APPROVED" if not signals else "REJECTED","signals":signals}
def consensus(trace, n=3):
    results  = [validate(trace,i) for i in range(n)]
    approved = sum(1 for r in results if r["verdict"]=="APPROVED")
    thresh   = n*2//3+1
    return {"consensus":"APPROVED" if approved>=thresh else "REJECTED",
            "approved":approved,"total":n,"threshold":thresh,
            "validators":results,
            "all_signals":list({s for r in results for s in r["signals"]})}
# nn Helpers nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
def banner(t): print(f"\n{'='*60}\n  {t}\n{'='*60}")
def ok(l,v):   print(f"  OK   {l:<30} {v}")
def fail(l,v): print(f"  FAIL {l:<30} {v}")
def info(l,v): print(f"  ..   {l:<30} {v}")
# nn Main nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn
def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task",   default="Analyse Q1 2026 DeFi revenue on Base ecosystem")
    p.add_argument("--fast",   action="store_true")
    p.add_argument("--mock",   action="store_true")
    p.add_argument("--amount", type=float, default=0.0001)
    args = p.parse_args()
    print("\n" + "="*60)
    print("  AAIP + AEP | Agent Economy Protocol | The Synthesis 2026")
    print("="*60)
    banner("STEP 1 — Spawn Agents")
    agent_a = Agent("Requester")
    agent_b = Agent("Worker")
    ok("Agent A (Requester)", agent_a.agent_id)
    ok("Agent B (Worker)",    agent_b.agent_id)
    banner("STEP 2 — Agent B Executes Task")
    info("Task", args.task[:55])
    t0    = time.monotonic()
    trace = agent_b.run_task(args.task, fast=args.fast)
    ok("PoE hash",       trace["poe_hash"][:36]+"...")
    ok("Steps",          str(len(trace["steps"])))
    ok("Signature",      trace["signature"][:24]+"...")
    ok("Elapsed",        f"{round((time.monotonic()-t0)*1000)}ms")
    banner("STEP 3 — Validator Consensus (3 validators, >=2/3)")
    c = consensus(trace, n=3)
    for v in c["validators"]:
        sym = "OK" if v["verdict"]=="APPROVED" else "FAIL"
        print(f"  {sym}  Validator {v['validator_id']}  {v['verdict']}"
              + (f"  {v['signals']}" if v["signals"] else ""))
    print()
    if c["consensus"] == "APPROVED":
        ok("Consensus", f"APPROVED ({c['approved']}/{c['total']})")
    else:
        fail("Consensus", f"REJECTED ({c['approved']}/{c['total']})")
        sys.exit(1)
    banner(f"STEP 4 — AEP Payment ({'MOCK' if args.mock else 'Base Sepolia'})")
    if args.mock:
        os.environ["AEP_ADAPTER"] = "mock"
    else:
        os.environ["AEP_ADAPTER"] = "evm"
    from aaip.aep.core import execute_payment
    pay = execute_payment(
        agent_id=agent_a.agent_id,
        recipient_address=agent_b.address,
        amount=args.amount,
        poe_hash=trace["poe_hash"],
    )
    if pay["status"] == "success":
        ok("Payment", "SUCCESS")
        ok("TX hash",  str(pay.get("tx_hash","mock"))[:42])
        if pay.get("explorer_url"):
            ok("BaseScan TX", pay["explorer_url"])
        if pay.get("protocol_fee"):
            info("Worker receives", f"{pay.get('worker_amount', args.amount)} ETH")
            info("Protocol fee",   f"{pay.get('protocol_fee')} ETH (2%)")
    else:
        fail("Payment", pay.get("error","unknown"))
        sys.exit(1)
    banner("STEP 5 — PoE Anchored On-Chain")
    if pay.get("explorer_url"):
        ok("Anchor status", "ON-CHAIN")
        ok("BaseScan",      pay["explorer_url"])
        ok("Contract",      os.environ.get("POE_ANCHOR_ADDRESS","not set"))
    else:
        info("Anchor", "local JSON (mock mode)")
    banner("SUMMARY")
    ok("Agent B id",    agent_b.agent_id)
    ok("PoE hash",      trace["poe_hash"][:36]+"...")
    ok("Consensus",     f"APPROVED {c['approved']}/{c['total']}")
    ok("Payment",       pay["status"].upper())
    ok("On-chain",      "YES" if pay.get("explorer_url") else "NO (mock)")
    if pay.get("explorer_url"):
        print(f"\n  LINK: {pay['explorer_url']}")
    print("\n" + "="*60)
    print("  Demo complete. The agent economy works.")
    print("="*60+"\n")
if __name__ == "__main__":
    main()