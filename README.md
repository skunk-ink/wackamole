# wackamole
Wack-A-Mole is a decentralized arcade hosted on the Sia network.

## Environment variable documentation

### Publisher (`publish_static.py`)

| Variable | Default | Description |
| ----- | ----- | ----- |
|  |  |  |
| `DIST_DIR` | `dist` | Local build directory to publish. |
| `MODE` | `zip` | `zip` or `multi`. |
| `MANIFEST_OUT` | `manifest.json` | Output file for multi-file manifest. |
| `ZIP_MANIFEST_OUT` | `zip-manifest.json` | Output for zip manifest. |
| `INDEXD_URL` | `http://localhost:4381` | Your remote Indexd base URL. |
| `APP_ID_HEX` | *(none)* | Indexd App ID (hex). **Required**. |
| `APP_RECOVERY_PHRASE` | *(none)* | Indexd recovery phrase. **Required**. |
| `UPLOAD_CONCURRENCY` | `8` | Max concurrent file uploads (multi-file). |
| `CHUNK_SIZE` | `4194304` | Chunk size (bytes) for SDK write() if you wire it. |
| `S5_BASE_URL` | `https://s5.example/api` | S5 API base. |
| `S5_UPLOAD_PATH` | `/upload` | Upload path appended to `S5_BASE_URL`. |
| `IPFS_API_URL` | `http://127.0.0.1:5001/api/v0/add?pin=true` | IPFS API add endpoint. |
| `ZIP_NAME` | `site.zip` | Name of the local zip artifact. |
| `HTTP_TIMEOUT` | `60` | Network timeout (s) for S5/IPFS. |
| `LOG_LEVEL` | `INFO` | `DEBUG` or `INFO`. |

**Notes**

* Replace `IndexdFFI` stub with your actual `indexd_ffi` integration (`Sdk`, `upload`, `write`, `finalize`, `share_object`).

* The code prints `S5_CID=` and `IPFS_CID=` upon successful manifest publish.

### Gateway (`gateway.py`)

| Variable | Default | Description |
| ----- | ----- | ----- |
| `MANIFEST_URL` | *(none)* | URL to the manifest JSON (S5/IPFS gateway URL). **Required** |
| `MODE` | `auto` | `auto`, `multi`, or `zip`. |
| `WARM_THRESHOLD_BYTES` | `209715200` (200MB) | Warm zip when size ≤ threshold; else lazy. |
| `ZIP_REVALIDATE_INTERVAL` | `300` | Head/etag check interval (s). |
| `HTTP_TIMEOUT` | `30` | Upstream timeout (s). |
| `MAX_STREAMS` | `64` | Reserved for future connection limiting (currently not enforced). |
| `ENABLE_RANGE_READS` | `true` | Enable Range pass-through for multi-file proxy. |
| `LOG_LEVEL` | `INFO` | `DEBUG` or `INFO`. |

**Behavior**

* **Multi-file**: proxies capability URLs; forwards `Range` if enabled.

* **Zip**: serves members from a warmed or lazily downloaded zip; strong caching (`ETag`, `Last-Modified` if upstream provided).

* `/__health`: loads manifest and verifies at least one asset (multi) or the zip head (zip).

---

## Post-deployment checklist

- [ ] **Publisher secrets**: Ensure `APP_ID_HEX` and `APP_RECOVERY_PHRASE` are stored securely (not in Git). Gateways need **no secrets**.

- [ ] **Publish flow**: Run `publish_static.py` → capture `S5_CID` / `IPFS_CID`.

- [ ] **DNSLink**: Run `update_dnslink.py` (manual) and add TXT records:  
       `dnslink=/s5/<S5_CID>` and optionally `dnslink=/ipfs/<IPFS_CID>`.

- [ ] **Multi-region gateways**: Deploy at least **2** gateways in different jurisdictions/clouds. Point both to the same `MANIFEST_URL`.

- [ ] **Health probes**: Configure uptime checks hitting `/__health` every minute.

- [ ] **Caching/CDN**: Optionally front gateways with neutral CDNs that respect immutable caching.

- [ ] **Monitoring**: Track gateway `5xx`, latency, and upstream failure rates.

- [ ] **Backups**: Keep a copy of local `manifest.json`/`zip-manifest.json` and your build artifacts.

- [ ] **ETag/Last-Modified**: Confirm upstream Indexd/HTTP sources send validators; ensure gateway logs show periodic revalidation.

---

# **Optional enhancements**

1. **HTTP Range** (zip members):  
    Implement an in-zip range server that parses `Range` headers against the uncompressed member by using `ZipExtFile.seek()` (Python 3.11+) when feasible. This allows partial reads for video/audio packed in the zip.

2. **Small-file packer** (multi-file mode):  
    Auto-pack tiny assets into a “spritesheet zip” to reduce many small network fetches, while still keeping large assets separate.

3. **Multi-gateway mirror guide**:

   * Put 3 gateways behind anycast or geo-DNS.

   * Health-based DNS failover.

   * Optional HTTP/3 termination.

4. **Automated monitoring script**:  
    A small Python cron job that fetches `/__health`, logs metrics, and alerts on failures (Slack/webhook).  
