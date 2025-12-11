#!/usr/bin/env python3

# gateway.py — serve a static site from an indexd *shared* URL (decrypts via SDK),
# with .env-managed MNEMONIC and APP_ID. Works with various handle shapes.

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
                         GATEWAY    |:::|  `-::::\   `|::::/::/
                                    |:::|     \:::\   \:::/::/
                                   /:::/       \:::\   \:/\:/
                                  (_::/         \:::;__ \\_\\___
                                  (_:/           \::):):)\:::):):)
                                   `"             `""""`  `""""""`      
"""

import argparse, webbrowser
import asyncio
import io
import os
import posixpath
import secrets
import sys
import zipfile
import json
from sys import stdin
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
import uvicorn

try:
    import magic
except Exception:
    magic = None
from dotenv import set_key
try:
    from dotenv import load_dotenv
    load_dotenv('.env')
except Exception:
    pass

from indexd_ffi import (
    Builder, Sdk, AppKey, AppMeta, Logger,
    DownloadOptions, generate_recovery_phrase, set_logger
)

class PrintLogger(Logger):
    def debug(self, msg): print("DEBUG", msg)
    def info(self, msg): print("INFO", msg)
    def warning(self, msg): print("WARN", msg)
    def error(self, msg): print("ERROR", msg)

def _load_app_key() -> bytes | None:
    try:
        with open("app_key.bin", "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return None

    # AppKey requires exactly 32 bytes. If it's not, ignore and re-onboard.
    if len(data) != 32:
        print(f"\nStored App Key has invalid length ({len(data)} bytes). Ignoring and re-onboarding.")
        return None

    return data

def _save_app_key(data: bytes) -> None:
    with open("app_key.bin", "wb") as f:
        f.write(data)

async def maybe_await(x):
    return await x if asyncio.iscoroutine(x) else x

def _guess_mime(name: str) -> str:
    low = name.lower()
    if low.endswith((".html", ".htm")): return "text/html; charset=utf-8"
    if low.endswith(".css"):            return "text/css; charset=utf-8"
    if low.endswith(".js"):             return "application/javascript; charset=utf-8"
    if low.endswith(".json"):           return "application/json; charset=utf-8"
    if low.endswith(".svg"):            return "image/svg+xml"
    if low.endswith(".png"):            return "image/png"
    if low.endswith((".jpg",".jpeg")):  return "image/jpeg"
    if low.endswith(".gif"):            return "image/gif"
    if low.endswith(".webp"):           return "image/webp"
    if low.endswith(".ico"):            return "image/x-icon"
    if magic:
        try:
            m = magic.Magic(mime=True)
            return m.from_buffer(b"") or "application/octet-stream"
        except Exception:
            pass
    return "application/octet-stream"

def _norm_path(url_path: str) -> str:
    p = PurePosixPath("/" + url_path).as_posix()
    p = posixpath.normpath(p)
    if p.startswith("/"): p = p[1:]
    return "" if p == "." else p

def _extract_indexd_base(share_url: str) -> str:
    u = urlparse(share_url)
    return f"{u.scheme}://{u.netloc}"

def _load_or_prompt_env(env_path: str = ".env") -> tuple[str, bytes]:
    recovery_phrase = os.getenv("RECOVERY_PHRASE")
    if not recovery_phrase:
        print("Enter recovery phrase (type `seed` to generate a new one):")
        recovery_phrase = stdin.readline().strip()
        if recovery_phrase == "seed":
            generate_recovery_phrase()
        set_key(env_path, "RECOVERY_PHRASE", recovery_phrase)

    app_id_hex = os.getenv("APP_ID")
    if not app_id_hex or len(app_id_hex) != 64:
        app_id_bytes = secrets.token_bytes(32)
        set_key(env_path, "APP_ID", app_id_bytes.hex())
    else:
        app_id_bytes = bytes.fromhex(app_id_hex)

    return recovery_phrase, app_id_bytes

def _load_manifest(path: Path) -> tuple[str | None, str | None]:
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
        return m.get("share_url"), m.get("indexd_url")
    except Exception:
        return None, None

app = FastAPI()
ZIP = None               # type: zipfile.ZipFile | None
ZIP_SET = set()
ETAG = 'W/"boot"'
STARTED_AT = datetime.now(timezone.utc).isoformat()
DEFAULT_INDEXES = ("index.html","index.htm")

def build_index(zf: zipfile.ZipFile) -> set[str]:
    items = set()
    for n in zf.namelist():
        n2 = n.replace("\\","/").rstrip("/")
        if n2:
            items.add(n2)
    return items

def find_index(prefix: str) -> str | None:
    prefix = prefix.rstrip("/")
    for ix in DEFAULT_INDEXES:
        cand = (prefix + "/" + ix) if prefix else ix
        if cand in ZIP_SET:
            return cand
    return None

@app.get("/__health", response_class=PlainTextResponse)
def health():
    if ZIP is None:
        raise HTTPException(503, "zip not loaded")
    probes = ["index.html","index.htm","favicon.ico"]
    lines = [f"{p}: {'ok' if (p in ZIP_SET or any(x.startswith(p) for x in ZIP_SET)) else 'missing'}" for p in probes]
    return "ok\n" + "\n".join(lines)

@app.get("/{rest:path}")
def serve(rest: str):
    if ZIP is None:
        raise HTTPException(503, "archive not ready")
    path = _norm_path(rest)

    if path == "":
        idx = find_index("")
        if not idx:
            return HTMLResponse("<h1>No index.html in archive</h1>", status_code=404)
        return _serve_member(idx)

    if path in ZIP_SET:
        return _serve_member(path)

    if any(n.startswith(path + "/") for n in ZIP_SET):
        idx = find_index(path)
        if idx:
            return _serve_member(idx)

    raise HTTPException(404, f"Not found: /{path}")

def _serve_member(name: str):
    try:
        data = ZIP.read(name)
    except KeyError:
        raise HTTPException(404, "Not in archive")
    headers = {
        "ETag": ETAG,
        "Cache-Control": "public, max-age=60",
        "Last-Modified": STARTED_AT,
        "X-From": "zip-gateway",
    }
    return Response(data, media_type=_guess_mime(name), headers=headers)

async def read_handle_bytes(handle, *, chunk_size: int = 1 << 20) -> bytes:
    for rname in ("read_all", "read_to_end", "bytes"):
        if hasattr(handle, rname):
            return bytes(await maybe_await(getattr(handle, rname)()))

    for rname in ("read", "next_chunk"):
        if hasattr(handle, rname):
            byte_array = bytearray()
            reader = getattr(handle, rname)
            while True:
                chunk = await maybe_await(reader())
                if not chunk:
                    break
                byte_array.extend(chunk)
            return bytes(byte_array)

    if hasattr(handle, "read_chunk"):
        byte_array = bytearray()
        while True:
            chunk = await maybe_await(handle.read_chunk())
            if not chunk:
                break
            byte_array.extend(chunk)
        return bytes(byte_array)

    size = None
    for sname in ("size", "len", "length"):
        if hasattr(handle, sname):
            try:
                size = await maybe_await(getattr(handle, sname)())
            except TypeError:
                size = getattr(handle, sname)
            if isinstance(size, int) and size >= 0:
                break
            size = None
    if size is not None and hasattr(handle, "read_at"):
        byte_array = bytearray()
        off = 0
        while off < size:
            n = min(chunk_size, size - off)
            chunk = await maybe_await(handle.read_at(off, n))
            if not chunk:
                break
            byte_array.extend(chunk)
            off += len(chunk)
        return bytes(byte_array)

    if hasattr(handle, "__aiter__"):
        byte_array = bytearray()
        async for chunk in handle:
            if not chunk:
                break
            byte_array.extend(chunk)
        return bytes(byte_array)
    if hasattr(handle, "stream"):
        s = await maybe_await(handle.stream())
        if hasattr(s, "read"):
            byte_array = bytearray()
            while True:
                chunk = await maybe_await(s.read(chunk_size))
                if not chunk:
                    break
                byte_array.extend(chunk)
            return bytes(byte_array)
        if hasattr(s, "__aiter__"):
            byte_array = bytearray()
            async for chunk in s:  # type: ignore
                if not chunk:
                    break
                byte_array.extend(chunk)
            return bytes(byte_array)

    if hasattr(handle, "open"):
        f = await maybe_await(handle.open())
        if hasattr(f, "read"):
            byte_array = bytearray()
            while True:
                chunk = await maybe_await(f.read(chunk_size))
                if not chunk:
                    break
                byte_array.extend(chunk)
            return bytes(byte_array)

    if hasattr(handle, "__bytes__"):
        try:
            return bytes(handle)
        except Exception:
            pass

    for attr in ("content", "data", "body"):
        if hasattr(handle, attr):
            b = getattr(handle, attr)
            if isinstance(b, (bytes, bytearray)):
                return bytes(b)

    t = type(handle)
    attrs = [a for a in dir(handle) if not a.startswith("_")]
    raise RuntimeError(
        f"Unknown download handle shape; cannot read bytes.\n"
        f"type={t.__module__}.{t.__name__}\n"
        f"attrs={attrs}"
    )

async def fetch_zip_via_sdk(share_url: str, indexer_url: str | None, *, no_auth: bool, env_path: str, auth_fallback: bool) -> bytes:
    # Windows event loop policy (helps some async stacks)
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    if not indexer_url:
        indexer_url = _extract_indexd_base(share_url)

    set_logger(PrintLogger(), "info")

    builder = Builder(indexer_url)
    
    recovery_phrase, app_id = _load_or_prompt_env(env_path)

    sdk: Sdk | None = None
    app_key: AppKey | None = None

    stored_key = _load_app_key()
    if stored_key is not None:
        try:
            app_key = AppKey(stored_key)
            sdk = await builder.connected(app_key)
        except Exception as e:
            # If anything goes wrong parsing the key, fall back to onboarding
            print(f"\nFailed to use stored App Key ({e}). Running onboarding...\n")
            sdk = None
            app_key = None

        if sdk is not None:
            print("\nConnected using stored App Key.")
        else:
            print("\nStored App Key is no longer valid. Running onboarding...\n")

    # 3. If fast-path failed (or no key stored), run the full onboarding flow
    if sdk is None:
        app_meta = AppMeta(
                id=app_id,
                name="Wack-a-Mole Gateway (read-only)",
                description="Temporary client to read a shared Wack-a-Mole site",
                service_url="about:blank",
                logo_url=None,
                callback_url=None
            )

        # Request app connection and get the approval URL
        print("\nRequesting app authorization…")
        await builder.request_connection(app_meta)
        try:
            webbrowser.open(builder.response_url())
            print("\n\nOpen this URL to approve the app:", builder.response_url())
        except Exception:
            pass
        
        # Wait for the user to approve the request
        approved = await builder.wait_for_approval()
        if not approved:
            raise Exception("\nUser rejected the app or request timed out")

        # Register an SDK instance with your recovery phrase.
        sdk = await builder.register(recovery_phrase)

        app_key = sdk.app_key()
        exported = app_key.export()  # Should be a 32-byte key for secure storage
        _save_app_key(exported)

    ref = await maybe_await(sdk.shared_object(share_url))
    handle = await maybe_await(sdk.download_shared(ref, DownloadOptions(max_inflight=6)))
    data = await read_handle_bytes(handle)
    if not data.startswith(b"PK\x03\x04"):
        raise RuntimeError("Downloaded bytes are not a ZIP (missing PK header).")
    return data

def load_zip_into_memory(data: bytes):
    global ZIP, ZIP_SET, ETAG
    zf = zipfile.ZipFile(io.BytesIO(data), "r")
    ZIP = zf
    ZIP_SET = build_index(zf)
    import hashlib
    ETAG = 'W/"%s"' % hashlib.sha256(data).hexdigest()[:32]
    print(f"Loaded ZIP with {len(ZIP_SET)} entries.")

def main():
    parser = argparse.ArgumentParser(description="Serve a static site from an indexd share URL (SDK-backed).")
    parser.add_argument("--share-url", help="Share URL printed by publish.py")
    parser.add_argument("--manifest", default="manifest.json", help="Path to manifest.json (auto-used if --share not given)")
    parser.add_argument("--indexer-url", default=None, help="Indexd base URL (auto-detected from share or manifest if omitted)")
    parser.add_argument("--env", default=".env", help="Path to .env (used only if auth fallback is needed)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-auth", dest="no_auth", action="store_true", default=True,
                        help="Try to fetch using only the share URL without app approval (default: on)")
    parser.add_argument("--auth-fallback", dest="auth_fallback", action="store_true", default=True,
                        help="If no-auth fails, fall back to interactive auth (default: on)")
    args = parser.parse_args()

    # If no --share and manifest exists, load from manifest
    if not args.share_url:
        mpath = Path(args.manifest)
        if mpath.exists():
            manifest_share_url, manifest_indexer_url = _load_manifest(mpath)
            if manifest_share_url:
                args.share_url = manifest_share_url
            if not args.indexer_url and manifest_indexer_url:
                args.indexer_url = manifest_indexer_url

    if not args.share_url:
        print("ERROR: Provide --share or ensure manifest.json exists with a share_url.")
        sys.exit(2)

    # Fetch ZIP (no-auth first, with optional auth fallback)
    data = asyncio.run(fetch_zip_via_sdk(
        args.share_url,
        args.indexer_url,
        no_auth=args.no_auth,
        env_path=args.env,
        auth_fallback=args.auth_fallback
    ))

    load_zip_into_memory(data)
    print(f"Try: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()