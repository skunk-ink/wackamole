# wackamole
Wack-A-Mole is a static website publisher and gateway for hosting websites on the Sia Network.

1. Clone Wackamole and `cd` in to the folder.
```shell
git clone https://github.com/skunk-ink/wackamole
cd wackamole
```

2. Clone Sia's SDK and build SDK from wackamole root
```shell
git clone https://github.com/siafoundation/sia-sdk-rs
```

3. `cd` into the Sia SDK and build the SDK for your system:
Linux:
```shell
cd sia-sdk-rs
cargo build --release -p indexd_ffi
cargo run -p indexd_ffi --bin uniffi-bindgen generate --library target/release/libindexd_ffi.so --language python --out-dir ../
mv target/release/libindexd_ffi.so ../
```

MacOS:
```shell
cd sia-sdk-rs
cargo build --release --package=indexd_ffi
cargo run --package=indexd_ffi --bin uniffi-bindgen generate --library target/release/libindexd_ffi.dylib --language python --out-dir ../
mv target/release/libindexd_ffi.dylib ../
```

Windows:
```powershell
cd sia-sdk-rs
cargo build --release --package indexd_ffi
cargo run --package indexd_ffi --bin uniffi-bindgen -- generate --library .\target\release\indexd_ffi.dll --language python --out-dir ../
mv target\release\indexd_ffi.dll ../
```

4. Return to `wackamole` root and run `publish_static.py` to publish a website on Sia, and run `gateway.py` to host a gateway to the site.

### Publisher (`publish_static.py`)

| Argument | Description | Default |
| ----- | ----- | ----- |
|  |  |  |
| `--indexd` | Remote indexd URL, e.g. https://indexd.example.com | *(none)* |
| `--site` | Path to built site directory. | `dist/` |
| `--out` | Where to write manifest. | `manifest.json` |
| `--share-days` | How long the share link is valid | `365` |

**Example:**
```shell
python publish_static.py --indexd https://indexd.yourdomain.tld --site ./dist --out manifest.json
```

### Gateway (`gateway.py`)

**Example:**
```shell
python gateway.py --host 127.0.0.1 --share <INDEXD SHARE URL>
```