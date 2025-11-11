#!/usr/bin/env python3
import argparse, json, pathlib, sys

def main():
    p = argparse.ArgumentParser(description="Safely update manifest.json fields.")
    p.add_argument("--manifest", required=True, help="Path to manifest.json")
    p.add_argument("--share-url", dest="share_url", default=None, help="Value for share_url")
    p.add_argument("--indexd-url", dest="indexd_url", default=None, help="Value for indexd_url")
    args = p.parse_args()

    mpath = pathlib.Path(args.manifest)
    # Load (or initialize)
    try:
        data = json.loads(mpath.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}

    changed = False
    if args.share_url is not None and args.share_url.strip():
        data["share_url"] = args.share_url.strip()
        changed = True
    if args.indexd_url is not None and args.indexd_url.strip():
        data["indexd_url"] = args.indexd_url.strip()
        changed = True

    # Ensure file exists even if nothing changed
    if (not mpath.exists()) or changed:
        mpath.parent.mkdir(parents=True, exist_ok=True)
        mpath.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # Console feedback
    print("Wrote:", mpath)
    s = data.get("share_url")
    print("share_url:", "<unchanged>" if s is None else (s[:100] + ("…" if len(s) > 100 else "")))
    print("indexd_url:", data.get("indexd_url", "<unchanged>"))

if __name__ == "__main__":
    sys.exit(main())
