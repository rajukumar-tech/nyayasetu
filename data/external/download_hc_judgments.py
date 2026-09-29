"""Build data/judgments/hc_judgments.jsonl from a LOCAL copy of a public High Court judgments dataset.

NyayaSetu never generates judgments. Download a public, licence-compatible dataset of Indian
High Court judgments yourself (for example the openly published Indian High Court judgments
collections — check the licence before use), then point this script at it:

    python data/external/download_hc_judgments.py --src /path/to/judgments --meta metadata.csv

Expected input: a directory of .txt files (or .pdf, text extracted with pypdf) and a CSV with
columns: filename, citation, court, date, url. Each judgment is split into ~1,200-character
passages so retrieval can show the matching passage with its source link.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def passages(text: str, size: int = 1200, overlap: int = 200):
    i = 0
    while i < len(text):
        yield text[i:i + size]
        i += size - overlap


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, required=True)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "judgments" / "hc_judgments.jsonl")
    a = ap.parse_args()
    meta = {r["filename"]: r for r in csv.DictReader(a.meta.open(encoding="utf-8"))}
    n = 0
    with a.out.open("w", encoding="utf-8") as out:
        for fname, m in meta.items():
            p = a.src / fname
            if not p.exists():
                continue
            if p.suffix.lower() == ".pdf":
                from pypdf import PdfReader
                text = "\n".join((pg.extract_text() or "") for pg in PdfReader(p).pages)
            else:
                text = p.read_text(encoding="utf-8", errors="replace")
            for k, chunk in enumerate(passages(" ".join(text.split()))):
                out.write(json.dumps({"id": f"{p.stem}-{k}", "citation": m["citation"], "court": m["court"],
                                      "date": m["date"], "url": m["url"], "text": chunk, "synthetic": False},
                                     ensure_ascii=False) + "\n")
                n += 1
    print(f"wrote {n} passages to {a.out}")


if __name__ == "__main__":
    main()
