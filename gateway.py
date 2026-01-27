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
import struct
import zlib
from sys import stdin
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse
from datetime import datetime, timezone
from threading import Lock

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, PlainTextResponse
import uvicorn

from dotenv import set_key
try:
    from dotenv import load_dotenv
    load_dotenv(".env")
except Exception:
    pass

from indexd_ffi import (
    Builder, AppKey, AppMeta, Logger,
    DownloadOptions, Writer,
    generate_recovery_phrase, set_logger, uniffi_set_event_loop
)


# ---------------------------
# Logging (SDK expects warn())
# ---------------------------
class PrintLogger(Logger):
    def debug(self, msg): print("DEBUG", msg)
    def info(self, msg): print("INFO", msg)
    def warn(self, msg): print("WARN", msg)
    def error(self, msg): print("ERROR", msg)


# ---------------------------
# App key persistence
# ---------------------------
def _load_app_key() -> bytes | None:
    try:
        with open("app_key.bin", "rb") as f:
            data = f.read()
    except FileNotFoundError:
        return None

    if len(data) != 32:
        print(f"\nStored App Key has invalid length ({len(data)} bytes). Ignoring.")
        return None
    return data


def _save_app_key(data: bytes) -> None:
    with open("app_key.bin", "wb") as f:
        f.write(data)


# ---------------------------
# UniFFI Writer (collect bytes)
# ---------------------------
class BytesWriter(Writer):
    """
    UniFFI Writer: SDK calls write() with data chunks.
    We track byte count so we can wait until all bytes arrive (drain async bridge).
    """
    def __init__(self):
        self._buf = io.BytesIO()
        self._lock = Lock()
        self._n = 0

    async def write(self, data: bytes) -> None:
        if not data:
            return
        with self._lock:
            self._buf.write(data)
            self._n += len(data)

    def getvalue(self) -> bytes:
        with self._lock:
            return self._buf.getvalue()

    def nbytes(self) -> int:
        with self._lock:
            return self._n


# ---------------------------
# MIME + path helpers
# ---------------------------
def _guess_mime(name: str) -> str:
    low = name.lower()
    if low.endswith((".html", ".htm")): return "text/html; charset=utf-8"
    if low.endswith(".css"):            return "text/css; charset=utf-8"
    if low.endswith(".js"):             return "application/javascript; charset=utf-8"
    if low.endswith(".json"):           return "application/json; charset=utf-8"
    if low.endswith(".svg"):            return "image/svg+xml"
    if low.endswith(".png"):            return "image/png"
    if low.endswith((".jpg", ".jpeg")): return "image/jpeg"
    if low.endswith(".gif"):            return "image/gif"
    if low.endswith(".webp"):           return "image/webp"
    if low.endswith(".ico"):            return "image/x-icon"
    return "application/octet-stream"


def _norm_path(url_path: str) -> str:
    p = PurePosixPath("/" + url_path).as_posix()
    p = posixpath.normpath(p)
    if p.startswith("/"):
        p = p[1:]
    return "" if p == "." else p


def _extract_indexd_base(share_url: str) -> str:
    u = urlparse(share_url)
    return f"{u.scheme}://{u.netloc}"


def _load_or_prompt_env(env_path: str = ".env") -> tuple[str, bytes]:
    recovery_phrase = os.getenv("RECOVERY_PHRASE")
    if not recovery_phrase:
        print("Enter recovery phrase (type `seed` to generate a new one):")
        rp = stdin.readline().strip()
        if rp == "seed" or rp == "":
            rp = generate_recovery_phrase()
            print("\nGenerated recovery phrase (store securely!):\n" + rp)
        recovery_phrase = rp
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
        share = m.get("share_url")
        indexer = m.get("indexer_url") or m.get("indexd_url") or m.get("indexer") or m.get("indexd")
        return share, indexer
    except Exception:
        return None, None


def _clamp_u8(n: int, default: int = 6) -> int:
    try:
        n = int(n)
    except Exception:
        n = default
    return max(1, min(255, n))


DEFAULT_INDEXES = ("index.html", "index.htm")


# ---------------------------
# FastAPI app + ZIP state
# ---------------------------
app = FastAPI()

ZIP = None               # type: zipfile.ZipFile | None

# We store names in lower-case for lookups, and map back to actual zip names:
ZIP_NAMES_LOWER: list[str] = []
ZIP_SET_LOWER: set[str] = set()
ZIP_REAL_BY_LOWER: dict[str, str] = {}

ETAG = 'W/"boot"'
STARTED_AT = datetime.now(timezone.utc).isoformat()

# Fallback ZIP (no central directory) state
USING_FALLBACK = False
FALLBACK_DATA: bytes | None = None
FALLBACK_ENTRIES: dict[str, dict] = {}
FALLBACK_DECOMP_CACHE: dict[str, bytes] = {}

# Auto-detected root prefix inside the zip (e.g. "dist", "website")
ROOT_PREFIX = ""  # stored WITHOUT trailing slash; empty means "zip root"


def _strip_slashes(s: str) -> str:
    return s.strip("/").strip("\\")


def _with_root(path: str) -> str:
    """
    Map a request-relative path (like 'css/app.css' or 'index.html')
    into the actual zip name, applying ROOT_PREFIX if set.
    """
    path = _strip_slashes(path)
    if not ROOT_PREFIX:
        return path
    if not path:
        return ROOT_PREFIX
    return f"{ROOT_PREFIX}/{path}"


def _resolve_name(maybe_name: str) -> str | None:
    """
    Resolve a possibly-cased name to the actual stored zip name,
    using lower-case mapping.
    """
    key = maybe_name.lower()
    return ZIP_REAL_BY_LOWER.get(key)


def _any_startswith(prefix: str) -> bool:
    """
    Case-insensitive startswith over zip names.
    """
    pl = prefix.lower()
    for n in ZIP_NAMES_LOWER:
        if n.startswith(pl):
            return True
    return False


def _detect_root_prefix() -> str:
    """
    Determine ROOT_PREFIX when index.html isn't at zip root.
    Strategy:
      1) If index.html or index.htm exists at root -> ""
      2) If any */index.html exists -> choose the shallowest one and return its parent dir
      3) If everything shares a single top-level directory -> that directory
      4) Else -> ""
    """
    # 1) root index?
    for ix in DEFAULT_INDEXES:
        if ix in ZIP_SET_LOWER:
            return ""

    # 2) find shallowest nested index.* anywhere
    candidates = []
    for n in ZIP_SET_LOWER:
        if n.endswith("/index.html") or n.endswith("/index.htm"):
            candidates.append(n)
    if candidates:
        # choose the shallowest (fewest segments), then shortest
        best = min(candidates, key=lambda s: (len(s.split("/")), len(s)))
        parent = best.rsplit("/", 1)[0]
        return _strip_slashes(parent)

    # 3) single common top-level directory?
    tops = set()
    all_have_slash = True
    for n in ZIP_SET_LOWER:
        if "/" not in n:
            all_have_slash = False
            break
        tops.add(n.split("/", 1)[0])
        if len(tops) > 1:
            break
    if all_have_slash and len(tops) == 1:
        return next(iter(tops))

    return ""


def find_index(req_prefix: str) -> str | None:
    req_prefix = _strip_slashes(req_prefix)
    for ix in DEFAULT_INDEXES:
        cand = (req_prefix + "/" + ix) if req_prefix else ix
        internal = _with_root(cand)
        resolved = _resolve_name(internal)
        if resolved is not None:
            return resolved
    return None


@app.get("/__debug", response_class=PlainTextResponse)
def debug():
    lines = [
        f"USING_FALLBACK={USING_FALLBACK}",
        f"ROOT_PREFIX={ROOT_PREFIX!r}",
        f"entries={len(ZIP_SET_LOWER)}",
        "",
        "first_entries:",
    ]
    for n in sorted(ZIP_REAL_BY_LOWER.values())[:80]:
        lines.append(n)
    return "\n".join(lines)


@app.get("/__health", response_class=PlainTextResponse)
def health():
    if (ZIP is None) and (not USING_FALLBACK):
        raise HTTPException(503, "zip not loaded")

    probes = ["index.html", "index.htm", "favicon.ico"]
    lines = []
    for p in probes:
        internal = _with_root(p)
        ok = _resolve_name(internal) is not None
        lines.append(f"{p}: {'ok' if ok else 'missing'} (mapped: {internal})")
    return "ok\n" + "\n".join(lines)


@app.get("/{rest:path}")
def serve(rest: str):
    if (ZIP is None) and (not USING_FALLBACK):
        raise HTTPException(503, "archive not ready")

    path = _norm_path(rest)

    # Root
    if path == "":
        idx = find_index("")
        if not idx:
            return HTMLResponse(
                "<h1>No index.html in archive</h1>"
                "<p>Try <code>/__debug</code> to see archive entries and root prefix.</p>",
                status_code=404,
            )
        return _serve_member(idx)

    internal = _with_root(path)
    resolved = _resolve_name(internal)

    # Exact file
    if resolved is not None:
        return _serve_member(resolved)

    # Directory: try index under directory
    dir_prefix = _strip_slashes(internal) + "/"
    if _any_startswith(dir_prefix):
        idx = find_index(path)
        if idx:
            return _serve_member(idx)

    raise HTTPException(404, f"Not found: /{path}")


def _serve_member(actual_name: str):
    headers = {
        "ETag": ETAG,
        "Cache-Control": "public, max-age=60",
        "Last-Modified": STARTED_AT,
        "X-From": "zip-gateway" if not USING_FALLBACK else "zip-gateway-fallback",
    }

    if not USING_FALLBACK:
        try:
            data = ZIP.read(actual_name)  # type: ignore[union-attr]
        except KeyError:
            raise HTTPException(404, "Not in archive")
        return Response(data, media_type=_guess_mime(actual_name), headers=headers)

    # Fallback serving (local-header parsing)
    # FALLBACK_ENTRIES is keyed by *actual* stored names (as parsed)
    info = FALLBACK_ENTRIES.get(actual_name)
    if not info:
        raise HTTPException(404, "Not in archive")

    if actual_name in FALLBACK_DECOMP_CACHE:
        data = FALLBACK_DECOMP_CACHE[actual_name]
        return Response(data, media_type=_guess_mime(actual_name), headers=headers)

    data = _fallback_extract(actual_name)
    if len(data) <= 2 * 1024 * 1024:
        FALLBACK_DECOMP_CACHE[actual_name] = data
    return Response(data, media_type=_guess_mime(actual_name), headers=headers)


# ---------------------------
# Fallback ZIP parsing/extract
# ---------------------------
def _parse_zip_local_headers(blob: bytes) -> dict[str, dict]:
    """
    Parse local file headers sequentially:
      - Works even if central directory is missing/corrupt.
      - Requires that local headers contain sizes (i.e. no data descriptor flag).
    Returns mapping: name -> {method, flags, comp_off, comp_len, uncomp_len}
    """
    entries: dict[str, dict] = {}
    off = 0
    n = len(blob)

    while off + 30 <= n:
        sig = blob[off:off+4]
        if sig != b"PK\x03\x04":
            break

        try:
            ver, flags, method, mtime, mdate, crc32, csize, usize, fnlen, extralen = struct.unpack_from(
                "<HHHHHIIIHH", blob, off + 4
            )
        except struct.error:
            break

        name_start = off + 30
        name_end = name_start + fnlen
        extra_end = name_end + extralen
        if extra_end > n:
            break

        name_bytes = blob[name_start:name_end]

        is_utf8 = bool(flags & (1 << 11))
        if is_utf8:
            name = name_bytes.decode("utf-8", errors="replace")
        else:
            try:
                name = name_bytes.decode("utf-8")
            except Exception:
                name = name_bytes.decode("cp437", errors="replace")

        name = name.replace("\\", "/")
        data_off = extra_end

        if flags & 0x08:
            raise RuntimeError(
                "Fallback ZIP parser encountered a file that uses a data descriptor (flags bit 3 set). "
                "This gateway fallback does not support descriptor-based entries yet."
            )

        comp_end = data_off + csize
        if comp_end > n:
            break

        if name and not name.endswith("/"):
            entries[name] = {
                "method": method,
                "flags": flags,
                "comp_off": data_off,
                "comp_len": csize,
                "uncomp_len": usize,
            }

        off = comp_end

    if not entries:
        raise RuntimeError("Fallback ZIP parser could not find any local file entries.")
    return entries


def _fallback_extract(actual_name: str) -> bytes:
    if FALLBACK_DATA is None:
        raise RuntimeError("Fallback ZIP data not loaded")

    info = FALLBACK_ENTRIES.get(actual_name)
    if not info:
        raise KeyError(actual_name)

    method = info["method"]
    comp_off = info["comp_off"]
    comp_len = info["comp_len"]
    comp = FALLBACK_DATA[comp_off:comp_off + comp_len]

    if method == 0:
        return comp

    if method == 8:
        try:
            return zlib.decompress(comp, -15)  # raw deflate
        except zlib.error as e:
            raise RuntimeError(f"Failed to inflate {actual_name}: {e}")

    raise RuntimeError(f"Unsupported compression method for {actual_name}: {method}")


# ---------------------------
# Download via SDK
# ---------------------------
async def fetch_zip_via_sdk(
    share_url: str,
    indexer_url: str | None,
    *,
    env_path: str,
    no_auth: bool,
    inflight: int = 6,
) -> bytes:
    if sys.platform.startswith("win"):
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    if not indexer_url:
        indexer_url = _extract_indexd_base(share_url)

    set_logger(PrintLogger(), "info")
    uniffi_set_event_loop(asyncio.get_running_loop())  # REQUIRED for UniFFI async traits

    builder = Builder(indexer_url)

    # Fast path: stored app key
    sdk = None
    stored_key = _load_app_key()
    if stored_key is not None:
        try:
            app_key = AppKey(stored_key)
            sdk = await builder.connected(app_key)
            if sdk is not None:
                print("\nConnected using stored App Key.")
        except Exception as e:
            print(f"\nFailed to use stored App Key ({e}). Will re-onboard.")
            sdk = None

    if sdk is None:
        if no_auth:
            raise RuntimeError(
                "No stored app_key.bin available and --no-auth was set.\n"
                "Remove --no-auth to run interactive onboarding, or provide app_key.bin."
            )

        recovery_phrase, app_id = _load_or_prompt_env(env_path)

        app_meta = AppMeta(
            id=app_id,
            name="Wack-a-Mole Gateway (read-only)",
            description="Temporary client to read a shared Wack-a-Mole site",
            service_url="about:blank",
            logo_url=None,
            callback_url=None,
        )

        print("\nRequesting app authorization…")
        await builder.request_connection(app_meta)

        try:
            url = builder.response_url()
            webbrowser.open(url)
            print("\nOpen this URL to approve the app:", url)
        except Exception:
            print("\nOpen this URL to approve the app:", builder.response_url())

        await builder.wait_for_approval()
        sdk = await builder.register(recovery_phrase)

        app_key = sdk.app_key()
        _save_app_key(app_key.export())
        print("\nOnboarding complete; stored app_key.bin.")

    shared_obj = await sdk.shared_object(share_url)

    # Best-effort retention/caching
    try:
        await sdk.pin_object(shared_obj)
        print("Pinned shared object (best-effort retention).")
    except Exception as e:
        print(f"WARN: Failed to pin shared object (continuing anyway): {e}")

    try:
        expected = int(shared_obj.size())
    except Exception:
        expected = -1

    max_inflight = _clamp_u8(inflight, default=6)
    writer = BytesWriter()
    await sdk.download(writer, shared_obj, DownloadOptions(max_inflight=max_inflight))

    # Drain writer bridge
    if expected >= 0:
        timeout = max(10.0, min(120.0, expected / (5 * 1024 * 1024)))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        last = -1
        while writer.nbytes() < expected and loop.time() < deadline:
            now = writer.nbytes()
            if now == last:
                await asyncio.sleep(0.02)
            else:
                last = now
                await asyncio.sleep(0)

        got = writer.nbytes()
        if got < expected:
            raise RuntimeError(f"Download incomplete: got {got} bytes, expected {expected}.")

    return writer.getvalue()


# ---------------------------
# ZIP loading (standard + fallback) + root prefix detection
# ---------------------------
def _index_names(names: list[str]):
    """
    Populate ZIP_* lookup structures with case-insensitive mapping.
    """
    global ZIP_NAMES_LOWER, ZIP_SET_LOWER, ZIP_REAL_BY_LOWER
    ZIP_NAMES_LOWER = []
    ZIP_SET_LOWER = set()
    ZIP_REAL_BY_LOWER = {}

    for raw in names:
        n = raw.replace("\\", "/").rstrip("/")
        if not n:
            continue
        key = n.lower()
        ZIP_SET_LOWER.add(key)
        ZIP_NAMES_LOWER.append(key)
        # keep first seen actual casing
        ZIP_REAL_BY_LOWER.setdefault(key, n)


def load_zip_into_memory(data: bytes):
    """
    Try standard ZipFile first.
    If that fails, fall back to local-header parsing and serve from that.
    Then auto-detect ROOT_PREFIX if needed.
    """
    global ZIP, ETAG, USING_FALLBACK, FALLBACK_DATA, FALLBACK_ENTRIES, FALLBACK_DECOMP_CACHE, ROOT_PREFIX

    import hashlib
    ETAG = 'W/"%s"' % hashlib.sha256(data).hexdigest()[:32]

    # Reset
    ZIP = None
    USING_FALLBACK = False
    FALLBACK_DATA = None
    FALLBACK_ENTRIES = {}
    FALLBACK_DECOMP_CACHE = {}
    ROOT_PREFIX = ""

    # Standard
    try:
        zf = zipfile.ZipFile(io.BytesIO(data), "r")
        names = zf.namelist()
        ZIP = zf
        _index_names(names)
        ROOT_PREFIX = _detect_root_prefix()
        print(f"Loaded ZIP (standard) entries={len(ZIP_SET_LOWER)} ROOT_PREFIX={ROOT_PREFIX!r}")
        return
    except zipfile.BadZipFile:
        pass
    except Exception as e:
        print(f"WARN: Standard ZIP open failed ({e}); trying fallback parser...")

    # Fallback
    FALLBACK_DATA = data
    FALLBACK_ENTRIES = _parse_zip_local_headers(data)
    USING_FALLBACK = True

    names = list(FALLBACK_ENTRIES.keys())
    _index_names(names)

    ROOT_PREFIX = _detect_root_prefix()
    print(f"Loaded ZIP (fallback) entries={len(ZIP_SET_LOWER)} ROOT_PREFIX={ROOT_PREFIX!r}")


# ---------------------------
# main()
# ---------------------------
def main():
    parser = argparse.ArgumentParser(description="Serve a static site from an indexd share URL (SDK-backed).")
    parser.add_argument("--share-url", help="Share URL printed by publish.py")
    parser.add_argument("--manifest", default="manifest.json", help="Path to manifest.json (auto-used if --share-url not given)")
    parser.add_argument("--indexer-url", default=None, help="Indexd base URL (auto-detected from share or manifest if omitted)")
    parser.add_argument("--env", default=".env", help="Path to .env (used only if onboarding is needed)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-auth", action="store_true", help="Do not run interactive onboarding; requires app_key.bin")
    parser.add_argument("--inflight", type=int, default=6, help="Max inflight download shards (1..255)")
    args = parser.parse_args()

    if not args.share_url:
        mpath = Path(args.manifest)
        if mpath.exists():
            share, idx = _load_manifest(mpath)
            if share:
                args.share_url = share
            if not args.indexer_url and idx:
                args.indexer_url = idx

    if not args.share_url:
        print("ERROR: Provide --share-url or ensure manifest.json exists with a share_url.")
        sys.exit(2)

    data = asyncio.run(fetch_zip_via_sdk(
        args.share_url,
        args.indexer_url,
        env_path=args.env,
        no_auth=args.no_auth,
        inflight=args.inflight,
    ))

    load_zip_into_memory(data)

    print(f"Try: http://{args.host}:{args.port}/")
    print("Debug: http://127.0.0.1:8787/__debug")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()