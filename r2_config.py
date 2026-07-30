"""
Läser R2-uppgifter från en lokal .env-fil (som INTE ska committas till Git).

Skapa en fil som heter ".env" i samma mapp som detta skript, med innehållet:

    R2_ACCESS_KEY_ID=din-access-key
    R2_SECRET_ACCESS_KEY=din-secret-key
    R2_ENDPOINT=https://xxxxxxxx.r2.cloudflarestorage.com
    R2_BUCKET=osterbackaphoto-media
    R2_PUBLIC_URL=https://pub-xxxxxxxx.r2.dev

Filen .env är listad i .gitignore och hamnar aldrig i Git.
"""

import os
from pathlib import Path

ENV_PATH = Path(__file__).parent / ".env"

REQUIRED_KEYS = [
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_ENDPOINT",
    "R2_BUCKET",
    "R2_PUBLIC_URL",
]


def _load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def load_r2_config():
    _load_dotenv(ENV_PATH)
    missing = [k for k in REQUIRED_KEYS if not os.environ.get(k)]
    if missing:
        print("Saknar R2-uppgifter:", ", ".join(missing))
        print(f"Skapa filen {ENV_PATH} enligt instruktionerna högst upp i r2_config.py")
        raise SystemExit(1)
    return {key: os.environ[key] for key in REQUIRED_KEYS}
