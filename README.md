# wackamole
Wack-A-Mole is a decentralized arcade hosted on the Sia network.

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