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

import argparse
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

from dotenv import load_dotenv, set_key

from indexd_ffi import (
    Sdk, AppKey, AppMeta, set_logger, Logger,
    DownloadOptions, generate_recovery_phrase
)

class PrintLogger(Logger):
    def debug(self, msg): print("DEBUG", msg)
    def info(self, msg): print("INFO", msg)
    def warning(self, msg): print("WARN", msg)
    def error(self, msg): print("ERROR", msg)

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
    # Ensure file exists
    load_dotenv(env_path)
    if not os.path.exists(env_path):
        open(env_path, "a", encoding="utf-8").close()

    seed_phrase = os.getenv("SEED_PHRASE")
    if not seed_phrase:
        print("Enter seed_phrase (leave blank to generate a new one):")
        entered = stdin.readline().strip()
        seed_phrase = entered or generate_recovery_phrase()
        set_key(env_path, "SEED_PHRASE", seed_phrase)

    app_id_hex = os.getenv("APP_ID")
    if not app_id_hex or len(app_id_hex) != 64:
        app_id_bytes = secrets.token_bytes(32)
        set_key(env_path, "APP_ID", app_id_bytes.hex())
    else:
        app_id_bytes = bytes.fromhex(app_id_hex)

    return seed_phrase, app_id_bytes

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
    # 1) Common "read all" shapes
    for rname in ("read_all", "read_to_end", "bytes"):
        if hasattr(handle, rname):
            return bytes(await maybe_await(getattr(handle, rname)()))

    # 2) Pull-based chunk readers
    for rname in ("read", "next_chunk"):
        if hasattr(handle, rname):
            out = bytearray()
            reader = getattr(handle, rname)
            while True:
                chunk = await maybe_await(reader())
                if not chunk:
                    break
                out.extend(chunk)
            return bytes(out)

    # 2b) indexd_ffi.Download shape: read_chunk()
    if hasattr(handle, "read_chunk"):
        out = bytearray()
        while True:
            chunk = await maybe_await(handle.read_chunk())
            if not chunk:
                break
            out.extend(chunk)
        return bytes(out)

    # 3) Range reader (size + read_at)
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
        out = bytearray()
        off = 0
        while off < size:
            n = min(chunk_size, size - off)
            chunk = await maybe_await(handle.read_at(off, n))
            if not chunk:
                break
            out.extend(chunk)
            off += len(chunk)
        return bytes(out)

    # 4) Streams (async iterator or .stream() → object with .read())
    if hasattr(handle, "__aiter__"):
        out = bytearray()
        async for chunk in handle:  # type: ignore
            if not chunk:
                break
            out.extend(chunk)
        return bytes(out)
    if hasattr(handle, "stream"):
        s = await maybe_await(handle.stream())
        if hasattr(s, "read"):
            out = bytearray()
            while True:
                chunk = await maybe_await(s.read(chunk_size))
                if not chunk:
                    break
                out.extend(chunk)
            return bytes(out)
        if hasattr(s, "__aiter__"):
            out = bytearray()
            async for chunk in s:  # type: ignore
                if not chunk:
                    break
                out.extend(chunk)
            return bytes(out)

    # 5) .open() → filelike with read()
    if hasattr(handle, "open"):
        f = await maybe_await(handle.open())
        if hasattr(f, "read"):
            out = bytearray()
            while True:
                chunk = await maybe_await(f.read(chunk_size))
                if not chunk:
                    break
                out.extend(chunk)
            return bytes(out)

    # 6) __bytes__ or direct bytes()
    if hasattr(handle, "__bytes__"):
        try:
            return bytes(handle)
        except Exception:
            pass

    # 7) Struct-like responses with .content / .data / .body
    for attr in ("content", "data", "body"):
        if hasattr(handle, attr):
            b = getattr(handle, attr)
            if isinstance(b, (bytes, bytearray)):
                return bytes(b)

    # 8) Helpful error
    t = type(handle)
    attrs = [a for a in dir(handle) if not a.startswith("_")]
    raise RuntimeError(
        f"Unknown download handle shape; cannot read bytes.\n"
        f"type={t.__module__}.{t.__name__}\n"
        f"attrs={attrs}"
    )

# ==============================
# SDK download (resolve → download_shared)
# ==============================

async def fetch_zip_via_sdk(share_url: str, indexd_base: str | None, *, no_auth: bool, env_path: str, auth_fallback: bool) -> bytes:
    # Windows event loop policy (helps some async stacks)
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    if not indexd_base:
        indexd_base = _extract_indexd_base(share_url)

    set_logger(PrintLogger(), "info")

    # Prefer "no-auth" path: ephemeral key, do NOT request approval.
    if no_auth:
        ephemeral_mnemonic = generate_recovery_phrase()
        ephemeral_app_id = secrets.token_bytes(32)
        sdk = Sdk(indexd_base, AppKey(ephemeral_mnemonic, ephemeral_app_id))
        try:
            # Directly try the shared-object flow without checking sdk.connected()
            ref = await maybe_await(sdk.shared_object(share_url))
            handle = await maybe_await(sdk.download_shared(ref, DownloadOptions(max_inflight=6)))
            data = await read_handle_bytes(handle)
            if not data.startswith(b"PK\x03\x04"):
                raise RuntimeError("Downloaded bytes are not a ZIP (missing PK header).")
            return data
        except Exception as e:
            if not auth_fallback:
                raise
            print("No-auth path failed; attempting interactive auth fallback…")
            # fall-through to auth path below

    # Auth path: ensure connection approved, then download
    seed_phrase, app_id = _load_or_prompt_env(env_path)
    sdk = Sdk(indexd_base, AppKey(seed_phrase, app_id))
    is_connected = await maybe_await(sdk.connected()) if hasattr(sdk, "connected") else True
    if not is_connected:
        resp = await maybe_await(sdk.request_app_connection(AppMeta(
            name="Zip Gateway (read-only)",
            description="Temporary client to read a shared object",
            service_url="about:blank",
            logo_url=None,
            callback_url=None
        )))
        print("Approve access in your browser if it opens:")
        print(resp.response_url)
        try:
            import webbrowser; webbrowser.open(resp.response_url)
        except Exception:
            pass
        ok = await maybe_await(sdk.wait_for_connect(resp))
        if not ok:
            raise RuntimeError("Authorization was not granted")

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
    parser.add_argument("--share", help="Share URL printed by publish.py")
    parser.add_argument("--manifest", default="manifest.json", help="Path to manifest.json (auto-used if --share not given)")
    parser.add_argument("--indexd", default=None, help="Indexd base URL (auto-detected from share or manifest if omitted)")
    parser.add_argument("--env", default=".env", help="Path to .env (used only if auth fallback is needed)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-auth", dest="no_auth", action="store_true", default=True,
                        help="Try to fetch using only the share URL without app approval (default: on)")
    parser.add_argument("--auth-fallback", dest="auth_fallback", action="store_true", default=True,
                        help="If no-auth fails, fall back to interactive auth (default: on)")
    args = parser.parse_args()

    # If no --share and manifest exists, load from manifest
    if not args.share:
        mpath = Path(args.manifest)
        if mpath.exists():
            share_from_m, indexd_from_m = _load_manifest(mpath)
            if share_from_m:
                args.share = share_from_m
            if not args.indexd and indexd_from_m:
                args.indexd = indexd_from_m

    if not args.share:
        print("ERROR: Provide --share or ensure manifest.json exists with a share_url.")
        sys.exit(2)

    # Fetch ZIP (no-auth first, with optional auth fallback)
    data = asyncio.run(fetch_zip_via_sdk(
        args.share,
        args.indexd,
        no_auth=args.no_auth,
        env_path=args.env,
        auth_fallback=args.auth_fallback
    ))

    load_zip_into_memory(data)
    print(f"Try: http://{args.host}:{args.port}/")
    uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()