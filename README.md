# Wack-A-Mole Site Decentralization
**Decentralized Static-Site Publisher & Gateway for the Sia Network**

Wack-A-Mole is a publishing framework that lets you upload any static website to the **Sia Network** through a remote **Indexd** node and serve it directly from decentralized storage — no central server required.

It includes:

- **`publish.py`** — Uploads your static site (zipped) to Sia via Indexd.  
- **`gateway.py`** — Runs a stateless HTTP gateway that serves your site straight from its decentralized zip.

---

## Table of Contents
- [Architecture Overview](#architecture-overview)
- [Setup](#setup)
  - [1. Clone Repositories](#1-clone-repositories)
  - [2. Build the FFI Bridge](#2-build-the-ffi-bridge)
  - [3. Environment Setup](#3-environment-setup)
- [Usage](#usage)
  - [Publisher (`publish.py`)](#publisher-publishpy)
  - [Gateway (`gatewaypy`)](#gateway-gatewaypy)
- [Configuration](#configuration)
- [Health Checks](#health-checks)
- [Troubleshooting](#troubleshooting)
- [Security Notes](#security-notes)
- [Version History](#version-history)
- [License](#license)

---

## Architecture Overview

```
[Local Site] → publish.py → [Indexd Node] → [Sia Network]
                                  ↓
                         gateway.py (FastAPI)
                                  ↓
                             [Browser]
```

- **Indexd Node** — Bridges your data into the Sia decentralized storage network.  
- **Publisher** — Packages and uploads your local website as a shareable object.  
- **Gateway** — Fetches and serves sites directly from their decentralized zip share.  
- **End-User** — Views the site via any gateway node, using the shared capability URL.

---

## Setup

### 1. Clone Repositories
```bash
git clone https://github.com/skunk-ink/wackamole
cd wackamole
```

Clone and build the Sia SDK:
```bash
git clone https://github.com/siafoundation/sia-sdk-rs
cd sia-sdk-rs
```

### 2. Build the FFI Bridge
You’ll need to compile the **`indexd_ffi`** dynamic library used by both scripts.

#### Linux
```bash
cargo build --release -p indexd_ffi
cargo run -p indexd_ffi --bin uniffi-bindgen generate   --library target/release/libindexd_ffi.so   --language python --out-dir ../
mv target/release/libindexd_ffi.so ../
```

#### macOS
```bash
cargo build --release -p indexd_ffi
cargo run -p indexd_ffi --bin uniffi-bindgen generate   --library target/release/libindexd_ffi.dylib   --language python --out-dir ../
mv target/release/libindexd_ffi.dylib ../
```

#### Windows (PowerShell)
```powershell
cargo build --release -p indexd_ffi
cargo run -p indexd_ffi --bin uniffi-bindgen -- generate --library .\target\release\indexd_ffi.dll --language python --out-dir ../
mv target\release\indexd_ffi.dll ../
```

Return to the main folder:
```bash
cd ../wackamole
```

### 3. Environment Setup

Create a `.env` file in the project root:
```ini
APP_ID_HEX=<your app id hex>
MNEMONIC=<your seed phrase>
INDEXD_URL=https://indexd.example.com
APP_NAME="My Static Site"
APP_DESC="Publishes static sites to Sia via Indexd"
SERVICE_URL="https://example.com"
LOGO_URL="https://example.com/logo.png"
CALLBACK_URL="https://example.com/auth/callback"
```

---

## Usage

### Publisher (`publish.py`)

Uploads your site to the Sia network through an Indexd node.

| Argument | Description | Default |
|-----------|-------------|----------|
| `--indexd` | Remote Indexd URL | `$INDEXD_URL` |
| `--site` | Path to built site directory | `website/` |
| `--out` | Manifest output path | `manifest.json` |
| `--app-name`, `--app-desc`, `--service-url`, `--logo-url`, `--callback-url` | Optional metadata | from `.env` |
| `--share-days` | How long the share link is valid | `365` |
| `--data`, `--parity` | Manual erasure coding overrides | smart defaults |
| `--inflight` | Parallel shard uploads | `6` |
| `--chunk-mib` | Upload chunk size | `1` |

#### Example
```bash
python publish.py --indexd https://indexd.skunk.ink
```

Output:
```text
Created zip: /tmp/site-1762469129.zip (208.0 B)
Uploading to Sia via Indexd...
✅ Upload complete.

Share URL (give this to a gateway):
https://indexd.skunk.ink/objects/<hash>/shared?...#encryption_key=...
Wrote manifest to: manifest.json
```

---

### Gateway (`gateway.py`)

Runs a FastAPI web server that fetches and serves your site directly from its shared zip.

| Argument | Description | Default |
|-----------|-------------|----------|
| `--share` | Share URL from the publisher | *required* |
| `--indexd` | Base URL (auto-detected if omitted) | — |
| `--env` | Path to `.env` file | `.env` |
| `--host` | Bind address | `127.0.0.1` |
| `--port` | Port to listen on | `8787` |

#### Example
```bash
python gateway.py --share "https://indexd.skunk.ink/objects/<hash>/shared?...#encryption_key=..."
```

Output:
```text
Loaded ZIP with 42 entries.
Try: http://127.0.0.1:8787/
Uvicorn running on http://127.0.0.1:8787 (Press CTRL+C to quit)
```

---

## Configuration

### Environment Variables
| Variable | Purpose |
|-----------|----------|
| `APP_ID_HEX` | Application identity (hex) |
| `MNEMONIC` | App seed phrase |
| `INDEXD_URL` | Default remote Indexd node |
| `APP_NAME` / `APP_DESC` | Metadata for shared objects |
| `SERVICE_URL`, `LOGO_URL`, `CALLBACK_URL` | Optional URLs used in Indexd app registration |

---

## Health Checks

Each running gateway exposes:
```
GET /__health
```
Returns `200 OK` if the site zip is loaded and accessible.

---

## Security Notes

- **Keep your mnemonic private** — it’s your signing seed.  
- Share URLs contain **capability tokens**; treat them as sensitive.  
- Use short `--share-days` for temporary content.  
- Run gateways in isolated environments when possible.

---

## License

See [LICENSE](LICENSE).
