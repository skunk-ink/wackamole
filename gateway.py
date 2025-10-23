#!/usr/bin/env python3
# Python 3.12+
import asyncio
import json
import os
import time
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any, Union
import httpx
from fastapi import FastAPI, Response, Request, HTTPException, Header
from fastapi.responses import StreamingResponse, PlainTextResponse
import zipfile

# -------------------------
# Environment
# -------------------------

MANIFEST_URL = os.getenv("MANIFEST_URL", "").strip()  # required
MODE = os.getenv("MODE", "auto").lower()  # "multi", "zip", or "auto"
WARM_THRESHOLD_BYTES = int(os.getenv("WARM_THRESHOLD_BYTES", str(200 * 1024 * 1024)))  # 200MB
ZIP_REVALIDATE_INTERVAL = int(os.getenv("ZIP_REVALIDATE_INTERVAL", "300"))  # seconds
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "30"))
MAX_STREAMS = int(os.getenv("MAX_STREAMS", "64"))
ENABLE_RANGE_READS = os.getenv("ENABLE_RANGE_READS", "true").lower() not in ("0", "false", "no")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# -------------------------
# Globals
# -------------------------

app = FastAPI()
_client = httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True)
_manifest_cache: Dict[str, Any] = {}
_manifest_loaded_at = 0.0

# For zip mode
_zip_state = {
    "url": None,
    "etag": None,
    "last_modified": None,
    "size": None,
    "temp_path": None,  # if downloaded
    "zip_obj": None,    # zipfile.ZipFile when warm
    "last_checked": 0.0,
}


def log(msg: str):
    if LOG_LEVEL in ("DEBUG", "INFO"):
        print(msg, flush=True)


# -------------------------
# Helpers
# -------------------------

async def fetch_json(url: str) -> dict:
    r = await _client.get(url)
    r.raise_for_status()
    return r.json()

async def head(url: str) -> httpx.Response:
    r = await _client.head(url)
    r.raise_for_status()
    return r

async def get_stream(url: str, headers: Optional[Dict[str, str]] = None) -> httpx.Response:
    r = await _client.get(url, headers=headers, timeout=None)
    r.raise_for_status()
    return r

def cache_headers(etag: Optional[str], last_modified: Optional[str]) -> Dict[str, str]:
    h = {"Cache-Control": "public,max-age=31536000,immutable"}
    if etag:
        h["ETag"] = etag
    if last_modified:
        h["Last-Modified"] = last_modified
    return h


# -------------------------
# Manifest handling
# -------------------------

async def load_manifest(force: bool = False) -> dict:
    global _manifest_cache, _manifest_loaded_at
    if _manifest_cache and not force:
        return _manifest_cache
    if not MANIFEST_URL:
        raise RuntimeError("MANIFEST_URL is required")

    m = await fetch_json(MANIFEST_URL)
    _manifest_cache = m
    _manifest_loaded_at = time.time()
    return m


def manifest_mode(m: dict) -> str:
    if MODE in ("multi", "zip"):
        return MODE
    if m.get("mode") == "zip" and "zip" in m:
        return "zip"
    return "multi"


# -------------------------
# Multi-file serving
# -------------------------

async def proxy_capability(url: str, req: Request) -> StreamingResponse:
    # Forward range header if present and allowed
    headers = {}
    if ENABLE_RANGE_READS:
        rh = req.headers.get("range")
        if rh:
            headers["Range"] = rh

    try:
        upstream = await get_stream(url, headers=headers)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 416:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        raise

    # Pass through important headers
    status = upstream.status_code
    content_length = upstream.headers.get("Content-Length")
    content_type = upstream.headers.get("Content-Type", "application/octet-stream")
    etag = upstream.headers.get("ETag")
    last_modified = upstream.headers.get("Last-Modified")
    accept_ranges = upstream.headers.get("Accept-Ranges", "bytes" if ENABLE_RANGE_READS else "none")

    def gen():
        for chunk in upstream.iter_bytes():
            yield chunk

    resp = StreamingResponse(gen(), media_type=content_type, status_code=status)
    if content_length:
        resp.headers["Content-Length"] = content_length
    resp.headers.update(cache_headers(etag, last_modified))
    if accept_ranges:
        resp.headers["Accept-Ranges"] = accept_ranges
    return resp


# -------------------------
# Zip mode handling
# -------------------------

async def ensure_zip_ready(zip_cap_url: str):
    """
    Warm (download) if ≤ threshold, else keep lazy (head only).
    Also store ETag/Last-Modified for revalidation.
    """
    now = time.time()
    if _zip_state["url"] != zip_cap_url or (now - _zip_state["last_checked"] > ZIP_REVALIDATE_INTERVAL):
        _zip_state["last_checked"] = now
        r = await head(zip_cap_url)
        _zip_state["url"] = zip_cap_url
        _zip_state["etag"] = r.headers.get("ETag")
        _zip_state["last_modified"] = r.headers.get("Last-Modified")
        size = r.headers.get("Content-Length")
        _zip_state["size"] = int(size) if size else None

        # If already warm but ETag changed, drop cache
        if _zip_state["temp_path"] and _zip_state["etag"]:
            # No conditional GET here; if changed, we re-fetch on next warm
            pass

        if _zip_state["size"] is not None and _zip_state["size"] <= WARM_THRESHOLD_BYTES:
            # download and open
            await download_zip(zip_cap_url)
        else:
            # lazy mode; ensure no stale open zip
            close_zip()


def close_zip():
    with contextlib.suppress(Exception):
        if _zip_state["zip_obj"]:
            _zip_state["zip_obj"].close()
    _zip_state["zip_obj"] = None
    # temp_path is kept in lazy mode only when downloaded before; we can remove.
    tp = _zip_state.get("temp_path")
    if tp and Path(tp).exists():
        with contextlib.suppress(Exception):
            Path(tp).unlink()
    _zip_state["temp_path"] = None


import contextlib  # placed here to keep the function above concise

async def download_zip(zip_cap_url: str):
    r = await get_stream(zip_cap_url)
    # Write to a temp file
    fd, path = tempfile.mkstemp(prefix="gw-zip-", suffix=".zip")
    with os.fdopen(fd, "wb") as f:
        async for chunk in r.aiter_bytes():
            f.write(chunk)
    # Open zip
    zf = zipfile.ZipFile(path, "r")
    _zip_state["temp_path"] = path
    # Any existing open zip gets closed first
    close_zip()
    _zip_state["zip_obj"] = zf


def read_zip_member_bytes(zf: zipfile.ZipFile, member: str) -> bytes:
    with zf.open(member, "r") as fp:
        return fp.read()


async def serve_from_zip(path: str, req: Request) -> Response:
    """
    Serve a single zip member. For simplicity, we load the member fully.
    If you need true range on zip members, enable upstream range reading instead
    (gateway range support is mainly for multi-file proxied caps).
    """
    m = await load_manifest()
    entry = m.get("entry", "/index.html")
    zip_cap = m.get("zip", {}).get("url")
    if not zip_cap:
        raise HTTPException(status_code=500, detail="zip manifest missing capability url")

    await ensure_zip_ready(zip_cap)

    # Normalize and map to zip name
    rel = path
    if rel == "" or rel == "/":
        rel = entry
    if rel.startswith("/"):
        rel = rel[1:]

    # If warm: read locally. If lazy (no zip_obj), stream full zip then read member.
    if _zip_state["zip_obj"] is None:
        # lazy: fetch whole zip to a temp file for this read (simple & robust)
        await download_zip(zip_cap)

    zf: zipfile.ZipFile = _zip_state["zip_obj"]
    if rel not in zf.namelist():
        # try index.html fallback for SPA routes
        if "index.html" in zf.namelist():
            rel = "index.html"
        else:
            raise HTTPException(status_code=404, detail="file not found in zip")

    try:
        data = read_zip_member_bytes(zf, rel)
    except KeyError:
        raise HTTPException(status_code=404, detail="file not found in zip")

    # Guess a content type very lightly (optional)
    ctype = "application/octet-stream"
    if rel.endswith(".html"):
        ctype = "text/html; charset=utf-8"
    elif rel.endswith(".js"):
        ctype = "application/javascript"
    elif rel.endswith(".css"):
        ctype = "text/css; charset=utf-8"
    elif rel.endswith(".json"):
        ctype = "application/json"
    elif rel.endswith(".png"):
        ctype = "image/png"
    elif rel.endswith(".jpg") or rel.endswith(".jpeg"):
        ctype = "image/jpeg"
    elif rel.endswith(".svg"):
        ctype = "image/svg+xml"

    headers = cache_headers(_zip_state.get("etag"), _zip_state.get("last_modified"))
    headers["Accept-Ranges"] = "none"  # we serve full member

    return Response(content=data, media_type=ctype, headers=headers)


# -------------------------
# Routes
# -------------------------

@app.get("/__health")
async def health():
    try:
        m = await load_manifest()
        mode = manifest_mode(m)
        # Quick checks
        if mode == "multi":
            assets = m.get("assets", {})
            if not assets:
                raise ValueError("manifest assets empty")
            # test one small item
            any_url = next(iter(assets.values())).get("url")
            r = await _client.head(any_url)
            r.raise_for_status()
        else:
            zip_url = m.get("zip", {}).get("url")
            if not zip_url:
                raise ValueError("zip url missing")
            await ensure_zip_ready(zip_url)
        return PlainTextResponse("ok", status_code=200)
    except Exception as e:
        return PlainTextResponse(f"unhealthy: {e}", status_code=500)


@app.get("/{full_path:path}")
async def serve(full_path: str, request: Request, range: Optional[str] = Header(None)):
    m = await load_manifest()
    mode = manifest_mode(m)

    if mode == "multi":
        assets = m.get("assets", {})
        lookup = "/" + full_path if not full_path.startswith("/") else full_path
        if lookup == "/" or lookup == "":
            lookup = "/index.html"
        meta = assets.get(lookup)
        if not meta:
            # SPA fallback
            meta = assets.get("/index.html")
            if not meta:
                raise HTTPException(status_code=404, detail="Not found")
        url = meta.get("url")
        if not url:
            raise HTTPException(status_code=500, detail="missing asset url")
        return await proxy_capability(url, request)

    # zip mode
    return await serve_from_zip("/" + full_path, request)
