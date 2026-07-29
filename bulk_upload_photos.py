#!/usr/bin/env python3
"""
Laddar upp en hel mapp med matchbilder till Cloudflare R2 i ett svep,
och skapar en ny bildpost (content/posts/<slug>.md) med alla bilder
redan ifyllda i galleriet och omslagsbilden satt till den första bilden.

Användning:
    python3 bulk_upload_photos.py /sökväg/till/bildmapp

Efteråt: öppna filen i static/cms (osterbackaphoto.com/cms) eller redigera
content/posts/<slug>.md direkt för att fylla i sport, lag, resultat, plats
osv - bilderna är redan på plats så det återstår bara några få textfält.
"""

import sys
import re
import mimetypes
from pathlib import Path
from datetime import datetime

import boto3
import requests
from botocore.config import Config

# ── Samma R2-konfiguration som migrate_images_to_r2.py ─────────────────────────
R2_ACCESS_KEY_ID     = "9ee3d34d9109328ff783d9ec4232a963"
R2_SECRET_ACCESS_KEY = "0432d8202c3be2675bc5d09744c02e8274669a7db155c15a99a74259c2b54cfb"
R2_ENDPOINT          = "https://cab444a744a475ef6d605811c4f09051.r2.cloudflarestorage.com"
R2_BUCKET            = "osterbackaphoto-media"
R2_PUBLIC_URL        = "https://pub-ef305913c29145ed99390d0f52ff6dee.r2.dev"

POSTS_DIR = Path(__file__).parent / "content" / "posts"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

SPORT_OPTIONS = ["fotboll", "futsal", "innebandy", "basket", "tennis", "annat"]


def slugify(text):
    replacements = {"å": "a", "ä": "a", "ö": "o", "Å": "a", "Ä": "a", "Ö": "o", "é": "e"}
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    text = text.lower().strip()
    text = re.sub(r"[:''’`]", "", text)
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text


def ask(prompt, default=""):
    suffix = f" [{default}]" if default else ""
    val = input(f"{prompt}{suffix}: ").strip()
    return val if val else default


def yaml_str(value):
    escaped = str(value).replace('\\', '\\\\').replace('"', '\\"')
    return f'"{escaped}"'


def main():
    if len(sys.argv) < 2:
        print("Användning: python3 bulk_upload_photos.py /sökväg/till/bildmapp")
        sys.exit(1)

    folder = Path(sys.argv[1]).expanduser()
    if not folder.is_dir():
        print(f"Hittar ingen mapp: {folder}")
        sys.exit(1)

    photos = sorted(
        [p for p in folder.iterdir() if p.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda p: p.name,
    )
    if not photos:
        print(f"Hittade inga bilder (.jpg/.jpeg/.png/.webp) i {folder}")
        sys.exit(1)

    print(f"Hittade {len(photos)} bilder i {folder}\n")

    title = ""
    while not title:
        title = ask("Rubrik (t.ex. 'Seger mot IFK Exempel')")

    slug = slugify(title)
    target_path = POSTS_DIR / f"{slug}.md"
    if target_path.exists():
        print(f"\nEn post med slug '{slug}' finns redan ({target_path.name}). Avbryter.")
        print("Byt rubrik något, eller ta bort/döp om den befintliga filen först.")
        sys.exit(1)

    date_input = ask("Datum (ÅÅÅÅ-MM-DD, tom = idag)", datetime.now().strftime("%Y-%m-%d"))
    try:
        date_obj = datetime.strptime(date_input, "%Y-%m-%d")
    except ValueError:
        print(f"Ogiltigt datum '{date_input}', använder dagens datum istället.")
        date_obj = datetime.now()
    date_str = date_obj.strftime("%Y-%m-%dT%H:%M:%S")

    post_type = ask("Typ av post (match/other)", "match")
    print(f"Sportkategori(er) — välj bland: {', '.join(SPORT_OPTIONS)}")
    sports_input = ask("(kommaseparerat om flera, t.ex. 'fotboll')", "")
    sports = [s.strip() for s in sports_input.split(",") if s.strip()]

    sport = ask("Sport (visningsfält, tom = samma som sportkategori)", sports[0] if sports else "")
    club = ask("Klubb (valfritt)")
    series = ask("Serie / tävling (valfritt)")
    home_team = ask("Hemmalag (valfritt)")
    away_team = ask("Bortalag (valfritt)")
    home_score = ask("Hemmamål (valfritt, siffra)")
    away_score = ask("Bortamål (valfritt, siffra)")
    venue = ask("Plats / arena (valfritt)")

    print(f"\nLaddar upp {len(photos)} bilder till R2 ...\n")

    s3 = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )

    year_month = date_obj.strftime("%Y/%m")
    uploaded_urls = []
    failed = []

    for i, photo in enumerate(photos, start=1):
        key = f"wp-content/uploads/{year_month}/{slug}-{photo.name}"
        content_type = mimetypes.guess_type(photo.name)[0] or "image/jpeg"
        try:
            with open(photo, "rb") as f:
                s3.put_object(Bucket=R2_BUCKET, Key=key, Body=f.read(), ContentType=content_type)
            url = f"{R2_PUBLIC_URL}/{key}"
            uploaded_urls.append(url)
            print(f"  [{i}/{len(photos)}] ✓ {photo.name}")
        except Exception as e:
            print(f"  [{i}/{len(photos)}] ✗ {photo.name} — {e}")
            failed.append(photo.name)

    if not uploaded_urls:
        print("\nInga bilder laddades upp, avbryter (skapar ingen post).")
        sys.exit(1)

    featured_image = uploaded_urls[0]

    lines = ["---"]
    lines.append(f"title: {yaml_str(title)}")
    lines.append(f"date: {date_str}")
    lines.append(f"slug: {yaml_str(slug)}")
    lines.append(f"post_type: {yaml_str(post_type)}")
    if sport:
        lines.append(f"sport: {yaml_str(sport)}")
    if sports:
        lines.append("sports:")
        for s in sports:
            lines.append(f"  - {yaml_str(s)}")
    if club:
        lines.append(f"club: {yaml_str(club)}")
    if series:
        lines.append(f"series: {yaml_str(series)}")
    if home_team:
        lines.append(f"home_team: {yaml_str(home_team)}")
    if away_team:
        lines.append(f"away_team: {yaml_str(away_team)}")
    if home_score:
        lines.append(f"home_score: {home_score}")
    if away_score:
        lines.append(f"away_score: {away_score}")
    if venue:
        lines.append(f"venue: {yaml_str(venue)}")
    lines.append(f"featured_image: {yaml_str(featured_image)}")
    lines.append("images:")
    for url in uploaded_urls:
        lines.append(f"  - {yaml_str(url)}")
    lines.append("---")
    lines.append("")

    target_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n=== Klart ===")
    print(f"Uppladdade: {len(uploaded_urls)}  Misslyckade: {len(failed)}")
    if failed:
        print("Misslyckade filer:", ", ".join(failed))
    print(f"\nNy post skapad: content/posts/{slug}.md")
    print("Öppna den i osterbackaphoto.com/cms (eller redigera filen direkt) för att")
    print("fylla i det som saknas (t.ex. kort beskrivning), och publicera som vanligt.")


if __name__ == "__main__":
    main()
