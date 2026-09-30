"""Upload → dedupe → read/OCR → classify → extract → store facts with spans → review queue."""
from __future__ import annotations

import hashlib
from pathlib import Path

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.config import settings
from app.extraction.extract import extract
from app.ingestion.classify import classify, missing_required
from app.ingestion.ocr import IngestError, OCRProvider, read_document, scripts_in
from app.models import Case, Document, ExtractedFact, ExtractionRun, Person, ReviewItem, User
from app.resolution.normalise import phonetic_key

MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".txt": "text/plain",
        ".tif": "image/tiff", ".tiff": "image/tiff"}


def _store(data: bytes, sha: str, suffix: str) -> tuple[str, bool]:
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{sha}{suffix}"
    encrypted = False
    if settings.documents_encryption_key:
        from cryptography.fernet import Fernet
        data = Fernet(settings.documents_encryption_key.encode()).encrypt(data)
        path = path.with_suffix(path.suffix + ".enc")
        encrypted = True
    path.write_bytes(data)
    return str(path), encrypted


def name_mismatch(person: Person, extracted_names: list[str]) -> str | None:
    """Warn when a document names someone other than the prisoner it was uploaded to."""
    if not extracted_names:
        return None
    known = [phonetic_key(n) for n in [person.canonical_name, *person.name_variants] if n]
    for n in extracted_names:
        k = phonetic_key(n)
        if not k:
            continue
        best = max((JaroWinkler.similarity(k, kk) for kk in known), default=0.0)
        if best >= 0.85:
            return None
    return (f"Name(s) in this document ({', '.join(extracted_names)}) do not match {person.canonical_name}. "
            "Check that it was uploaded to the right prisoner.")


def ingest(db: Session, data: bytes, filename: str, user: User | None, person: Person | None = None,
           case_id: str | None = None, use_llm: bool = True, ocr: OCRProvider | None = None,
           store_file: bool = True) -> tuple[Document, bool]:
    """Returns (document, created). Duplicate uploads (same SHA-256 for the same prisoner) return the existing document."""
    # keep only the base name (no client-side path) and bound its length; storage uses the hash, never this name
    filename = Path(filename.replace("\\", "/")).name.strip()[:200] or "upload"
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise IngestError(f"File is larger than {settings.max_upload_mb} MB. Split it into smaller files.")
    if not data:
        raise IngestError("The file is empty.")
    suffix = Path(filename).suffix.lower()
    if suffix not in MIME:
        raise IngestError("Unsupported file type. Upload PDF, JPG/PNG, DOCX or TXT.")
    # the extension is only a claim: read the file as what its bytes actually are
    actual = sniff(data)
    if actual is None:
        raise IngestError("This file is not a readable PDF, image, Word or text document.")
    ext_warning = []
    if MIME[actual] != MIME[suffix]:
        ext_warning = ["EXTENSION_MISMATCH"]
        suffix = actual
    sha = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.sha256 == sha,
                                           Document.person_id == (person.id if person else None)))
    if dup is not None:
        return dup, False

    pages = read_document(data, Path(filename).stem + suffix, ocr)
    text = "\n".join(p.text for p in pages)
    warnings = sorted({w for p in pages for w in p.warnings} | set(ext_warning))
    doc_type, type_conf, type_method = classify(text) if text.strip() else ("unknown", 0.0, "none")
    path, encrypted = _store(data, sha, suffix) if store_file else (None, False)
    doc = Document(person_id=person.id if person else None, case_id=case_id, filename=filename, sha256=sha,
                   mime=MIME[suffix], size_bytes=len(data), doc_type=doc_type, doc_type_confidence=type_conf,
                   scripts=scripts_in(text), language=_language(text),
                   pages=[{"page": p.page, "text": p.text, "confidence": p.confidence, "boxes": p.boxes[:5000],
                           "warnings": p.warnings, "method": p.method} for p in pages],
                   warnings=warnings, storage_path=path, encrypted=encrypted,
                   uploaded_by=user.id if user else None, status="ocr_done")
    db.add(doc)
    db.flush()
    if not text.strip():
        doc.status = "needs_review"
        _review(db, "document", doc.id, f"No readable text in {filename}", 0.0, {"warnings": warnings})
        audit(db, user, "upload_document", "document", doc.id, after={"filename": filename, "warnings": warnings}, commit=False)
        db.commit()
        return doc, True
    if type_conf < settings.confidence_threshold:
        _review(db, "document_type", doc.id, f"Confirm document type of {filename} (guess: {doc_type})", type_conf,
                {"guess": doc_type, "method": type_method})

    today = settings.today()
    facts, meta = extract(text, doc_type, today, use_llm=use_llm)
    db.add(ExtractionRun(document_id=doc.id, method="regex+llm" if meta.get("llm") else "regex",
                         model=(meta.get("llm") or {}).get("model"), prompt_version=(meta.get("llm") or {}).get("prompt_version"),
                         raw_output=meta))
    page_offsets = _page_offsets(pages)
    ocr_conf = {p.page: p.confidence for p in pages}
    names: list[str] = [f.value["name"] for f in facts if f.field == "person" and isinstance(f.value, dict)
                        and f.value.get("name")]
    # ---- does the CONTENT support this document? (type from text, required fields present, right person/case)
    problems: list[str] = []
    if doc_type == "unknown" or type_conf < settings.confidence_threshold:
        problems.append(f"document type not established from its content (best guess {doc_type}, {type_conf:.0%})")
    missing = missing_required(doc_type, {f.field for f in facts if f.value not in (None, "")})
    if doc_type != "unknown" and missing:
        problems.append(f"a {doc_type.replace('_', ' ')} should contain: {', '.join(missing)}")
        doc.warnings = doc.warnings + ["CONTENT_INCOMPLETE"]
        _review(db, "document_type", doc.id, f"{filename}: content does not support the type '{doc_type}' "
                f"(missing {', '.join(missing)})", min(type_conf, 0.4), {"guess": doc_type, "missing": missing,
                                                                          "document_id": doc.id})
    case = db.get(Case, case_id) if case_id else None
    case_mismatch = _case_mismatch(case, person, facts)
    if case_mismatch:
        problems.append(case_mismatch)
        doc.warnings = doc.warnings + ["CASE_MISMATCH"]
        _review(db, "document_mismatch", doc.id, case_mismatch, 0.3, {"document_id": doc.id, "case_id": case_id})
    elif case is None and person is not None and len(person.cases) > 1:
        linked = _case_by_reference(person, facts)
        if linked is not None:  # unambiguous FIR/CNR match: file it under that case
            doc.case_id = case_id = linked.id
    if person is not None and name_mismatch(person, names):
        problems.append("names in the document do not match this prisoner")
    for f in facts:
        page = _page_for(page_offsets, f.start)
        conf = min(f.confidence, ocr_conf.get(page, 1.0) + 0.1) if ocr_conf.get(page, 1.0) < 0.9 else f.confidence
        notes = list(f.notes)
        if problems:
            # facts from an unverified document are kept (with their spans) but not trusted until a person confirms them
            conf = min(conf, 0.5)
            notes.append("UNVERIFIED_DOCUMENT: " + "; ".join(problems))
        row = ExtractedFact(document_id=doc.id, person_id=person.id if person else None, case_id=case_id, field=f.field,
                            value=f.value, page=page, span_start=f.start, span_end=f.end, span_text=f.text,
                            method=f.method, confidence=round(conf, 2), notes=notes)
        db.add(row)
        db.flush()
        if not problems and (conf < settings.confidence_threshold or any(n.startswith("DISAGREEMENT") for n in f.notes)):
            _review(db, "extraction", row.id, f"{f.field} = {f.value!r} ({doc_type}, p.{page})", conf,
                    {"fact_id": row.id, "document_id": doc.id, "span_text": f.text, "notes": f.notes})
    if person is not None:
        mismatch = name_mismatch(person, names)
        if mismatch:
            doc.warnings = doc.warnings + ["NAME_MISMATCH"]
            _review(db, "document_mismatch", doc.id, mismatch, 0.3, {"names": names, "person_id": person.id})
    doc.status = "needs_review" if problems else "extracted"
    audit(db, user, "upload_document", "document", doc.id,
          after={"filename": filename, "doc_type": doc_type, "facts": len(facts), "warnings": doc.warnings}, commit=False)
    db.commit()
    return doc, True


def sniff(data: bytes) -> str | None:
    """Real format from the leading bytes (magic numbers) — never from the name."""
    head = data[:8]
    if head.startswith(b"%PDF"):
        return ".pdf"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tif"
    if head.startswith(b"PK\x03\x04"):
        return ".docx" if b"word/" in data[:65536] else None
    sample = data[:4096]
    if not sample or b"\x00" in sample:
        return None
    text = sample.decode("utf-8", errors="replace")
    if text.count("\ufffd") <= 2:  # tolerate a multi-byte character cut at the 4 KB boundary
        return ".txt"
    latin = sample.decode("latin-1")
    printable = sum(ch.isprintable() or ch in "\r\n\t\f" for ch in latin)
    return ".txt" if printable / len(latin) > 0.95 else None


def _norm_ref(v: str | None) -> str:
    return "".join(ch for ch in (v or "").upper() if ch.isalnum())


def _refs(facts) -> tuple[set[str], set[str]]:
    firs = {_norm_ref(str(f.value)) for f in facts if f.field == "fir_number" and f.value}
    cnrs = {_norm_ref(str(f.value)) for f in facts if f.field == "cnr" and f.value}
    return firs - {""}, cnrs - {""}


def _case_mismatch(case, person, facts) -> str | None:
    """A document filed under one case that names another case's FIR / CNR."""
    if case is None:
        return None
    firs, cnrs = _refs(facts)
    if cnrs and case.cnr and _norm_ref(case.cnr) not in cnrs:
        return f"The document's CNR does not match the selected case ({case.cnr})."
    if firs and case.fir_number and _norm_ref(case.fir_number) not in firs:
        return f"The document's FIR number does not match the selected case (FIR {case.fir_number})."
    return None


def _case_by_reference(person, facts):
    firs, cnrs = _refs(facts)
    hits = [c for c in person.cases if (c.cnr and _norm_ref(c.cnr) in cnrs) or (c.fir_number and _norm_ref(c.fir_number) in firs)]
    return hits[0] if len(hits) == 1 else None


def _review(db: Session, kind: str, ref: str, title: str, conf: float, payload: dict) -> None:
    existing = db.scalar(select(ReviewItem).where(ReviewItem.kind == kind, ReviewItem.ref_id == ref))
    if existing is None:
        db.add(ReviewItem(kind=kind, ref_id=ref, title=title[:300], confidence=conf, payload=payload))
        db.flush()  # the session does not autoflush: make the next check for this (kind, ref) see it
    elif title not in existing.title:  # a second problem with the same document: keep both reasons
        existing.title = f"{existing.title} | {title}"[:300]
        existing.confidence = min(existing.confidence, conf)


def _page_offsets(pages) -> list[tuple[int, int]]:
    out, pos = [], 0
    for p in pages:
        out.append((pos, p.page))
        pos += len(p.text) + 1
    return out


def _page_for(offsets: list[tuple[int, int]], start: int) -> int:
    page = 1
    for off, pg in offsets:
        if start >= off:
            page = pg
    return page


def _language(text: str) -> str:
    kn = sum(1 for c in text if 0x0C80 <= ord(c) <= 0x0CFF)
    hi = sum(1 for c in text if 0x0900 <= ord(c) <= 0x097F)
    lat = sum(1 for c in text if c.isascii() and c.isalpha())
    parts = [(kn, "kn"), (hi, "hi"), (lat, "en")]
    main = [lang for n, lang in sorted(parts, reverse=True) if n > 0.1 * max(1, kn + hi + lat)]
    return "+".join(main) or "unknown"


__all__ = ["ingest", "IngestError", "name_mismatch"]
