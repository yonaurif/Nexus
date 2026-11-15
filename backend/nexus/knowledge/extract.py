"""Extracción de texto de documentos con OCR (Doc 03 §4 Document Processor, M2).

Portado de Primitivo-f25 `backend/app/gala/document_extractor.py` (OCR en gris, salto de
imágenes diminutas, caché de logotipos repetidos, reducción de imágenes enormes). Cambios:
- errores en `Extraction.error`, nunca como texto (en Primitivo el mensaje se indexaba);
- HTML sin el contenido de <script>/<style>;
- configuración por `nexus.config.env` en vez de `settings`.

Síncrono: desde la API se llama en el threadpool de FastAPI.
"""
import csv
import hashlib
import io
import json
import os
import shutil
import threading
from collections import OrderedDict
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from nexus.config import env

BACKEND_DIR = Path(__file__).resolve().parents[2]
OCR_DPI = 200            # f25: 150-175 ppp perdía cifras (cuentas, códigos)
MIN_OCR_AREA = 10_000    # px: viñetas e iconos, sin texto legible -> se saltan
MAX_OCR_SIDE = 2500      # px: Tesseract tarda en proporción a los píxeles -> se reduce
_OCR_CACHE_MAX = 512     # ponytail: caché en memoria del proceso; persistirla si hiciera falta
_ocr_cache: "OrderedDict[str, str]" = OrderedDict()
_ocr_cache_lock = threading.Lock()

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tiff", ".tif", ".bmp"}
SUPPORTED_EXT = {".pdf", ".docx", ".xlsx", ".csv", ".html", ".htm", ".json", ".md", ".markdown", ".txt"} | IMAGE_EXT


@dataclass
class Extraction:
    text: str
    ocr_used: bool = False
    error: str | None = None  # UNSUPPORTED_TYPE | EXTRACTION_FAILED | NO_TEXT


# --- Tesseract ---------------------------------------------------------------------------------
def _tesseract_cmd() -> str | None:
    if cmd := env("NEXUS_TESSERACT_CMD"):
        return cmd
    win = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    return str(win) if win.is_file() else shutil.which("tesseract")


def tesseract_available() -> bool:
    cmd = _tesseract_cmd()
    return bool(cmd) and (Path(cmd).is_file() or shutil.which(cmd) is not None)


def _ocr_image(img) -> str:
    """OCR de una PIL.Image. '' si Tesseract no está disponible o falla."""
    try:
        import pytesseract
        if cmd := _tesseract_cmd():
            pytesseract.pytesseract.tesseract_cmd = cmd
        # TESSDATA_PREFIX por entorno (no --tessdata-dir): pytesseract parte el config por
        # espacios y una ruta con espacios se rompe (Primitivo).
        tessdata = Path(env("NEXUS_TESSDATA_DIR") or BACKEND_DIR / "tessdata")
        if tessdata.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        if img.mode not in ("L", "1"):  # f25: mismo texto en gris y la mitad de tiempo
            img = img.convert("L")
        return pytesseract.image_to_string(img, lang=env("NEXUS_OCR_LANGUAGES", "spa+eng"))
    except Exception:
        return ""


def _ocr_embedded(data: bytes, img) -> str:
    """Imagen incrustada: salta las diminutas, reutiliza el resultado de una imagen ya vista
    (mismo logotipo en todas las cartas) y reduce las enormes."""
    w, h = img.size
    if w * h < MIN_OCR_AREA:
        return ""
    key = hashlib.sha1(data).hexdigest()
    with _ocr_cache_lock:
        if key in _ocr_cache:
            _ocr_cache.move_to_end(key)
            return _ocr_cache[key]
    if max(w, h) > MAX_OCR_SIDE:
        img = img.copy()
        img.thumbnail((MAX_OCR_SIDE, MAX_OCR_SIDE))
    text = _ocr_image(img)
    with _ocr_cache_lock:
        _ocr_cache[key] = text
        while len(_ocr_cache) > _OCR_CACHE_MAX:
            _ocr_cache.popitem(last=False)
    return text


# --- Formatos ----------------------------------------------------------------------------------
def _pdf(path: Path, ocr: bool) -> tuple[str, bool]:
    import pymupdf
    from PIL import Image
    pages, used = [], False
    with pymupdf.open(str(path)) as doc:
        for page in doc:
            text = page.get_text()
            if not text.strip() and ocr:  # página escaneada: OCR de la página entera
                pix = page.get_pixmap(dpi=OCR_DPI, colorspace=pymupdf.csGRAY)
                text = _ocr_image(Image.open(io.BytesIO(pix.tobytes("png"))))
                used = used or bool(text.strip())
            elif ocr:  # texto nativo + imágenes incrustadas (sellos, fotos): se OCRan también
                for info in page.get_images(full=True):
                    try:
                        pix = pymupdf.Pixmap(doc, info[0])
                        if pix.n - pix.alpha >= 4:  # CMYK -> RGB
                            pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
                        img_text = _ocr_embedded(pix.samples, Image.open(io.BytesIO(pix.tobytes("png"))))
                    except Exception:
                        continue
                    if img_text.strip():
                        text += "\n\n[Texto de imagen incrustada]\n" + img_text
                        used = True
            if text.strip():
                pages.append(text.strip())
    return "\n\n".join(pages), used


def _image(path: Path, ocr: bool) -> tuple[str, bool]:
    if not ocr:
        return "", False
    from PIL import Image
    with Image.open(str(path)) as img:
        text = _ocr_image(img)
    return text, bool(text.strip())


def _docx(path: Path, ocr: bool) -> tuple[str, bool]:
    from docx import Document
    doc = Document(str(path))
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    used = False
    if ocr:  # las imágenes de un .docx son "media parts" en las relaciones, no párrafos
        from PIL import Image
        for rel in doc.part.rels.values():
            if "image" not in rel.reltype:
                continue
            try:
                blob = rel.target_part.blob
                img_text = _ocr_embedded(blob, Image.open(io.BytesIO(blob)))
            except Exception:
                continue
            if img_text.strip():
                text += "\n\n[Texto de imagen incrustada]\n" + img_text
                used = True
    return text, used


def _xlsx(path: Path) -> str:
    from openpyxl import load_workbook
    wb = load_workbook(str(path), read_only=True, data_only=True)
    lines = []
    for sheet in wb.worksheets:
        lines.append(f"=== Hoja: {sheet.title} ===")
        for row in sheet.iter_rows(values_only=True):
            if cells := [str(c) for c in row if c is not None]:
                lines.append(", ".join(cells))
    wb.close()
    return "\n".join(lines) if len(lines) > len(wb.worksheets) else ""


def _csv(path: Path) -> str:
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        return "\n".join(", ".join(row) for row in csv.reader(f))


class _HtmlText(HTMLParser):
    SKIP = {"script", "style", "noscript", "template"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def _html(path: Path) -> str:
    parser = _HtmlText()
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(parser.parts)


def _json(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        return raw


def extract(path: Path, mime_type: str, name: str, ocr: bool = True) -> Extraction:
    ext = Path(name).suffix.lower()
    try:
        if mime_type == "application/pdf" or ext == ".pdf":
            text, used = _pdf(path, ocr)
        elif mime_type.startswith("image/") or ext in IMAGE_EXT:
            text, used = _image(path, ocr)
        elif mime_type == DOCX or ext == ".docx":
            text, used = _docx(path, ocr)
        elif mime_type == XLSX or ext == ".xlsx":
            text, used = _xlsx(path), False
        elif mime_type == "text/csv" or ext == ".csv":
            text, used = _csv(path), False
        elif mime_type == "text/html" or ext in (".html", ".htm"):
            text, used = _html(path), False
        elif mime_type == "application/json" or ext == ".json":
            text, used = _json(path), False
        elif mime_type in ("text/plain", "text/markdown") or ext in (".txt", ".md", ".markdown"):
            text, used = path.read_text(encoding="utf-8", errors="replace"), False
        else:
            return Extraction("", error="UNSUPPORTED_TYPE")
    except Exception:
        return Extraction("", error="EXTRACTION_FAILED")
    if not text.strip():
        return Extraction("", ocr_used=used, error="NO_TEXT")
    return Extraction(text, ocr_used=used)
