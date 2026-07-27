#!/usr/bin/env python3
"""
Migrerar bilder från WordPress CDN till Cloudflare R2.
Läser alla markdown-filer, laddar ner bilder och laddar upp till R2.
Uppdaterar URL:erna i markdown-filerna automatiskt.
"""

import os
import re
import time
import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import boto3
import requests
from botocore.config import Config

# ── Konfiguration ──────────────────────────────────────────────────────────────
R2_ACCESS_KEY_ID     = "9ee3d34d9109328ff783d9ec4232a963"
R2_SECRET_ACCESS_KEY = "0432d8202c3be2675bc5d09744c02e8274669a7db155c15a99a74259c2b54cfb"
R2_ENDPOINT          = "https://cab444a744a475ef6d605811c4f09051.r2.cloudflarestorage.com"
R2_BUCKET            = "osterbackaphoto-media"
R2_PUBLIC_URL        = "https://pub-ef305913c29145ed99390d0f52ff6dee.r2.dev"

POSTS_DIR = Path(__file__).parent / "content" / "posts"
# ──────────────────────────────────────────────────────────────────────────────

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY_ID,
    aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    config=Config(signature_version="s3v4"),
    region_name="auto",
)

uploaded_cache = {}   # original_url → r2_url
failed = []
skipped = 0
uploaded = 0

def r2_key_from_url(url):
    """Behåller originalmappsstrukturen: wp-content/uploads/2024/07/foto.jpg"""
    parsed = urlparse(url)
    path = parsed.path.lstrip("/")
    return path

def upload_image(url):
    global skipped, uploaded
    if url in uploaded_cache:
        return uploaded_cache[url]

    key = r2_key_from_url(url)
    r2_url = f"{R2_PUBLIC_URL}/{key}"

    # Kolla om filen redan finns i R2
    try:
        s3.head_object(Bucket=R2_BUCKET, Key=key)
        uploaded_cache[url] = r2_url
        skipped += 1
        return r2_url
    except Exception:
        pass

    # Ladda ner från WordPress
    try:
        resp = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            print(f"  ✗ HTTP {resp.status_code}: {url}")
            failed.append(url)
            return url
    except Exception as e:
        print(f"  ✗ Download error: {url} — {e}")
        failed.append(url)
        return url

    # Ladda upp till R2
    content_type = resp.headers.get("Content-Type") or mimetypes.guess_type(url)[0] or "image/jpeg"
    content_type = content_type.split(";")[0].strip()

    try:
        s3.put_object(
            Bucket=R2_BUCKET,
            Key=key,
            Body=resp.content,
            ContentType=content_type,
        )
        uploaded_cache[url] = r2_url
        uploaded += 1
        print(f"  ✓ {key}")
        return r2_url
    except Exception as e:
        print(f"  ✗ Upload error: {key} — {e}")
        failed.append(url)
        return url

def process_file(path):
    content = path.read_text(encoding="utf-8")
    original = content

    # Hitta alla WordPress-bild-URL:er
    wp_pattern = re.compile(
        r'https?://(?:osterbackaphoto\.com|osterbackaphoto\.wordpress\.com)'
        r'/wp-content/uploads/[^\s"\'\]\)>]+'
    )

    urls = list(set(wp_pattern.findall(content)))
    if not urls:
        return

    print(f"\n{path.name} ({len(urls)} bilder)")
    for url in urls:
        new_url = upload_image(url)
        if new_url != url:
            content = content.replace(url, new_url)
        time.sleep(0.1)  # skonsam mot WordPress CDN

    if content != original:
        path.write_text(content, encoding="utf-8")

# ── Kör ───────────────────────────────────────────────────────────────────────
print("=== Bildmigrering WordPress → Cloudflare R2 ===\n")
md_files = list(POSTS_DIR.glob("*.md"))
print(f"Hittade {len(md_files)} markdown-filer\n")

for md in sorted(md_files):
    process_file(md)

print(f"\n=== Klart ===")
print(f"Uppladdade: {uploaded}")
print(f"Redan i R2: {skipped}")
print(f"Misslyckade: {len(failed)}")
if failed:
    print("\nMisslyckade URL:er:")
    for u in failed:
        print(f"  {u}")
