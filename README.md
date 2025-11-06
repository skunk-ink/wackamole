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

### 4. Setup is complete.
You can now run `publish.py` and `gateway.py` from the `wackamole` root directory.

## Publisher (`publish.py`)

This script is used to create a `manifest.json` that is then zipped together with the users website and uploaded to the Sia network through an indexd node. The script uses `website/` by default as the location of the users website. This can be changed by using the `--site` flag.

| Argument | Description | Default | Required |
| ----- | ----- | ----- | ----- |
|  |  |  |  |
| `--indexd` | Remote indexd URL, e.g. https://indexd.example.com |  | ✔ |
| `--site` | Path to built site directory. | `website/` |  |
| `--out` | Where to write manifest. | `manifest.json` |  |
| `--share-days` | How long the share link is valid | `365` |  |

### Example:
1. Create a new file named `index.html` inside of the `website/` folder. Copy an paste the following into the file and save.
    ```html
    <html>
        <title>Hello World!</title>
        <body>
            Hello World!
        </body>
    </html>
    ```

2. Run `publish.py` to upload your site to the Sia network.

    Run:
    ```shell
    python publish.py --indexd https://indexd.yourdomain.tld
    ```
    When prompted for a mnemonic, you can either leave it empty to generate a new app seed, or enter a pre-existing seed.

    Next you will be prompted for app authorization inside of your browser. Paste your app key and click `Accept`.

    Your website will then be uploaded to the network and once completed, you will receive a share url.

    **Output**
    ```shell
    Enter mnemonic (or leave empty to generate new):


    mnemonic: seed urban monitor error upon number license float artefact useless lucky correct

    Requesting app authorization…
    Open this URL to approve access:
    https://indexd.skunk.ink/auth/connect/c1c803041792c7e0b08dc01e7c09fbf2
    App authorized.

    Created zip: C:\Users\murra\AppData\Local\Temp\site-1762469129.zip (208.0 B)
    Using erasure coding: data=3, parity=9, inflight=6
    Uploading to Sia via indexd…
    208.0 B / 208.0 B (100.0%)

    ✅ Upload complete.
    Share URL (give this to a gateway):
    https://indexd.skunk.ink/objects/be096a7bbe67b3e3d1ba075c56b67d5e5c8a97b337b4d2e770c0d620e51ea29d/shared?sv=1794005151&sc=fiYwiWCw8ZolPoj2NA9IOgEf2iNFKND6hAUBFAcNzv4%3D&ss=6VWZ_iJ7tsuZZZozkoRXQLL9GiEvRVQly7C3ZERzBSCed2jQ3EEh44Z20HNjl_LjyAMpFR_8pBA5-Vxcc-fQDA%3D%3D#encryption_key=RDxfFXrc6GdMzAYwBv_istRyZLUE5FLdtCrtod81jTA=

    Wrote manifest to: manifest.json
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