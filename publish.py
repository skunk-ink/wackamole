#!/usr/bin/env python3

# publish_static.py
# Upload a static site (zipped) to a remote indexd node on Sia.

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

import asyncio
from sys import stdin
import argparse, os, sys, json, time, webbrowser, tempfile, zipfile, subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone

# Ensure we can import the generated indexd_ffi module + shared library
sys.path.insert(0, str(Path(__file__).parent.resolve()))

from indexd_ffi import (
    generate_recovery_phrase, AppKey, AppMeta, Sdk,
    UploadOptions, set_logger, Logger
)

try:
    from dotenv import load_dotenv
    load_dotenv('.env')
except Exception:
    pass

class PrintLogger(Logger):
    def debug(self, msg): print("DEBUG", msg)
    def info(self, msg): print("INFO", msg)
    def warning(self, msg): print("WARN", msg)
    def error(self, msg): print("ERROR", msg)

def _parse_app_id(value) -> bytes:
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
        if len(b) != 32:
            raise ValueError(f"APP_ID must be 32 bytes, got {len(b)}")
        return b
    if isinstance(value, str):
        s = value.strip()
        # hex path
        h = s[2:] if s.startswith(("0x","0X")) else s
        try:
            if len(h) == 64 and all(c in "0123456789abcdefABCDEF" for c in h):
                return bytes.fromhex(h)
        except Exception:
            pass
        # base64 path
        import base64
        for decoder in (base64.b64decode, base64.urlsafe_b64decode):
            try:
                b = decoder(s + "===")
                if len(b) == 32:
                    return b
            except Exception:
                pass
        # integer path
        if s.isdigit():
            n = int(s, 10)
            return n.to_bytes(32, "big", signed=False)
    raise ValueError("Could not parse APP_ID into 32 bytes. Use 64-hex or base64.")

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
    return await value if asyncio.iscoroutine(value) else value

PLACEHOLDER_NAME = "PLACE STATIC SITE HERE.txt"

def _site_flag_was_passed(argv: list[str]) -> bool:
    # Detect explicit --site usage (either "--site" then value OR "--site=value")
    for a in argv:
        if a == "--site" or a.startswith("--site="):
            return True
    return False

def _dir_is_empty_or_only_placeholder(site_dir: Path) -> bool:
    if not site_dir.exists():
        return True
    entries = []
    for p in site_dir.iterdir():
        # Ignore hidden files/dirs like .DS_Store, .gitkeep, etc.
        if p.name.startswith("."):
            continue
        # Keep everything else
        entries.append(p.name)
    if not entries:
        return True
    # If there’s exactly one non-hidden entry and it’s the placeholder, treat as empty
    if len(entries) == 1 and entries[0] == PLACEHOLDER_NAME:
        return True
    return False

def _run_demo_builder(site_dir: Path):
    """
    Try to run scripts/build_demo_site.py (preferred).
    If not found, fall back to a minimal inline generator.
    """
    root = Path(__file__).parent.resolve()
    candidates = [
        root / "scripts" / "build_demo_website.py",
    ]
    for script in candidates:
        if script.exists():
            print(f"Generating demo site via: {script} --dir {site_dir}")
            # Use the current Python executable for maximum cross-platform compatibility.
            subprocess.check_call([sys.executable, str(script), "--dir", str(site_dir), "--force"])
            return

    # Fallback (shouldn’t happen in your repo): create a tiny demo
    print("build_demo_site.py not found — creating a minimal demo site inline.")
    (site_dir / "css").mkdir(parents=True, exist_ok=True)
    (site_dir / "js").mkdir(parents=True, exist_ok=True)
    (site_dir / "assets").mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(
        "<!doctype html><meta charset='utf-8'><title>Demo</title>"
        "<h1>Wack-A-Mole Demo</h1><p>Replace this with your site.</p>", encoding="utf-8"
    )
    (site_dir / "css" / "styles.css").write_text("body{font-family:system-ui}", encoding="utf-8")
    (site_dir / "js" / "app.js").write_text("console.log('demo');", encoding="utf-8")

async def main():
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Upload a static site (zipped) to Sia via remote indexd.")
    parser.add_argument("--indexd", dest="indexd_url", default=os.getenv("INDEXD_URL"), required=False)
    parser.add_argument("--site", dest="site_dir", default="website")
    parser.add_argument("--out", dest="out_manifest", default="manifest.json")
    parser.add_argument("--app-name", default=os.getenv("APP_NAME", "My Static Site"))
    parser.add_argument("--app-desc", default=os.getenv("APP_DESC", "Publishes static sites to Sia via indexd"))
    parser.add_argument("--service-url", default=os.getenv("SERVICE_URL", "https://example.com"))
    parser.add_argument("--logo-url", default=os.getenv("LOGO_URL"))
    parser.add_argument("--callback-url", default=os.getenv("CALLBACK_URL"))
    parser.add_argument("--share-days", type=int, default=365)
    parser.add_argument("--app-id", dest="app_id", default=os.getenv("APP_ID"))
    parser.add_argument("--seed-phrase", dest="seed_phrase", default=os.getenv("SEED_PHRASE"))
    parser.add_argument("--data", type=int, default=None)
    parser.add_argument("--parity", type=int, default=None)
    parser.add_argument("--inflight", type=int, default=6)
    parser.add_argument("--chunk-mib", type=int, default=1)
    args = parser.parse_args()

    site_flag_present = _site_flag_was_passed(sys.argv[1:])
    site_dir = Path(args.site_dir).resolve()

    if not site_flag_present and site_dir.name == "website":
        # Only auto-build if user didn't explicitly choose a different --site
        if _dir_is_empty_or_only_placeholder(site_dir):
            print(f"ℹ️  No custom site detected in {site_dir} (empty or only '{PLACEHOLDER_NAME}').")
            _run_demo_builder(site_dir)
        else:
            # If the placeholder file exists alongside other files, quietly ignore it.
            placeholder = site_dir / PLACEHOLDER_NAME
            if placeholder.exists():
                try:
                    placeholder.unlink()
                    print(f"Removed placeholder file: {placeholder}")
                except Exception:
                    pass

    if not args.indexd_url:
        print("ERROR: --indexd (or INDEXD_URL env) is required.")
        sys.exit(2)

    set_logger(PrintLogger(), "INFO")

    if not args.seed_phrase:
        print("Enter mnemonic (or leave empty to generate new):")
        mnemonic = stdin.readline().strip()
        if not mnemonic:
            mnemonic = generate_recovery_phrase()
        print("\nmnemonic:", mnemonic)
    else:
        mnemonic = args.seed_phrase

    if not args.app_id:
        app_id = b'\x01' * 32
    else:
        app_id = args.app_id

    try:
        app_id_bytes = _parse_app_id(app_id)
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(2)

    app_key = AppKey(mnemonic, app_id_bytes)
    sdk = Sdk(args.indexd_url, app_key)

    if not await sdk.connected():
        print("\nRequesting app authorization…")
        resp = await sdk.request_app_connection(AppMeta(
            name=args.app_name,
            description=args.app_desc,
            service_url=args.service_url,
            logo_url=args.logo_url or None,
            callback_url=args.callback_url or None
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

    # Prepare the zipped site archive
    # (site_dir may have been auto-populated above)
    zip_path = zip_directory(site_dir)
    size = zip_path.stat().st_size
    print(f"\nCreated zip: {zip_path} ({human_bytes(size)})")

    # Erasure-coding defaults by size, unless overridden
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

    # Signed share URL
    valid_until = datetime.now(timezone.utc) + timedelta(days=args.share_days)
    signed_url = await maybe_await(sdk.share_object(obj, valid_until))

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