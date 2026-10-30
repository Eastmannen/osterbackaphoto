"""
Gemensam kod för OsterbackaPhoto Shops lokala verktyg (uppladdare och kontrollvy).

Körs bara på administratörens dator. Inga nycklar finns i koden – de läses från
shop_tools/.env (skyddas av .gitignore) och skrivs aldrig ut.
"""

from __future__ import annotations

import io
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image, ImageDraw, ImageFont, ImageOps
from PIL import IptcImagePlugin

HERE = Path(__file__).resolve().parent
STOCKHOLM = ZoneInfo("Europe/Stockholm")

PREVIEW_MAX_PX = 1200
PREVIEW_QUALITY = 80
SIGNED_QUALITY = 95
DEFAULT_WATERMARK_TEXT = "osterbackaphoto.com"

# Signaturen bygger på Eskos vattenstämpel i Lightroom ("@osterbackaphoto.com",
# vit, opacitet 62, ingen skugga) men enligt beslut 2026-10-30 placerad
# nere till HÖGER och betydligt större än på den nuvarande sajten.
DEFAULT_SIGNATURE_TEXT = "@osterbackaphoto.com"
SIGNATURE_OPACITY = 0.62
SIGNATURE_WIDTH = 0.32        # textens bredd som andel av bildens bredd
SIGNATURE_OFFSET_X = 0.05     # andel av bildens bredd
SIGNATURE_OFFSET_Y = 0.03     # andel av bildens höjd

# Förhandsbildens vattenstämpel (stark, 2026-10-30: "mycket starkare,
# både större och lite mer markerad").
PREVIEW_TEXT_WIDTH = 0.80     # varje rads bredd som andel av bildens bredd
PREVIEW_ALPHA_CENTER = 175
PREVIEW_ALPHA_OTHER = 115

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

ENVIRONMENTS = {"test": "SHOP_TEST_", "produktion": "SHOP_PROD_"}
REQUIRED_KEYS = [
    "R2_ENDPOINT",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "PREVIEW_BUCKET",
    "ORIGINAL_BUCKET",
    "DB_URL",
]


class ConfigError(Exception):
    pass


def load_env_file(path: Path) -> None:
    """Läser KEY=värde-rader till os.environ (befintliga värden behålls)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass
class Config:
    environment: str
    r2_endpoint: str
    r2_access_key_id: str
    r2_secret_access_key: str
    preview_bucket: str
    original_bucket: str
    db_url: str
    preview_public_url: str = ""
    signature_path: Path | None = None
    watermark_text: str = DEFAULT_WATERMARK_TEXT
    signature_text: str = DEFAULT_SIGNATURE_TEXT
    font_path: str | None = None

    def describe(self) -> str:
        host = re.sub(r"^https?://", "", self.r2_endpoint).split("/")[0]
        return (
            f"miljö={self.environment.upper()}  R2={host}  "
            f"buckets={self.original_bucket} + {self.preview_bucket}"
        )


def load_config(environment: str) -> Config:
    if environment not in ENVIRONMENTS:
        raise ConfigError(f"Okänd miljö '{environment}'. Välj test eller produktion.")
    load_env_file(HERE / ".env")
    prefix = ENVIRONMENTS[environment]
    missing = [prefix + k for k in REQUIRED_KEYS if not os.environ.get(prefix + k)]
    if missing:
        raise ConfigError(
            "Saknar inställningar i shop_tools/.env: " + ", ".join(missing)
            + "\nSe shop_tools/.env.example."
        )
    sig = os.environ.get("SHOP_SIGNATURE_PATH") or str(HERE / "assets" / "signatur.png")
    return Config(
        environment=environment,
        r2_endpoint=os.environ[prefix + "R2_ENDPOINT"],
        r2_access_key_id=os.environ[prefix + "R2_ACCESS_KEY_ID"],
        r2_secret_access_key=os.environ[prefix + "R2_SECRET_ACCESS_KEY"],
        preview_bucket=os.environ[prefix + "PREVIEW_BUCKET"],
        original_bucket=os.environ[prefix + "ORIGINAL_BUCKET"],
        db_url=os.environ[prefix + "DB_URL"],
        preview_public_url=os.environ.get(prefix + "PREVIEW_PUBLIC_URL", ""),
        signature_path=Path(sig) if Path(sig).exists() else None,
        watermark_text=os.environ.get("SHOP_WATERMARK_TEXT", DEFAULT_WATERMARK_TEXT),
        signature_text=os.environ.get("SHOP_SIGNATURE_TEXT", DEFAULT_SIGNATURE_TEXT),
        font_path=os.environ.get("SHOP_FONT_PATH") or None,
    )


def render_only_config() -> Config:
    """Inställningar för provkörning: bara signatur och vattenstämpel, inga nycklar."""
    load_env_file(HERE / ".env")
    sig = Path(os.environ.get("SHOP_SIGNATURE_PATH") or HERE / "assets" / "signatur.png")
    return Config(
        environment="provkörning", r2_endpoint="", r2_access_key_id="", r2_secret_access_key="",
        preview_bucket="", original_bucket="", db_url="",
        signature_path=sig if sig.exists() else None,
        watermark_text=os.environ.get("SHOP_WATERMARK_TEXT", DEFAULT_WATERMARK_TEXT),
        signature_text=os.environ.get("SHOP_SIGNATURE_TEXT", DEFAULT_SIGNATURE_TEXT),
        font_path=os.environ.get("SHOP_FONT_PATH") or None,
    )


def r2_client(cfg: Config):
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=cfg.r2_endpoint,
        aws_access_key_id=cfg.r2_access_key_id,
        aws_secret_access_key=cfg.r2_secret_access_key,
        region_name="auto",
        config=BotoConfig(
            signature_version="s3v4",
            # R2 stöder inte alla nya standardkontrollsummor i boto3.
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            retries={"max_attempts": 5, "mode": "standard"},
        ),
    )


def db_connect(cfg: Config):
    import psycopg

    return psycopg.connect(cfg.db_url, autocommit=False, connect_timeout=15)


# ---------------------------------------------------------------------------
# Namn och slugs
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.strip().lower()
    for a, b in (("å", "a"), ("ä", "a"), ("ö", "o"), ("é", "e"), ("ü", "u")):
        text = text.replace(a, b)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return re.sub(r"-{2,}", "-", text)


# ---------------------------------------------------------------------------
# Nyckelord (Lightroom) -> taggar
# ---------------------------------------------------------------------------

TAG_RE = re.compile(r"^\s*(home|away)\s*:\s*(\d{1,3})\s*$", re.IGNORECASE)
LOOKS_LIKE_NUMBER_RE = re.compile(r"(^|\W)(home|away|hemma|borta)\b|#?\d", re.IGNORECASE)


@dataclass
class ParsedTags:
    tags: set[tuple[str, int]] = field(default_factory=set)   # {("home", 17), ("away", 8)}
    unclear: list[str] = field(default_factory=list)          # t.ex. "17", "#8", "home 17"
    ignored: list[str] = field(default_factory=list)          # övriga ord, t.ex. "Fotboll"


def parse_keywords(keywords: list[str]) -> ParsedTags:
    result = ParsedTags()
    for raw in keywords:
        kw = raw.strip()
        if not kw:
            continue
        m = TAG_RE.match(kw)
        if m:
            result.tags.add((m.group(1).lower(), int(m.group(2))))
        elif LOOKS_LIKE_NUMBER_RE.search(kw):
            result.unclear.append(kw)
        else:
            result.ignored.append(kw)
    return result


# ---------------------------------------------------------------------------
# Metadata ur JPEG
# ---------------------------------------------------------------------------

XMP_RE = re.compile(rb"<x:xmpmeta.*?</x:xmpmeta>", re.S)


@dataclass
class ImageMeta:
    keywords: list[str]
    taken_at: datetime | None
    has_gps: bool
    width: int
    height: int


def _xmp_text(data: bytes) -> str:
    m = XMP_RE.search(data)
    return m.group(0).decode("utf-8", "ignore") if m else ""


def _xmp_keywords(xmp: str) -> list[str]:
    m = re.search(r"<dc:subject>(.*?)</dc:subject>", xmp, re.S)
    if not m:
        return []
    return [re.sub(r"\s+", " ", v).strip() for v in re.findall(r"<rdf:li[^>]*>([^<]*)</rdf:li>", m.group(1))]


def _iptc_keywords(im: Image.Image) -> list[str]:
    try:
        info = IptcImagePlugin.getiptcinfo(im) or {}
    except Exception:
        return []
    val = info.get((2, 25))
    if val is None:
        return []
    items = val if isinstance(val, list) else [val]
    return [v.decode("utf-8", "ignore") if isinstance(v, bytes) else str(v) for v in items]


def _parse_exif_datetime(value: str | None, offset: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.strptime(value.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    if offset and re.match(r"^[+-]\d{2}:\d{2}$", offset.strip()):
        sign = 1 if offset.strip()[0] == "+" else -1
        hh, mm = offset.strip()[1:].split(":")
        from datetime import timedelta
        return dt.replace(tzinfo=timezone(sign * timedelta(hours=int(hh), minutes=int(mm))))
    return dt.replace(tzinfo=STOCKHOLM)


def _parse_xmp_datetime(xmp: str) -> datetime | None:
    for key in ("photoshop:DateCreated", "exif:DateTimeOriginal", "xmp:CreateDate"):
        m = re.search(key + r'(?:="|>)([0-9T:\-+.Z]+)', xmp)
        if m:
            try:
                dt = datetime.fromisoformat(m.group(1).replace("Z", "+00:00"))
                return dt if dt.tzinfo else dt.replace(tzinfo=STOCKHOLM)
            except ValueError:
                continue
    return None


def read_meta(data: bytes) -> ImageMeta:
    im = Image.open(io.BytesIO(data))
    exif = im.getexif()
    sub = exif.get_ifd(0x8769) if exif else {}
    gps = exif.get_ifd(0x8825) if exif else {}
    xmp = _xmp_text(data)

    keywords = _xmp_keywords(xmp)
    for kw in _iptc_keywords(im):
        if kw not in keywords:
            keywords.append(kw)

    taken = _parse_exif_datetime(sub.get(0x9003), sub.get(0x9011)) or _parse_xmp_datetime(xmp)

    has_gps = bool(gps and (gps.get(2) or gps.get(4))) or bool(
        re.search(r"exif:GPSLatitude|exif:GPSLongitude", xmp)
    )

    oriented = ImageOps.exif_transpose(im)
    return ImageMeta(keywords, taken, has_gps, oriented.width, oriented.height)


# ---------------------------------------------------------------------------
# Bildbehandling: signerad version och förhandsbild
# ---------------------------------------------------------------------------

FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _font(size: int, font_path: str | None = None) -> ImageFont.ImageFont:
    for path in ([font_path] if font_path else []) + FONT_CANDIDATES:
        if path and Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


def _oriented_rgb(data: bytes) -> tuple[Image.Image, bytes | None, Image.Exif]:
    im = Image.open(io.BytesIO(data))
    icc = im.info.get("icc_profile")
    exif = im.getexif()
    im = ImageOps.exif_transpose(im)
    if im.mode != "RGB":
        im = im.convert("RGB")
    return im, icc, exif


def _fit_font(draw: ImageDraw.ImageDraw, text: str, target_w: int, font_path: str | None):
    """Teckenstorlek så att texten blir target_w pixlar bred."""
    size = 100
    font = _font(size, font_path)
    l, _, r, _ = draw.textbbox((0, 0), text, font=font)
    size = max(10, int(size * target_w / max(1, r - l)))
    return _font(size, font_path)


def _apply_signature(img: Image.Image, cfg: Config) -> Image.Image:
    """Lägger Eskos signatur nere till höger."""
    out = img.convert("RGBA")
    mx, my = int(out.width * SIGNATURE_OFFSET_X), int(out.height * SIGNATURE_OFFSET_Y)
    if cfg.signature_path:
        sig = Image.open(cfg.signature_path).convert("RGBA")
        target_w = int(out.width * SIGNATURE_WIDTH)
        sig = sig.resize((target_w, max(1, int(sig.height * target_w / sig.width))), Image.LANCZOS)
        out.alpha_composite(sig, (out.width - sig.width - mx, out.height - sig.height - my))
        return out.convert("RGB")
    layer = Image.new("RGBA", out.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    text = cfg.signature_text
    font = _fit_font(draw, text, int(out.width * SIGNATURE_WIDTH), cfg.font_path)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((out.width - mx - r, out.height - my - b), text, font=font,
              fill=(255, 255, 255, int(255 * SIGNATURE_OPACITY)))
    return Image.alpha_composite(out, layer).convert("RGB")


def make_signed_jpeg(data: bytes, cfg: Config) -> bytes:
    """Signerad version i full upplösning. Behåller upphovsuppgifter, tar bort GPS."""
    img, icc, exif = _oriented_rgb(data)
    signed = _apply_signature(img, cfg)
    exif = Image.Exif() if exif is None else exif
    exif[0x0112] = 1                      # orientering redan tillämpad
    if 0x8825 in exif:
        del exif[0x8825]                  # ingen GPS
    buf = io.BytesIO()
    kwargs = {"quality": SIGNED_QUALITY, "subsampling": 0, "exif": exif.tobytes()}
    if icc:
        kwargs["icc_profile"] = icc
    signed.save(buf, "JPEG", **kwargs)
    return buf.getvalue()


def make_preview_jpeg(signed_data: bytes, cfg: Config) -> bytes:
    """Förhandsbild: högst 1200 px, stor diagonal vattenstämpel, ingen metadata."""
    img = Image.open(io.BytesIO(signed_data)).convert("RGB")
    img.thumbnail((PREVIEW_MAX_PX, PREVIEW_MAX_PX), Image.LANCZOS)

    w, h = img.size
    diag = int((w * w + h * h) ** 0.5)
    layer = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    text = cfg.watermark_text
    font = _fit_font(draw, text, int(w * PREVIEW_TEXT_WIDTH), cfg.font_path)
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    step = int(th * 2.6)
    stroke = max(1, th // 14)
    for i, y in enumerate(range(-diag, diag * 2, step)):
        x = (diag - tw) // 2 + (tw // 2 if i % 2 else 0) - tw // 4
        for dx in (-tw - th, 0, tw + th):
            alpha = PREVIEW_ALPHA_CENTER if abs(y - diag // 2) < step else PREVIEW_ALPHA_OTHER
            draw.text((x + dx, y), text, font=font, fill=(255, 255, 255, alpha),
                      stroke_width=stroke, stroke_fill=(0, 0, 0, alpha // 2))
    layer = layer.rotate(30, resample=Image.BICUBIC)
    left, top = (diag - w) // 2, (diag - h) // 2
    layer = layer.crop((left, top, left + w, top + h))

    out = Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, "JPEG", quality=PREVIEW_QUALITY, optimize=True, progressive=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Lagringsnycklar
# ---------------------------------------------------------------------------

def storage_keys(match_id: uuid.UUID, image_id: uuid.UUID) -> dict[str, str]:
    return {
        "original": f"{match_id}/{image_id}/original.jpg",
        "signed": f"{match_id}/{image_id}/signerad.jpg",
        "preview": f"{match_id}/{image_id}.jpg",
    }
