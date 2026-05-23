#!/usr/bin/env python3
"""
graph.py — Ekstraksi relasi antar regulasi dari output markdown.
Menggunakan Gemini untuk identifikasi referensi silang (amanatkan, merujuk, berlaku_untuk).
Menghasilkan YAML knowledge graph per dokumen.

Usage:
    python scripts/graph.py output/pp-122-2015.md      # Ekstrak 1 dokumen → graph/
    python scripts/graph.py output/                     # Batch semua dokumen di output/
"""

import os
import sys
import json
import re
import yaml
from pathlib import Path
from datetime import datetime, timezone

import logging

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- Frontmatter helpers ---

REGULATION_TYPES = {
    "peraturan-pemerintah": "PP",
    "peraturan-presiden": "Perpres",
    "peraturan-menteri": "Permen",
    "keputusan-menteri": "Kepmen",
    "undang-undang": "UU",
    "sni": "SNI",
    "sop": "SOP",
    "panduan-teknis": "Panduan Teknis",
    "standar-internasional": "Standar Internasional",
}

TOPICS = [
    "spam", "air-minum", "nrw", "air-limbah", "pdam", "bumd",
    "pengadaan", "tarif", "regulasi", "kelembagaan", "pengawasan",
    "kualitas-air", "sumber-daya-air", "teknis", "keuangan",
]

ENTITIES = ["PUPR", "Kemenkes", "BPPSPAM", "PERPAMSI", "Bappenas",
            "Kemenkeu", "Kemendagri", "KLHK", "IWA", "WHO"]


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Ekstrak YAML frontmatter dan body dari markdown."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                return yaml.safe_load(parts[1]) or {}, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text


def guess_meta(text: str, filepath: Path) -> dict:
    """Heuristic: tebak metadata dari nama file dan isi."""
    stem = filepath.stem
    meta = {"doc_id": stem.lower().replace(" ", "-").replace("_", "-")[:60],
            "title": stem,
            "source_file": str(filepath.name)}

    # Deteksi tipe dari judul/isi
    body_lower = text.lower()
    if "peraturan pemerintah" in body_lower or stem.lower().startswith("pp"):
        meta["hierarki"] = "peraturan-pemerintah"
    elif "peraturan menteri" in body_lower or stem.lower().startswith("permen"):
        meta["hierarki"] = "peraturan-menteri"
    elif "keputusan menteri" in body_lower or stem.lower().startswith("kepmen"):
        meta["hierarki"] = "keputusan-menteri"
    elif "undang-undang" in body_lower or stem.lower().startswith("uu"):
        meta["hierarki"] = "undang-undang"
    elif "sni" in stem.lower() or "standar nasional indonesia" in body_lower:
        meta["hierarki"] = "sni"
    else:
        meta["hierarki"] = "panduan-teknis"

    # Entity
    for entity in ENTITIES:
        if entity.lower() in body_lower:
            meta["entity"] = entity
            break
    if "entity" not in meta:
        meta["entity"] = "PUPR"

    # Topics
    found_topics = [t for t in TOPICS if t.replace("-", " ") in body_lower[:3000]]
    meta["topik"] = found_topics or ["spam"]

    # Keywords from headings
    headings = re.findall(r"^#{1,4}\s+(.+)", text, re.MULTILINE)
    meta["keywords"] = [h.strip().lower() for h in headings[:8]]

    return meta


def extract_relations(markdown_path: Path, gemini_api_key: str = None) -> dict:
    """
    Ekstrak relasi dari satu dokumen markdown.
    Jika Gemini tersedia, gunakan LLM; jika tidak, fallback ke heuristic.
    """
    text = markdown_path.read_text(encoding="utf-8")
    existing_meta, body = parse_frontmatter(text)

    # Merge existing frontmatter + heuristic guess
    meta = guess_meta(body, markdown_path)
    meta.update({k: v for k, v in existing_meta.items() if v})

    # Heuristic: cari referensi ke dokumen lain
    refs_pp = re.findall(r"PP\s*(?:Nomor|No\.?|No)?\s*(\d+)(?:\s*Tahun\s*(\d{4}))?", body, re.IGNORECASE)
    refs_permen = re.findall(r"Permen\s*(?:PUPR|Kesehatan|Dagri)?\s*(?:Nomor|No\.?|No)?\s*(\d+)(?:\s*Tahun\s*(\d{4}))?", body, re.IGNORECASE)
    refs_sni = re.findall(r"SNI\s*(\d+[:\-]\d+)", body, re.IGNORECASE)
    refs_uu = re.findall(r"UU\s*(?:Nomor|No\.?|No)?\s*(\d+)(?:\s*Tahun\s*(\d{4}))?", body, re.IGNORECASE)

    amanatkan = []
    for num, year in refs_pp:
        id_ = f"pp-{num}-{year}" if year else f"pp-{num}"
        amanatkan.append({"id": id_, "tipe": "pp"})
    for num, year in refs_permen:
        id_ = f"permen-{num}-{year}" if year else f"permen-{num}"
        amanatkan.append({"id": id_, "tipe": "permen"})
    for num, year in refs_uu:
        id_ = f"uu-{num}-{year}" if year else f"uu-{num}"
        amanatkan.append({"id": id_, "tipe": "uu"})

    merujuk_sni = [s.replace(":", "-") for s in refs_sni]

    meta["amanatkan"] = amanatkan[:15]  # cap at 15
    meta["merujuk_sni"] = merujuk_sni[:10]
    meta["extracted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    meta["extraction_method"] = "heuristic"
    meta["needs_human_review"] = True

    return meta


def save_graph(meta: dict, output_dir: Path = None):
    """Simpan YAML graph ke graph/."""
    if output_dir is None:
        output_dir = WORKSPACE / "graph"
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_id = meta.get("doc_id", "unknown")
    out_path = output_dir / f"{doc_id}.yaml"
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.dump(meta, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    logger.info(f"Graph tersimpan: {out_path}")


# --- Gemini-assisted extraction (optional) ---

def extract_with_gemini(markdown_path: Path, api_key: str) -> dict:
    """Gunakan Gemini untuk ekstraksi relasi yang lebih akurat."""
    import urllib.request

    text = markdown_path.read_text(encoding="utf-8")
    # Ambil 8000 karakter pertama (cukup untuk identifikasi relasi regulasi)
    snippet = text[:8000]

    prompt = f"""Kamu adalah analis regulasi industri air Indonesia.
Ekstrak metadata dan relasi dari dokumen berikut. Output HANYA JSON valid, tanpa markdown.

{{
  "doc_id": "slug singkat (contoh: pp-122-2015)",
  "title": "judul lengkap dokumen",
  "hierarki": "peraturan-pemerintah|peraturan-menteri|keputusan-menteri|undang-undang|sni|panduan-teknis",
  "entity": "PUPR|Kemenkes|BPPSPAM|PERPAMSI|Bappenas|Kemendagri",
  "topik": ["spam", "air-minum", ...],
  "keywords": ["kata kunci 1", ...],
  "nomor": "nomor dokumen",
  "tahun": tahun,
  "tanggal_berlaku": "YYYY-MM-DD atau null",
  "summary": "ringkasan 2-3 kalimat",
  "amanatkan": [
    {{"id": "slug-dokumen-di-amanatkan", "konteks": "mengamanatkan apa"}}
  ],
  "merujuk_sni": ["sni-7509-2011"],
  "berlaku_untuk": ["nrw-audit", "perencanaan-spam", "evaluasi-kinerja", ...]
}}

Dokumen:
{snippet}"""

    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
        data=json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 2048}
        }).encode(),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            raw = data["candidates"][0]["content"]["parts"][0]["text"]
            # Bersihkan markdown code fences jika ada
            raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            raw = re.sub(r"\s*```$", "", raw)
            return json.loads(raw)
    except Exception as e:
        logger.warning(f"Gemini gagal, fallback ke heuristic: {e}")
        return None


# --- Main ---

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    target = Path(sys.argv[1])
    api_key = os.environ.get("GEMINI_API_KEY")

    md_files = list(target.rglob("*.md")) if target.is_dir() else [target] if target.suffix == ".md" else []

    if not md_files:
        logger.error("Tidak ada file .md ditemukan")
        sys.exit(1)

    for md_path in sorted(md_files):
        logger.info(f"Ekstrak relasi: {md_path}")

        meta = None
        if api_key:
            meta = extract_with_gemini(md_path, api_key)

        if meta is None:
            meta = extract_relations(md_path, api_key)

        save_graph(meta)

    logger.info(f"Selesai: {len(md_files)} graph diekstrak")


if __name__ == "__main__":
    main()
