#!/usr/bin/env python3
"""
convert.py — Konversi dokumen regulasi (PDF, DOCX, gambar) ke markdown via Docling.
Adapted from proven pipeline. Zero dependency on itgov data.

Usage:
    python scripts/convert.py documents/pp-122-2015.pdf output/pp-122-2015.md
    python scripts/convert.py documents/ output/  # Batch convert folder
"""

import sys
from pathlib import Path
from docling.document_converter import DocumentConverter
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".docx", ".pptx", ".xlsx"}


def convert(input_path: Path, output_path: Path) -> bool:
    if not input_path.exists():
        logger.error(f"File tidak ditemukan: {input_path}")
        return False
    if input_path.suffix.lower() not in SUPPORTED:
        logger.error(f"Tipe tidak didukung: {input_path.suffix}")
        return False

    try:
        logger.info(f"Konversi: {input_path} → {output_path}")
        converter = DocumentConverter()
        result = converter.convert(str(input_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(result.document.export_to_markdown(), encoding="utf-8")
        logger.info(f"Selesai: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Gagal: {input_path}: {e}")
        return False


def batch(input_dir: Path, output_dir: Path) -> int:
    if not input_dir.is_dir():
        logger.error(f"Direktori tidak ditemukan: {input_dir}")
        return 0
    count = 0
    for f in input_dir.rglob("*"):
        if f.is_file() and f.suffix.lower() in SUPPORTED:
            rel = f.relative_to(input_dir)
            if convert(f, output_dir / rel.with_suffix(".md")):
                count += 1
    logger.info(f"Batch selesai: {count} dokumen dikonversi")
    return count


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    if src.is_dir():
        batch(src, dst)
    else:
        ok = convert(src, dst)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
