#!/usr/bin/env python3
"""
OsterbackaPhoto Shop – uppladdare.

Tar en mapp med RENA JPEG-original exporterade från Lightroom och:
  1. läser nyckelord home:NN / away:NN (stora/små bokstäver spelar ingen roll),
     tagningstid och kontrollerar att ingen GPS-position finns,
  2. skapar en SIGNERAD version (signaturen "@osterbackaphoto.com" nere till vänster,
     som i Eskos Lightroom-export, full upplösning),
  3. skapar en FÖRHANDSBILD (högst 1200 px, stor vattenstämpel, ingen metadata),
  4. laddar upp rent original + signerad version till den privata bucketen och
     förhandsbilden till preview-bucketen,
  5. registrerar match, bilder och taggar i databasen som UTKAST (draft).

Inget syns i shoppen förrän matchen publiceras i kontrollvyn.

Exempel:
  python3 shop_upload.py ~/Desktop/shop-test --hemmalag "Ulricehamns IFK" --bortalag "P18 IK"
  python3 shop_upload.py ~/Desktop/shop-test --hemmalag "Ulricehamns IFK" --bortalag "P18 IK" --provkor

Standard är TESTMILJÖN. Produktion kräver --miljo produktion och en bekräftelse.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import date
from pathlib import Path

import shop_common as sc

JPEG_SUFFIXES = {".jpg", ".jpeg"}


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Ladda upp en match till OsterbackaPhoto Shop.")
    p.add_argument("mapp", type=Path, help="Mapp med exporterade JPEG-original")
    p.add_argument("--hemmalag", required=True, help='Hemmalagets namn, t.ex. "Ulricehamns IFK"')
    p.add_argument("--bortalag", required=True, help='Bortalagets namn, t.ex. "P18 IK"')
    p.add_argument("--datum", help="Matchdatum ÅÅÅÅ-MM-DD (standard: tagningsdatum för första bilden)")
    p.add_argument("--serie", help='Serie/tävling, t.ex. "Div 1 Mellersta"')
    p.add_argument("--miljo", choices=["test", "produktion"], default="test")
    p.add_argument("--provkor", action="store_true",
                   help="Laddar inte upp något. Skapar signerade bilder och förhandsbilder i mappen provkorning/ för granskning.")
    p.add_argument("--tillat-gps", action="store_true",
                   help="Tillåt original med GPS-position (rekommenderas inte)")
    return p.parse_args(argv)


def confirm_production() -> None:
    print("\n*** PRODUKTION ***  Bilderna laddas upp till den skarpa shoppen (som utkast).")
    answer = input('Skriv "produktion" för att fortsätta: ').strip().lower()
    if answer != "produktion":
        sys.exit("Avbrutet – inget har laddats upp.")


def find_images(folder: Path) -> tuple[list[Path], list[Path]]:
    if not folder.is_dir():
        sys.exit(f"Hittar ingen mapp: {folder}")
    files = sorted(p for p in folder.iterdir() if p.is_file() and not p.name.startswith("."))
    images = [p for p in files if p.suffix.lower() in JPEG_SUFFIXES]
    others = [p for p in files if p.suffix.lower() not in JPEG_SUFFIXES]
    return images, others


def get_or_create_team(cur, name: str) -> uuid.UUID:
    slug = sc.slugify(name)
    if not slug:
        sys.exit(f"Ogiltigt lagnamn: {name!r}")
    cur.execute("select id, name from public.team where slug = %s", (slug,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute("insert into public.team (name, slug) values (%s, %s) returning id", (name.strip(), slug))
    return cur.fetchone()[0]


def get_or_create_match(cur, match_date: date, home_id, away_id, home_name, away_name, series):
    slug = f"{match_date.isoformat()}-{sc.slugify(home_name)}-{sc.slugify(away_name)}"
    cur.execute("select id, home_team_id, away_team_id, status from public.match where slug = %s", (slug,))
    row = cur.fetchone()
    if row:
        if (row[1], row[2]) != (home_id, away_id):
            sys.exit(f"Matchen {slug} finns redan med andra lag. Avbryter.")
        return row[0], slug, False, row[3]
    cur.execute(
        "insert into public.match (slug, date, home_team_id, away_team_id, series) "
        "values (%s, %s, %s, %s, %s) returning id",
        (slug, match_date, home_id, away_id, series),
    )
    return cur.fetchone()[0], slug, True, "draft"


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    images, others = find_images(args.mapp.expanduser())
    if not images:
        sys.exit(f"Inga JPEG-bilder i {args.mapp}")

    # Läs all metadata först, så att problem syns innan något laddas upp.
    print(f"Läser {len(images)} bilder …")
    metas: dict[Path, sc.ImageMeta] = {}
    tags: dict[Path, sc.ParsedTags] = {}
    warnings: list[str] = []
    blocked: list[Path] = []
    for p in images:
        try:
            meta = sc.read_meta(p.read_bytes())
        except Exception as e:  # trasig fil
            warnings.append(f"{p.name}: kan inte läsas ({e}) – hoppas över")
            blocked.append(p)
            continue
        metas[p] = meta
        tags[p] = sc.parse_keywords(meta.keywords)
        if tags[p].unclear:
            warnings.append(f"{p.name}: oklara nyckelord tolkas inte: {', '.join(tags[p].unclear)}"
                            " (använd home:NN eller away:NN)")
        if not meta.keywords and meta.taken_at is None:
            warnings.append(f"{p.name}: saknar all metadata (inga nyckelord, ingen tagningstid) – "
                            "exportera med \"Alla metadata\"")
        elif meta.taken_at is None:
            warnings.append(f"{p.name}: saknar tagningstid – sorteras sist i galleriet")
        if meta.has_gps and not args.tillat_gps:
            warnings.append(f"{p.name}: innehåller GPS-position – hoppas över (exportera utan platsinfo)")
            blocked.append(p)

    usable = [p for p in images if p not in blocked]
    taken = sorted(m.taken_at for p, m in metas.items() if m.taken_at and p in usable)
    if args.datum:
        match_date = date.fromisoformat(args.datum)
    elif taken:
        match_date = taken[0].astimezone(sc.STOCKHOLM).date()
    else:
        sys.exit("Kan inte avgöra matchdatum (ingen tagningstid). Ange --datum ÅÅÅÅ-MM-DD.")

    print(f"Match: {args.hemmalag} – {args.bortalag}, {match_date.isoformat()}"
          + (f", {args.serie}" if args.serie else ""))

    cfg = None
    if args.provkor:
        cfg = sc.render_only_config()
    else:
        try:
            cfg = sc.load_config(args.miljo)
        except sc.ConfigError as e:
            sys.exit(str(e))
        if args.miljo == "produktion":
            confirm_production()
        print(cfg.describe())

    results = {"uppladdade": 0, "fanns_redan": 0, "med_taggar": 0, "utan_taggar": 0}

    if args.provkor:
        out = args.mapp.expanduser() / "provkorning"
        out.mkdir(exist_ok=True)
        for p in usable:
            signed = sc.make_signed_jpeg(p.read_bytes(), cfg)
            (out / f"{p.stem}_signerad.jpg").write_bytes(signed)
            (out / f"{p.stem}_forhandsbild.jpg").write_bytes(sc.make_preview_jpeg(signed, cfg))
            results["med_taggar" if tags[p].tags else "utan_taggar"] += 1
            print(f"  {p.name}: taggar {format_tags(tags[p], args)}")
        print(f"\nProvkörning klar – granska bilderna i {out}")
    else:
        s3 = sc.r2_client(cfg)
        with sc.db_connect(cfg) as conn:
            with conn.cursor() as cur:
                cur.execute("select current_user")
                role = cur.fetchone()[0]
                if role != "shop_admin":
                    warnings.append(f"Ansluten som rollen '{role}', inte shop_admin")
                home_id = get_or_create_team(cur, args.hemmalag)
                away_id = get_or_create_team(cur, args.bortalag)
                match_id, slug, created, status = get_or_create_match(
                    cur, match_date, home_id, away_id, args.hemmalag, args.bortalag, args.serie)
                conn.commit()
                print(f"Match {'skapad' if created else 'finns redan'}: {slug} (status {status})")
                team_ids = {"home": home_id, "away": away_id}

                for i, p in enumerate(usable, 1):
                    cur.execute("select 1 from public.image where match_id = %s and filename = %s",
                                (match_id, p.name))
                    if cur.fetchone():
                        results["fanns_redan"] += 1
                        print(f"  [{i}/{len(usable)}] {p.name}: finns redan – hoppas över")
                        continue
                    meta = metas[p]
                    data = p.read_bytes()
                    signed = sc.make_signed_jpeg(data, cfg)
                    preview = sc.make_preview_jpeg(signed, cfg)
                    image_id = uuid.uuid4()
                    keys = sc.storage_keys(match_id, image_id)
                    s3.put_object(Bucket=cfg.original_bucket, Key=keys["original"], Body=data,
                                  ContentType="image/jpeg")
                    s3.put_object(Bucket=cfg.original_bucket, Key=keys["signed"], Body=signed,
                                  ContentType="image/jpeg")
                    s3.put_object(Bucket=cfg.preview_bucket, Key=keys["preview"], Body=preview,
                                  ContentType="image/jpeg", CacheControl="public, max-age=3600")
                    cur.execute(
                        "insert into public.image (id, match_id, filename, preview_key, original_r2_key, "
                        "signed_r2_key, taken_at, width, height) values (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (image_id, match_id, p.name, keys["preview"], keys["original"], keys["signed"],
                         meta.taken_at, meta.width, meta.height),
                    )
                    for side, number in sorted(tags[p].tags):
                        cur.execute("insert into public.image_tag (image_id, team_id, player_number) "
                                    "values (%s, %s, %s)", (image_id, team_ids[side], number))
                    conn.commit()
                    results["uppladdade"] += 1
                    results["med_taggar" if tags[p].tags else "utan_taggar"] += 1
                    print(f"  [{i}/{len(usable)}] {p.name}: uppladdad, taggar {format_tags(tags[p], args)}")

    print("\n=== Sammanfattning ===")
    print(f"Bilder i mappen:        {len(images)}")
    if not args.provkor:
        print(f"Uppladdade nu:          {results['uppladdade']}")
        print(f"Fanns redan:            {results['fanns_redan']}")
    print(f"Med taggar:             {results['med_taggar']}")
    print(f"Utan taggar:            {results['utan_taggar']}  (helt okej – visas ändå i galleriet)")
    print(f"Hoppades över:          {len(blocked)}")
    if others:
        print(f"Andra filer (ignoreras): {', '.join(p.name for p in others[:5])}"
              + (" …" if len(others) > 5 else ""))
    if warnings:
        print("\nVarningar:")
        for w in warnings:
            print(f"  ! {w}")
    if not args.provkor:
        print("\nMatchen är ett UTKAST. Den syns inte i shoppen förrän du publicerar den i kontrollvyn.")
    return 0


def format_tags(parsed: sc.ParsedTags, args) -> str:
    if not parsed.tags:
        return "inga"
    names = {"home": args.hemmalag, "away": args.bortalag}
    return ", ".join(f"{names[s]} #{n}" for s, n in sorted(parsed.tags))


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
