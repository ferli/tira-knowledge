#!/usr/bin/env python3
"""
ingest.py — Chunk markdown dokumen regulasi, embed via Gemini Embedding, push ke CF Vectorize.
Ini adalah jembatan antara graph/ + output/ → CF Vectorize (Tira-accessible).

Usage:
    python scripts/ingest.py                          # Ingest semua dokumen
    python scripts/ingest.py graph/pp-122-2015.yaml   # Ingest 1 dokumen
    python scripts/ingest.py --dry-run                # Tanpa push, lihat output saja
"""

import os
import sys
import json
import re
import hashlib
import urllib.request
from pathlib import Path
from datetime import datetime, timezone
import yaml

WORKSPACE = Path(__file__).resolve().parents[1]

# --- Config ---

CF_ACCOUNT_ID = os.environ.get("CF_ACCOUNT_ID", "")
CF_API_TOKEN = os.environ.get("CF_API_TOKEN", "")
VECTORIZE_INDEX = os.environ.get("VECTORIZE_INDEX", "tira-knowledge")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
EMBED_MODEL = "text-embedding-004"  # Gemini embedding model
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def log(msg):
    print(f"[ingest] {msg}")


# --- Chunking ---

def split_sections(body: str, max_len: int = CHUNK_SIZE) -> list[dict]:
    """Split markdown body by headings, adapted from proven pattern."""
    sections = []
    current_heading = "Pendahuluan"
    current_level = 0
    current_lines = []

    for line in body.split("\n"):
        m = re.match(r"^(#{1,4})\s+(.+)", line)
        if m:
            text = "\n".join(current_lines).strip()
            if text and len(text) > 20:
                sections.append({"heading": current_heading, "level": current_level, "text": text})
            current_heading = m.group(2).strip()
            current_level = len(m.group(1))
            current_lines = []
        else:
            current_lines.append(line)

    text = "\n".join(current_lines).strip()
    if text and len(text) > 20:
        sections.append({"heading": current_heading, "level": current_level, "text": text})

    # Merge small adjacent sections, split large ones
    merged = []
    for s in sections:
        if len(s["text"]) > max_len * 1.5:
            # Split long section into overlapping chunks
            words = s["text"].split()
            for i in range(0, len(words), max_len // 10):
                chunk_text = " ".join(words[i:i + max_len // 10 + CHUNK_OVERLAP // 10])
                if len(chunk_text) > 20:
                    merged.append({**s, "text": chunk_text})
        else:
            merged.append(s)
    return merged


# --- Embedding ---

def embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed list of texts via Gemini Embedding API."""
    if not GEMINI_API_KEY:
        log("WARNING: GEMINI_API_KEY tidak diset, gunakan dummy embeddings")
        return [[0.0] * 768 for _ in texts]

    url = f"https://generativelanguage.googleapis.com/v1beta/models/{EMBED_MODEL}:batchEmbedContents?key={GEMINI_API_KEY}"
    requests = [{
        "model": f"models/{EMBED_MODEL}",
        "content": {"parts": [{"text": t}]}
    } for t in texts]

    req = urllib.request.Request(
        url,
        data=json.dumps({"requests": requests}).encode(),
        headers={"Content-Type": "application/json"}
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read())
            return [e["values"] for e in data.get("embeddings", [])]
    except Exception as e:
        log(f"ERROR embedding: {e}")
        return [[0.0] * 768 for _ in texts]


# --- CF Vectorize ---

def push_to_vectorize(vectors: list[dict], dry_run: bool = False) -> bool:
    """Push vectors ke CF Vectorize index via REST API."""
    if not CF_ACCOUNT_ID or not CF_API_TOKEN:
        log("WARNING: CF_ACCOUNT_ID/CF_API_TOKEN tidak diset, skip push")
        return False

    if dry_run:
        log(f"DRY-RUN: {len(vectors)} vectors akan di-push ke {VECTORIZE_INDEX}")
        for v in vectors[:3]:
            log(f"  {v['id']}: {v['metadata'].get('heading', '')[:60]}")
        return True

    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/vectorize/indexes/{VECTORIZE_INDEX}/upsert"
    req = urllib.request.Request(
        url,
        data=json.dumps(vectors).encode(),
        headers={
            "Authorization": f"Bearer {CF_API_TOKEN}",
            "Content-Type": "application/json"
        },
        method="PUT"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("success"):
                log(f"Berhasil push {len(vectors)} vectors ke CF Vectorize")
                return True
            else:
                log(f"ERROR CF: {json.dumps(data.get('errors', []))}")
                return False
    except Exception as e:
        log(f"ERROR push: {e}")
        return False


# --- Ingest pipeline ---

def ingest_document(graph_path: Path, dry_run: bool = False) -> int:
    """Ingest satu dokumen: baca graph → baca markdown source → chunk → embed → push."""
    with open(graph_path, encoding="utf-8") as f:
        meta = yaml.safe_load(f)

    doc_id = meta.get("doc_id", graph_path.stem)
    title = meta.get("title", doc_id)
    source_file = meta.get("source_file", "")

    # Cari file markdown
    md_path = WORKSPACE / "output" / source_file if source_file else None
    if not md_path or not md_path.exists():
        # Fallback: cari berdasarkan doc_id
        candidates = list((WORKSPACE / "output").rglob(f"*{doc_id}*.md"))
        md_path = candidates[0] if candidates else None

    if not md_path or not md_path.exists():
        log(f"SKIP {doc_id}: markdown source tidak ditemukan")
        return 0

    text = md_path.read_text(encoding="utf-8")
    _, body = text.split("---", 2)[1:] if text.startswith("---") else (None, text)

    sections = split_sections(body)
    log(f"{doc_id}: {len(sections)} chunks")

    # Embed in batches of 20
    vectors = []
    for i in range(0, len(sections), 20):
        batch_sections = sections[i:i + 20]
        texts = [s["text"] for s in batch_sections]
        embeddings = embed_batch(texts)

        for sec, emb in zip(batch_sections, embeddings):
            chunk_id = hashlib.md5(sec["text"][:200].encode()).hexdigest()[:12]
            vector_id = f"{doc_id}-{chunk_id}"
            vectors.append({
                "id": vector_id,
                "values": emb,
                "metadata": {
                    "doc_id": doc_id,
                    "title": title,
                    "hierarki": meta.get("hierarki", ""),
                    "entity": meta.get("entity", ""),
                    "heading": sec["heading"],
                    "level": sec["level"],
                    "text": sec["text"][:2000],  # simpan 2000 karakter untuk context
                    "topik": ",".join(meta.get("topik", [])),
                }
            })

    if vectors:
        push_to_vectorize(vectors, dry_run=dry_run)

    return len(vectors)


def main():
    dry_run = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]

    target = Path(args[0]) if args else WORKSPACE / "graph"

    if target.is_file():
        count = ingest_document(target, dry_run=dry_run)
        log(f"Selesai: {count} vectors dari {target.stem}")
    elif target.is_dir():
        yaml_files = sorted(target.glob("*.yaml"))
        if not yaml_files:
            log("Tidak ada file .yaml di graph/. Jalankan graph.py dulu.")
            sys.exit(1)
        total = 0
        for yf in yaml_files:
            total += ingest_document(yf, dry_run=dry_run)
        log(f"Selesai: {total} vectors dari {len(yaml_files)} dokumen")
    else:
        log(f"ERROR: {target} bukan file atau direktori valid")


if __name__ == "__main__":
    main()
