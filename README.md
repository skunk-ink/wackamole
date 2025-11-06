# wackamole
Wack-A-Mole is a static website publisher and gateway for hosting websites on the Sia Network.

## Setup
### 1. Clone the `wackamole` repository and `cd` in to the folder.
```shell
git clone https://github.com/skunk-ink/wackamole
cd wackamole
```

### 2. From the `wackamole` root directory, clone Sia's SDK and `cd` into the folder.
```shell
git clone https://github.com/siafoundation/sia-sdk-rs
cd sia-sdk-rs
```

### 3. `cd` into the Sia SDK and build the SDK for your system:
#### Linux:
```shell
cargo build --release -p indexd_ffi
cargo run -p indexd_ffi --bin uniffi-bindgen generate --library target/release/libindexd_ffi.so --language python --out-dir ../
mv target/release/libindexd_ffi.so ../
cd ../
```

#### MacOS:
```shell
cargo build --release --package=indexd_ffi
cargo run --package=indexd_ffi --bin uniffi-bindgen generate --library target/release/libindexd_ffi.dylib --language python --out-dir ../
mv target/release/libindexd_ffi.dylib ../
cd ../
```

#### Windows:
```powershell
cargo build --release --package indexd_ffi
cargo run --package indexd_ffi --bin uniffi-bindgen -- generate --library .\target\release\indexd_ffi.dll --language python --out-dir ../
mv target\release\indexd_ffi.dll ../
cd ../
```

### 4. From the `wackamole` root directory run `publish.py` to publish your website on Sia, and run `gateway.py` to host a gateway to the site.

## Publisher (`publish.py`)

This script is used to create a `manifest.json` that is then zipped together with the users website and uploaded to the Sia network through an indexd node. The script uses `website/` by default as the location of the users website. This can be changed by using the `--site` flag.

| Argument | Description | Default | Required |
| ----- | ----- | ----- | ----- |
|  |  |  |  |
| `--indexd` | Remote indexd URL, e.g. https://indexd.example.com |  | ✔ |
| `--site` | Path to built site directory. | `website/` |  |
| `--out` | Where to write manifest. | `manifest.json` |  |
| `--share-days` | How long the share link is valid | `365` |  |

**Example:**
```shell
python publish.py --indexd https://indexd.yourdomain.tld
```

## Gateway (`gateway.py`)

This script creates a gateway that can access websites stored on Sia using the websites share URL.

| Argument | Description | Default | Required |
| ----- | ----- | ----- | ----- |
|  |  |  |  |
| `--share` | Share URL printed by publish.py |  | ✔ |
| `--indexd` | Indexd base URL (auto-detected from share if omitted) |  |  |
| `--host` | Host's IP address | `127.0.0.1` |  |
| `--port` | Port number to host on | `8787` |  |

**Example:**
```shell
python gateway.py --share <INDEXD SHARE URL>
```