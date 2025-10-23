#!/usr/bin/env python3
import os
import sys
import json
import httpx

"""
Updates HNS TXT dnslink via hsd/Bob JSON-RPC (RPC mode)
or prints the records for manual mode.

Env:
  MODE=rpc|manual
  HNS_RPC_URL=http://127.0.0.1:12037
  HNS_RPC_AUTH=user:pass   (if needed)
  HNS_NAME=yourname/
  S5_CID=...
  IPFS_CID=...             (optional)
"""

MODE = os.getenv("MODE", "manual").lower()
HNS_RPC_URL = os.getenv("HNS_RPC_URL", "http://127.0.0.1:12037")
HNS_RPC_AUTH = os.getenv("HNS_RPC_AUTH", "")
HNS_NAME = os.getenv("HNS_NAME", "").strip()
S5_CID = os.getenv("S5_CID", "").strip()
IPFS_CID = os.getenv("IPFS_CID", "").strip()

def make_dnslink_txts() -> list[str]:
    txts = []
    if S5_CID:
        txts.append(f"dnslink=/s5/{S5_CID}")
    if IPFS_CID:
        txts.append(f"dnslink=/ipfs/{IPFS_CID}")
    if not txts:
        raise SystemExit("No CIDs provided.")
    return txts

def rpc_headers():
    headers = {"Content-Type": "application/json"}
    if HNS_RPC_AUTH:
        import base64
        headers["Authorization"] = "Basic " + base64.b64encode(HNS_RPC_AUTH.encode()).decode()
    return headers

async def rpc_set_txt(name: str, txts: list[str]):
    """
    This is a placeholder. hsd/Bob wallet RPCs vary by setup.
    Often you'll update the zone resource via wallet RPC or sign and send a NAME_UPDATE.
    For safety, we present a stub that raises, and you can adapt to your node.
    """
    raise RuntimeError("RPC mode not implemented for your hsd/Bob setup. Provide exact RPC and auth to enable.")

def main():
    if MODE == "manual":
        txts = make_dnslink_txts()
        print("# Add the following TXT records to your HNS zone:")
        for t in txts:
            print("TXT", t)
        print("\n# Example (BIND-style):")
        for t in txts:
            print(f'@  TXT  "{t}"')
        return

    if MODE == "rpc":
        if not HNS_NAME:
            print("[ERROR] HNS_NAME is required for RPC mode")
            sys.exit(2)
        txts = make_dnslink_txts()
        # Implement your RPC here (wallet auth, resource edit, update, broadcast)
        print("[ERROR] RPC flow not implemented in this template. Adapt `rpc_set_txt` to your node.")
        sys.exit(2)

if __name__ == "__main__":
    if MODE not in ("manual", "rpc"):
        print("[ERROR] MODE must be manual or rpc")
        sys.exit(2)
    main()
