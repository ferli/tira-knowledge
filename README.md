# tira-knowledge

Knowledge graph untuk industri utilitas air Indonesia — powers chatbot **Tira** di [fdiskandar.com](https://fdiskandar.com).

## Arsitektur

```
documents/          # PDF/dokumen sumber regulasi publik
output/             # hasil Docling → markdown + YAML frontmatter
scripts/
  convert.py        # Docling parser (PDF → markdown terstruktur)
  graph.py          # Gemini-assisted relation extraction → YAML graph
  ingest.py         # chunk → embed → push CF Vectorize
graph/              # YAML knowledge graph: relasi antar regulasi
```

## Dokumen Target

- Peraturan Pemerintah (PP)
- Peraturan Menteri (Permen PUPR, Permenkes)
- Standar Nasional Indonesia (SNI) — air minum, NRW
- Panduan teknis PERPAMSI, BPPSPAM
- Standar internasional: IWA, WHO guidelines (konteks Indonesia)

## Status

Fase 0 — scaffolding. Belum ada data.
