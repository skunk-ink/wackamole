"""                      _..._ ___
                       .:::::::.  `"-._.-''.
                  ,   /:::::::::\     ':    \                     _._
                  \:-::::::::::::\     :.    |     /|.-'         /:::\ 
                   \::::::::\:::::|    ':     |   |  /           |:::|
                    `:::::::|:::::\     ':    |   `\ |    __     |\::/\ 
                       -:::-|::::::|    ':    |  .`\ .\_.'  `.__/      |
                            |::::::\    ':.   |   \ ';:: /.-._   ,    /
                            |:::::::|    :.   /   ,`\;:: \'./0)  |_.-/
                            ;:::::::|    ':  |    \.`;::.   ``   |  |
                             \::::::/    :'  /     _\::::'      /  /
                              \::::|   :'   /    ,=:;::/           |
                               \:::|   :'  |    (='` //        /   |
                                \::\   `:  /     '--' |       /\   |
  GITHUB.COM/SKUNK-INK           \:::.  `:_|.-"`"-.    \__.-'/::\  |
░▒█▀▀▀█░▒█░▄▀░▒█░▒█░▒█▄░▒█░▒█░▄▀  '::::.:::...:::. '.       /:::|  |
░░▀▀▀▄▄░▒█▀▄░░▒█░▒█░▒█▒█▒█░▒█▀▄░   '::/::::::::::::. '-.__.:::::|  |
░▒█▄▄▄█░▒█░▒█░░▀▄▄▀░▒█░░▀█░▒█░▒█     |::::::::::::\::..../::::::| /
                                     |:::::::::::::|::::/::::::://
              ░▒▀█▀░▒█▄░▒█░▒█░▄▀     \:::::::::::::|'::/::::::::/
              ░░▒█░░▒█▒█▒█░▒█▀▄░     /\::::::::::::/  /:::::::/:|
              ░▒▄█▄░▒█░░▀█░▒█░▒█    |::';:::::::::/   |::::::/::;
                     WACK-A-MOLE    |:::/`-:::::;;-._ |:::::/::/
                       PUBLISHER    |:::|  `-::::\   `|::::/::/
                                    |:::|     \:::\   \:::/::/
                                   /:::/       \:::\   \:/\:/
                                  (_::/         \:::;__ \\_\\___
                                  (_:/           \::):):)\:::):):)
                                   `"             `""""`  `""""""`      
"""

# publish_static.py
# Upload a static site (zipped) to a remote indexd node on Sia.
# Adds CLI flags for erasure coding + concurrency and smarter defaults by file size.

import asyncio
from sys import stdin
import argparse, os, sys, json, time, webbrowser, tempfile, zipfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Ensure we can import the generated indexd_ffi module + shared library
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from indexd_ffi import (
    generate_recovery_phrase, AppKey, AppMeta, Sdk,
    UploadOptions, set_logger, Logger
)

# Simple console logger (optional)
class PrintLogger(Logger):
    def debug(self, msg): print("DEBUG", msg)
    def info(self, msg): print("INFO", msg)
    def warning(self, msg): print("WARN", msg)
    def error(self, msg): print("ERROR", msg)

def zip_directory(src_dir: Path) -> Path:
    assert src_dir.is_dir(), f"{src_dir} is not a directory"
    tmp = Path(tempfile.gettempdir()) / f"site-{int(time.time())}.zip"
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(src_dir.rglob("*")):
            if p.is_file():
                z.write(p, arcname=str(p.relative_to(src_dir)))
    return tmp

def human_bytes(n: int) -> str:
    for unit in ['B','KiB','MiB','GiB','TiB','PiB']:
        if n < 1024 or unit == 'PiB':
            return f"{n:.1f} {unit}"
        n /= 1024.0

async def maybe_await(value):
    """Await the value if it's a coroutine; otherwise return it as-is."""
    return await value if asyncio.iscoroutine(value) else value

async def main():
    # Windows compatibility for some async networking stacks
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Upload a static site (zipped) to Sia via remote indexd.")
    parser.add_argument("--indexd", dest="indexd_url", default=os.getenv("INDEXD_URL"), required=False,
                        help="Remote indexd URL, e.g. https://indexd.example.com")
    parser.add_argument("--site", dest="site_dir", default="website",
                        help="Path to built site directory (default: website)")
    parser.add_argument("--out", dest="out_manifest", default="manifest.json",
                        help="Where to write manifest (default: manifest.json)")
    parser.add_argument("--app-name", default=os.getenv("APP_NAME", "My Static Site"))
    parser.add_argument("--app-desc", default=os.getenv("APP_DESC", "Publishes static sites to Sia via indexd"))
    parser.add_argument("--service-url", default=os.getenv("SERVICE_URL", "https://example.com"))
    parser.add_argument("--logo-url", default=os.getenv("LOGO_URL"))
    parser.add_argument("--callback-url", default=os.getenv("CALLBACK_URL"))
    parser.add_argument("--share-days", type=int, default=365,
                        help="How long the share link is valid (default: 365)")

    # New knobs
    parser.add_argument("--data", type=int, default=None,
                        help="Number of data shards (overrides smart defaults)")
    parser.add_argument("--parity", type=int, default=None,
                        help="Number of parity shards (overrides smart defaults)")
    parser.add_argument("--inflight", type=int, default=6,
                        help="Max shards uploading in parallel (default: 6)")
    parser.add_argument("--chunk-mib", type=int, default=1,
                        help="Upload chunk size in MiB (default: 1)")

    args = parser.parse_args()

    if not args.indexd_url:
        print("ERROR: --indexd (or INDEXD_URL env) is required.")
        sys.exit(2)

    set_logger(PrintLogger(), "INFO")

    # Identity input (simple interactive flow used in your version)
    print("Enter mnemonic (or leave empty to generate new):")
    mnemonic = stdin.readline().strip()
    if not mnemonic:
        mnemonic = generate_recovery_phrase()
    print("\nmnemonic:", mnemonic)

    # Fixed app id for reproducibility (matches your edited script)
    app_id = b'\x01' * 32
    app_key = AppKey(mnemonic, app_id)
    sdk = Sdk(args.indexd_url, app_key)

    # One-time connect/approve flow
    if not await sdk.connected():
        print("\nRequesting app authorization…")
        resp = await sdk.request_app_connection(AppMeta(
            name=args.app_name,
            description=args.app_desc,
            service_url=args.service_url,
            logo_url=args.logo_url if args.logo_url else None,
            callback_url=args.callback_url if args.callback_url else None
        ))
        print("Open this URL to approve access:\n", resp.response_url)
        try:
            webbrowser.open(resp.response_url)
        except Exception:
            pass
        ok = await sdk.wait_for_connect(resp)
        if not ok:
            print("Authorization was not granted.")
            sys.exit(1)
        print("App authorized.")

    # Prepare the zip
    site_dir = Path(args.site_dir).resolve()
    zip_path = zip_directory(site_dir)
    size = zip_path.stat().st_size
    print(f"\nCreated zip: {zip_path} ({human_bytes(size)})")

    # Smarter erasure-coding defaults by size, unless overridden
    if args.data is None or args.parity is None:
        if size <= 8 * 1024 * 1024:          # <= 8 MiB
            data_shards, parity_shards = 3, 9
        elif size <= 64 * 1024 * 1024:       # <= 64 MiB
            data_shards, parity_shards = 6, 12
        else:
            data_shards, parity_shards = 10, 20
    else:
        data_shards, parity_shards = args.data, args.parity

    print(f"Using erasure coding: data={data_shards}, parity={parity_shards}, inflight={args.inflight}")

    # Metadata
    metadata = {
        "type": "zip",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "original_dir": str(site_dir),
        "filename": zip_path.name,
        "content": "static-website",
        "hint": "Serve by unzipping in-memory or via ranged reads"
    }
    metadata_bytes = json.dumps(metadata).encode("utf-8")

    # Start upload
    print("Uploading to Sia via indexd…")
    up = await sdk.upload(UploadOptions(
        max_inflight=args.inflight,
        data_shards=data_shards,
        parity_shards=parity_shards,
        metadata=metadata_bytes,
        progress_callback=None
    ))

    sent = 0
    chunk_size = max(1, args.chunk_mib) * 1024 * 1024
    with open(zip_path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            await up.write(chunk)
            sent += len(chunk)
            pct = (sent / size) * 100 if size else 100.0
            print(f"\r{human_bytes(sent)} / {human_bytes(size)} ({pct:.1f}%)", end="", flush=True)
    print()
    obj = await up.finalize()

    # Signed share URL (works for both sync or async implementations)
    valid_until = datetime.now(timezone.utc) + timedelta(days=args.share_days)
    signed_url = await maybe_await(sdk.share_object(obj, valid_until))

    # Try to include a sealed id if available (works across sync/async shapes)
    sealed_id = None
    try:
        if hasattr(obj, "seal"):
            sealed = await maybe_await(obj.seal(app_key))
            sealed_id = getattr(sealed, "id", None)
    except Exception:
        pass

    manifest = {
        "indexd_url": args.indexd_url,
        "sealed_object": {"id": sealed_id} if sealed_id else {},
        "share_url": signed_url,
        "valid_until": valid_until.isoformat(),
        "zip_size_bytes": size,
        "metadata": metadata,
        "erasure_coding": {
            "data_shards": data_shards,
            "parity_shards": parity_shards,
            "max_inflight": args.inflight,
            "chunk_mib": args.chunk_mib,
        }
    }
    Path(args.out_manifest).write_text(json.dumps(manifest, indent=2))
    print("\n✅ Upload complete.")
    print("Share URL (give this to a gateway):")
    print(signed_url)
    print(f"\nWrote manifest to: {args.out_manifest}")

if __name__ == "__main__":
    asyncio.run(main())
