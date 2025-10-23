#!/usr/bin/env python3
# Python 3.12+
import asyncio
import concurrent.futures
import contextlib
import dataclasses
import functools
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx
from tqdm.asyncio import tqdm_asyncio
from tqdm import tqdm
import zipfile

# -------------------------
# Environment configuration
# -------------------------

DIST_DIR = Path(os.getenv("DIST_DIR", "dist"))
MODE = os.getenv("MODE", "zip").lower()  # "zip" or "multi"
MANIFEST_OUT = Path(os.getenv("MANIFEST_OUT", "manifest.json"))
ZIP_MANIFEST_OUT = Path(os.getenv("ZIP_MANIFEST_OUT", "zip-manifest.json"))

# Indexd/Sia
INDEXD_URL = os.getenv("INDEXD_URL", "http://localhost:4381")
APP_ID_HEX = os.getenv("APP_ID_HEX", "")  # required for publishing
APP_RECOVERY_PHRASE = os.getenv("APP_RECOVERY_PHRASE", "")  # required for publishing

# Concurrency & chunking
UPLOAD_CONCURRENCY = int(os.getenv("UPLOAD_CONCURRENCY", "8"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", str(4 * 1024 * 1024)))  # 4 MiB

# S5/IPFS publishing
S5_BASE_URL = os.getenv("S5_BASE_URL", "https://s5.example/api")
S5_UPLOAD_PATH = os.getenv("S5_UPLOAD_PATH", "/upload")  # appended to base
IPFS_API_URL = os.getenv("IPFS_API_URL", "http://127.0.0.1:5001/api/v0/add?pin=true")

# Deterministic zip
ZIP_NAME = os.getenv("ZIP_NAME", "site.zip")

# Misc
TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "60"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def log(msg: str):
    if LOG_LEVEL in ("DEBUG", "INFO"):
        print(msg, flush=True)


# -------------------------
# Deterministic zipping
# -------------------------

def deterministic_zip(src_dir: Path, zip_path: Path) -> Tuple[int, str]:
    """
    Create a deterministic zip: fixed timestamps, sorted entries, no extra attrs.
    Returns (size_bytes, sha256_hex).
    """
    if not src_dir.exists():
        raise FileNotFoundError(f"dist dir not found: {src_dir}")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in sorted(src_dir.rglob("*")):
            if p.is_dir():
                continue
            arcname = str(p.relative_to(src_dir)).replace("\\", "/")
            # Fixed DOS timestamp (1980-01-01 00:00:00)
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with p.open("rb") as f:
                data = f.read()
            zf.writestr(info, data)

    size = zip_path.stat().st_size
    h = hashlib.sha256()
    with zip_path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return size, h.hexdigest()


# -------------------------
# Indexd FFI wrapper (thin)
# -------------------------

class IndexdError(Exception):
    pass


@dataclasses.dataclass
class CapLink:
    url: str  # capability URL


class IndexdFFI:
    """
    A thin wrapper around the Rust FFI (indexd_ffi). We keep it import-late and
    do blocking calls in a threadpool so the outer code can be async.
    """

    def __init__(self, base_url: str, app_id_hex: str, recovery_phrase: str):
        self.base_url = base_url
        self.app_id_hex = app_id_hex
        self.recovery_phrase = recovery_phrase
        # Placeholder: import/initialize the real SDK here.
        # from indexd_ffi import Sdk
        # self.sdk = Sdk(base_url, app_id_hex, recovery_phrase)

    def _upload_bytes(self, data: bytes) -> CapLink:
        # Pseudocode for real SDK:
        # upload = self.sdk.upload(UploadOptions(chunk_size=...))
        # upload.write(data)
        # obj = upload.finalize()
        # shared = self.sdk.share_object(obj.id)
        # return CapLink(url=shared.url)
        # For now, require a compatible HTTP gateway that accepts raw data:
        raise IndexdError("Indexd FFI upload not implemented in this stub. Integrate your SDK here.")

    def upload_file(self, path: Path) -> CapLink:
        with path.open("rb") as f:
            data = f.read()
        return self._upload_bytes(data)


# -------------------------
# Async uploader helpers
# -------------------------

async def upload_paths_via_indexd(
    paths: List[Path],
    indexd: IndexdFFI,
    concurrency: int,
) -> Dict[str, CapLink]:
    results: Dict[str, CapLink] = {}
    loop = asyncio.get_running_loop()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
        tasks = []
        for p in paths:
            rel = "/" + str(p).replace("\\", "/")
            fn = functools.partial(indexd.upload_file, p)
            tasks.append(loop.run_in_executor(pool, fn))

        for rel, fut in tqdm(zip(["/" + str(p.relative_to(DIST_DIR)).replace("\\", "/") for p in paths], tasks),
                             total=len(tasks), desc="Uploading", unit="file"):
            try:
                cap = await fut
                results[rel] = cap
            except Exception as e:
                raise IndexdError(f"failed to upload {rel}: {e}") from e
    return results


# -------------------------
# S5/IPFS publishing
# -------------------------

async def publish_to_s5(manifest_bytes: bytes) -> str:
    """
    POST multipart to S5; return CID string.
    """
    fname = "manifest.json"
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        url = S5_BASE_URL.rstrip("/") + "/" + S5_UPLOAD_PATH.lstrip("/")
        files = {"file": (fname, manifest_bytes, "application/json")}
        try:
            resp = await client.post(url, files=files)
            resp.raise_for_status()
            data = resp.json()
            # Expect { cid: "..." } or similar
            cid = data.get("cid") or data.get("CID") or data.get("hash")
            if not cid:
                raise ValueError(f"unexpected S5 response: {data}")
            return cid
        except Exception as e:
            raise RuntimeError(f"S5 publish failed: {e}") from e


async def publish_to_ipfs(manifest_bytes: bytes) -> str:
    """
    POST /api/v0/add?pin=true ; return Hash.
    """
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        files = {"file": ("manifest.json", manifest_bytes, "application/json")}
        try:
            resp = await client.post(IPFS_API_URL, files=files)
            resp.raise_for_status()
            data = resp.json()
            h = data.get("Hash")
            if not h:
                raise ValueError(f"unexpected IPFS response: {data}")
            return h
        except Exception as e:
            raise RuntimeError(f"IPFS publish failed: {e}") from e


# -------------------------
# Main publish flows
# -------------------------

def build_multi_manifest(mapping: Dict[str, CapLink]) -> dict:
    return {
        "assets": {path: {"type": "shared", "url": cap.url} for path, cap in mapping.items()}
    }


def build_zip_manifest(cap: CapLink, entry: str = "/index.html") -> dict:
    return {
        "mode": "zip",
        "entry": entry,
        "zip": {"type": "shared", "url": cap.url},
    }


async def run_zip_mode():
    indexd = IndexdFFI(INDEXD_URL, APP_ID_HEX, APP_RECOVERY_PHRASE)

    tmpdir = Path(tempfile.mkdtemp(prefix="pubzip-"))
    zip_path = tmpdir / ZIP_NAME
    try:
        size, sha = deterministic_zip(DIST_DIR, zip_path)
        log(f"Deterministic zip created: {zip_path} ({size} bytes, sha256={sha})")

        # Upload zip to Indexd
        try:
            cap = indexd.upload_file(zip_path)
        except IndexdError as e:
            print(f"[ERROR] Indexd upload failed: {e}")
            sys.exit(2)

        manifest = build_zip_manifest(cap)
        manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()

        # Write local manifest
        ZIP_MANIFEST_OUT.write_bytes(manifest_bytes)
        log(f"Wrote {ZIP_MANIFEST_OUT}")

        # Publish to S5 / IPFS (best effort, report both)
        s5_cid = ipfs_cid = None
        try:
            s5_cid = await publish_to_s5(manifest_bytes)
            print(f"S5_CID={s5_cid}")
        except Exception as e:
            print(f"[WARN] S5 publish error: {e}")

        try:
            ipfs_cid = await publish_to_ipfs(manifest_bytes)
            print(f"IPFS_CID={ipfs_cid}")
        except Exception as e:
            print(f"[WARN] IPFS publish error: {e}")

        print("OK zip mode.")
    finally:
        with contextlib.suppress(Exception):
            shutil.rmtree(tmpdir)


async def run_multi_mode():
    indexd = IndexdFFI(INDEXD_URL, APP_ID_HEX, APP_RECOVERY_PHRASE)
    files = [p for p in DIST_DIR.rglob("*") if p.is_file()]
    if not files:
        print(f"[ERROR] No files found in {DIST_DIR}")
        sys.exit(2)

    # Upload in parallel
    try:
        mapping = await upload_paths_via_indexd(files, indexd, UPLOAD_CONCURRENCY)
    except Exception as e:
        print(f"[ERROR] Uploads failed: {e}")
        sys.exit(2)

    manifest = build_multi_manifest(mapping)
    manifest_bytes = json.dumps(manifest, indent=2, sort_keys=True).encode()
    MANIFEST_OUT.write_bytes(manifest_bytes)
    log(f"Wrote {MANIFEST_OUT}")

    # Publish to S5/IPFS
    s5_cid = ipfs_cid = None
    try:
        s5_cid = await publish_to_s5(manifest_bytes)
        print(f"S5_CID={s5_cid}")
    except Exception as e:
        print(f"[WARN] S5 publish error: {e}")

    try:
        ipfs_cid = await publish_to_ipfs(manifest_bytes)
        print(f"IPFS_CID={ipfs_cid}")
    except Exception as e:
        print(f"[WARN] IPFS publish error: {e}")

    print("OK multi-file mode.")


def main():
    if not APP_ID_HEX or not APP_RECOVERY_PHRASE:
        print("[ERROR] APP_ID_HEX and APP_RECOVERY_PHRASE are required for publishing.")
        sys.exit(2)

    if MODE not in ("zip", "multi"):
        print(f"[ERROR] MODE must be 'zip' or 'multi', got {MODE}")
        sys.exit(2)

    if not DIST_DIR.exists():
        print(f"[ERROR] DIST_DIR not found: {DIST_DIR}")
        sys.exit(2)

    if MODE == "zip":
        asyncio.run(run_zip_mode())
    else:
        asyncio.run(run_multi_mode())


if __name__ == "__main__":
    main()
