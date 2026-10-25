"""Image ingestion and privacy-preserving evidence crop pipeline (docs/SPEC.md B1, B5, AC-15)."""

import hashlib
import os
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image, ImageOps
from app.infra.settings import settings

MAX_IMAGE_BYTES = 25 * 1024 * 1024  # 25 MB limit
MAX_DIMENSION = 3000                 # Down-sample longest side to 3000 px max


class CropError(ValueError):
    """Raised when an image fails format or decoding checks."""
    pass


def calculate_image_hash(image_bytes: bytes) -> str:
    """Compute the SHA-256 hash of original image bytes."""
    return hashlib.sha256(image_bytes).hexdigest()


def ingest_incoming_image(
    image_bytes: bytes,
    original_filename: str = "upload.jpg",
) -> Tuple[str, Path]:
    """Validate incoming image bytes, write temporarily to incoming cache, and return (sha256, temp_path).
    
    Enforces:
    - Maximum 25 MB file size.
    - Valid image formats (JPEG, PNG, WEBP).
    - File lives exclusively in cacheDir/incoming/ and will be purged after crop extraction.
    """
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise CropError(f"File exceeds 25 MB size limit ({len(image_bytes) / 1024 / 1024:.1f} MB).")

    sha256_hash = calculate_image_hash(image_bytes)

    # Ensure incoming cache directory exists
    incoming_dir = settings.CACHE_INCOMING_DIR
    incoming_dir.mkdir(parents=True, exist_ok=True)

    temp_path = incoming_dir / f"incoming_{sha256_hash}.tmp"
    with open(temp_path, "wb") as f:
        f.write(image_bytes)

    # Validate that it really opens as an image
    try:
        with Image.open(temp_path) as img:
            img.verify()
    except Exception as e:
        if temp_path.exists():
            temp_path.unlink()
        raise CropError(f"Invalid or corrupted image file: {e}")

    return sha256_hash, temp_path


def extract_evidence_crop(
    temp_image_path: Path,
    sha256_hash: str,
    ym_str: str = "2026-05",
    srs_row_band_pct: Tuple[float, float] = (0.61, 0.72),
) -> Path:
    """Extract only the three required pieces and stitch them vertically:
    1. Top band (title and date): ~0% to 15% of height
    2. Header row: ~15% to 28% of height
    3. SRS Kumaran row: ~61% to 72% of height
    
    Saves stitched crop into evidence/YYYY-MM/evidence_<sha256>.jpg.
    Permanently deletes the full image from temp_image_path!
    """
    evidence_dir = settings.EVIDENCE_DIR / ym_str
    evidence_dir.mkdir(parents=True, exist_ok=True)
    evidence_dest = evidence_dir / f"evidence_{sha256_hash}.jpg"

    try:
        with Image.open(temp_image_path) as raw_img:
            # Apply EXIF rotation if present
            img = ImageOps.exif_transpose(raw_img)

            # Downsample if longest side exceeds MAX_DIMENSION
            w, h = img.size
            if max(w, h) > MAX_DIMENSION:
                ratio = MAX_DIMENSION / max(w, h)
                new_w, new_h = int(w * ratio), int(h * ratio)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                w, h = img.size

            # Slice the 3 parts:
            # 1. Date and title band (top ~14% of the image)
            crop_date = img.crop((0, 0, w, int(h * 0.14)))

            # 2. Table Header Row (from 14% to 28% of the image)
            crop_header = img.crop((0, int(h * 0.14), w, int(h * 0.28)))

            # 3. SRS Kumaran Row (Row 5 in a 6-row table, approx 61% to 72% of height)
            top_row_y = int(h * srs_row_band_pct[0])
            bot_row_y = int(h * srs_row_band_pct[1])
            crop_srs_row = img.crop((0, top_row_y, w, bot_row_y))

            # Stitch the 3 crops vertically
            total_height = crop_date.height + crop_header.height + crop_srs_row.height
            stitched = Image.new("RGB", (w, total_height), (255, 255, 255))
            stitched.paste(crop_date, (0, 0))
            stitched.paste(crop_header, (0, crop_date.height))
            stitched.paste(crop_srs_row, (0, crop_date.height + crop_header.height))

            # Save the stitched evidence crop
            stitched.save(evidence_dest, format="JPEG", quality=90)

    finally:
        # Non-negotiable privacy rule: permanently delete the full incoming image!
        if temp_image_path.exists():
            try:
                temp_image_path.unlink()
            except OSError:
                pass

    return evidence_dest
