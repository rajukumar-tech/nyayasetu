"""Document reading: PDF text layer / DOCX / TXT directly; scanned pages and images via a
pluggable OCR engine (default Tesseract eng+hin+kan) after OpenCV preprocessing
(denoise, deskew, binarise). Per-page text keeps word boxes for citation highlighting."""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, field
from typing import Protocol

from app.resolution.normalise import script_of


class IngestError(Exception):
    """User-facing ingestion failure (message is shown to the uploader)."""


@dataclass
class Page:
    page: int
    text: str
    confidence: float
    boxes: list[dict] = field(default_factory=list)  # {text, x, y, w, h, conf}
    warnings: list[str] = field(default_factory=list)
    method: str = "text"


class OCRProvider(Protocol):
    name: str

    def available(self) -> bool: ...

    def ocr(self, image) -> tuple[str, float, list[dict]]: ...


class TesseractOCR:
    name = "tesseract"
    langs = "eng+hin+kan"

    def available(self) -> bool:
        return shutil.which("tesseract") is not None

    def ocr(self, image) -> tuple[str, float, list[dict]]:
        import pytesseract
        try:
            data = pytesseract.image_to_data(image, lang=self.langs, output_type=pytesseract.Output.DICT)
        except pytesseract.TesseractError:
            data = pytesseract.image_to_data(image, lang="eng", output_type=pytesseract.Output.DICT)
        words, boxes, confs = [], [], []
        line_key = None
        text_parts: list[str] = []
        for i, w in enumerate(data["text"]):
            if not w.strip():
                continue
            key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            if line_key is not None and key != line_key:
                text_parts.append("\n")
            elif text_parts:
                text_parts.append(" ")
            line_key = key
            text_parts.append(w)
            c = float(data["conf"][i])
            confs.append(c)
            boxes.append({"text": w, "x": data["left"][i], "y": data["top"][i], "w": data["width"][i],
                          "h": data["height"][i], "conf": c})
            words.append(w)
        conf = (sum(confs) / len(confs) / 100) if confs else 0.0
        return "".join(text_parts), conf, boxes


def preprocess(img_bytes: bytes):
    """Grayscale → denoise → deskew → Otsu binarise. Returns (image, warnings)."""
    import cv2
    import numpy as np
    arr = np.frombuffer(img_bytes, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise IngestError("The image could not be read — upload a JPG or PNG.")
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    warnings: list[str] = []
    if gray.std() < 3:
        warnings.append("BLANK_PAGE")
    gray = cv2.fastNlMeansDenoising(gray, h=10)
    inv = cv2.bitwise_not(gray)
    coords = np.column_stack(np.where(inv > 128))
    if len(coords) > 50:
        angle = cv2.minAreaRect(coords.astype(np.float32))[-1]
        angle = -(90 + angle) if angle < -45 else -angle
        if 0.5 < abs(angle) < 20:
            h, w = gray.shape
            M = cv2.getRotationMatrix2D((w // 2, h // 2), angle, 1.0)
            gray = cv2.warpAffine(gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
            warnings.append(f"DESKEWED_{angle:.1f}_DEG")
    _, binar = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return binar, warnings


def _ocr_page(img_bytes: bytes, n: int, engine: OCRProvider) -> Page:
    img, warnings = preprocess(img_bytes)
    if "BLANK_PAGE" in warnings:
        return Page(n, "", 0.0, [], warnings, "blank")
    if not engine.available():
        return Page(n, "", 0.0, [], warnings + ["OCR_ENGINE_UNAVAILABLE"], "none")
    text, conf, boxes = engine.ocr(img)
    if conf < 0.6:
        warnings.append("LOW_OCR_CONFIDENCE_POSSIBLE_HANDWRITING")
    if not text.strip():
        warnings.append("NO_TEXT_FOUND")
    return Page(n, text, conf, boxes, warnings, engine.name)


def read_document(data: bytes, filename: str, engine: OCRProvider | None = None) -> list[Page]:
    """Fails safely: any parser error on a damaged/mislabelled file becomes a user-facing IngestError, never a 500."""
    try:
        return _read_document(data, filename, engine)
    except IngestError:
        raise
    except Exception as e:  # noqa: BLE001  (zip/xml/pdf parser internals raise many types)
        kind = filename.rsplit(".", 1)[-1].upper() if "." in filename else "file"
        raise IngestError(f"This {kind} file is damaged or is not really a {kind} and cannot be read "
                          f"({type(e).__name__}). Re-save or re-scan it and upload again.")


def _read_document(data: bytes, filename: str, engine: OCRProvider | None = None) -> list[Page]:
    engine = engine or TesseractOCR()
    name = filename.lower()
    if name.endswith(".txt"):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("latin-1")
        pages = [t for t in text.split("\f")] or [""]
        return [Page(i + 1, t, 1.0 if t.strip() else 0.0, [], [] if t.strip() else ["BLANK_PAGE"]) for i, t in enumerate(pages)]
    if name.endswith(".docx"):
        import docx
        d = docx.Document(io.BytesIO(data))
        text = "\n".join(p.text for p in d.paragraphs)
        return [Page(1, text, 1.0, [], [] if text.strip() else ["BLANK_PAGE"])]
    if name.endswith(".pdf"):
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
        try:
            reader = PdfReader(io.BytesIO(data))
        except PdfReadError as e:
            raise IngestError(f"This PDF is damaged and cannot be read ({e}).")
        if reader.is_encrypted:
            try:
                ok = reader.decrypt("")
            except Exception:  # noqa: BLE001
                ok = 0
            if not ok:
                raise IngestError("This PDF is password-protected. Remove the password and upload again.")
        out = []
        for i, pg in enumerate(reader.pages, start=1):
            text = pg.extract_text() or ""
            if text.strip():
                out.append(Page(i, text, 0.98, [], []))
                continue
            images = list(getattr(pg, "images", []))
            if images:
                out.append(_ocr_page(images[0].data, i, engine))
            else:
                out.append(Page(i, "", 0.0, [], ["BLANK_PAGE"], "blank"))
        return out
    if name.endswith((".jpg", ".jpeg", ".png", ".tif", ".tiff")):
        return [_ocr_page(data, 1, engine)]
    raise IngestError("Unsupported file type. Upload PDF, JPG/PNG, DOCX or TXT.")


def scripts_in(text: str) -> list[str]:
    found = set()
    for line in text.splitlines():
        for tok in line.split():
            found.add(script_of(tok))
    return sorted(found - {"latin"}) + (["latin"] if "latin" in found else [])
