"""Extracción de documentos + OCR (Doc 03 §4–5, M2). Portado de Primitivo-f25
(backend/tests/test_document_extractor.py) y adaptado: los errores van aparte, nunca como texto."""
import io
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.knowledge import extract as ex
from nexus.knowledge.extract import extract

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


# --- Formatos de texto (Primitivo C4 §8) ---
def test_txt_and_markdown(tmp_path):
    assert extract(_write(tmp_path, "n.txt", "texto plano"), "text/plain", "n.txt").text == "texto plano"
    assert "Contenido" in extract(_write(tmp_path, "r.md", "# T\n\nContenido"), "text/markdown", "r.md").text


def test_csv(tmp_path):
    r = extract(_write(tmp_path, "d.csv", "nombre,edad\nAna,30"), "text/csv", "d.csv")
    assert "Ana" in r.text and "30" in r.text and r.error is None


def test_html_strips_tags_scripts_and_styles(tmp_path):
    html = ("<html><head><style>body{color:red}</style><script>alert('x')</script></head>"
            "<body><h1>Título</h1><p>Un párrafo.</p></body></html>")
    t = extract(_write(tmp_path, "p.html", html), "text/html", "p.html").text
    assert "Título" in t and "Un párrafo." in t
    assert "<h1>" not in t and "alert" not in t and "color:red" not in t  # mejora sobre Primitivo


def test_json_pretty_and_invalid_fallback(tmp_path):
    assert "valor" in extract(_write(tmp_path, "c.json", '{"clave": "valor"}'), "application/json", "c.json").text
    assert "no es json" in extract(_write(tmp_path, "r.json", "{no es json"), "application/json", "r.json").text


def test_xlsx(tmp_path):
    from openpyxl import Workbook
    p = tmp_path / "h.xlsx"
    wb = Workbook()
    wb.active.title = "Datos"
    wb.active.append(["nombre", "edad"])
    wb.active.append(["Ana", 30])
    wb.save(p)
    t = extract(p, XLSX, "h.xlsx").text
    assert "Ana" in t and "Datos" in t


# --- Errores: separados del texto (bug de Primitivo: el mensaje se indexaba como contenido) ---
def test_empty_file_is_an_error_not_text(tmp_path):
    r = extract(_write(tmp_path, "v.csv", ""), "text/csv", "v.csv")
    assert r.text == "" and r.error == "NO_TEXT"


def test_unsupported_type_is_an_error_not_text(tmp_path):
    r = extract(_write(tmp_path, "a.xyz", "binario"), "application/x-unknown", "a.xyz")
    assert r.text == "" and r.error == "UNSUPPORTED_TYPE"


def test_corrupt_pdf_is_an_error_not_text(tmp_path):
    p = tmp_path / "roto.pdf"
    p.write_bytes(b"%PDF-1.4 esto no es un pdf")
    r = extract(p, "application/pdf", "roto.pdf")
    assert r.text == "" and r.error == "EXTRACTION_FAILED"


# --- OCR de imágenes incrustadas (Primitivo F6/T2) ---
def _png(tmp_path, size=(300, 150), name="img.png"):
    from PIL import Image
    p = tmp_path / name
    Image.new("RGB", size, color="white").save(p)
    return p


def _docx_with_image(tmp_path: Path) -> Path:
    from docx import Document
    doc = Document()
    doc.add_paragraph("Texto nativo del documento.")
    doc.add_picture(str(_png(tmp_path)))
    p = tmp_path / "con_imagen.docx"
    doc.save(p)
    return p


def test_docx_ocrs_embedded_image(tmp_path):
    ex._ocr_cache.clear()
    with patch("nexus.knowledge.extract._ocr_image", return_value="TEXTO DEL SELLO"):
        r = extract(_docx_with_image(tmp_path), DOCX, "con_imagen.docx")
    assert "Texto nativo del documento." in r.text and "TEXTO DEL SELLO" in r.text and r.ocr_used


def test_docx_without_ocr_skips_images(tmp_path):
    with patch("nexus.knowledge.extract._ocr_image") as ocr:
        r = extract(_docx_with_image(tmp_path), DOCX, "con_imagen.docx", ocr=False)
    ocr.assert_not_called()
    assert "Texto nativo del documento." in r.text and not r.ocr_used


def test_pdf_ocrs_embedded_image_alongside_native_text(tmp_path):
    import pymupdf
    ex._ocr_cache.clear()
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Texto nativo de la pagina PDF.")
    page.insert_image(pymupdf.Rect(72, 100, 200, 150), filename=str(_png(tmp_path)))
    p = tmp_path / "con_imagen.pdf"
    doc.save(p)
    doc.close()
    with patch("nexus.knowledge.extract._ocr_image", return_value="TEXTO DE LA FOTO"):
        r = extract(p, "application/pdf", "con_imagen.pdf")
    assert "Texto nativo de la pagina PDF." in r.text and "TEXTO DE LA FOTO" in r.text and r.ocr_used


def test_embedded_ocr_skips_tiny_images_and_caches_repeats(tmp_path):
    """f25: iconos sin texto se saltan; el mismo logotipo en varios documentos se reconoce una vez."""
    from PIL import Image
    ex._ocr_cache.clear()
    tiny = Image.new("RGB", (50, 50), "white")
    logo = Image.new("RGB", (300, 150), "white")
    with patch("nexus.knowledge.extract._ocr_image", return_value="LOGO") as ocr:
        assert ex._ocr_embedded(b"tiny", tiny) == ""
        assert ex._ocr_embedded(b"logo-bytes", logo) == "LOGO"
        assert ex._ocr_embedded(b"logo-bytes", logo) == "LOGO"
    assert ocr.call_count == 1


# --- OCR real con Tesseract (se salta si no está instalado) ---
def _scanned_pdf(tmp_path: Path, text: str) -> Path:
    """PDF solo con imagen (como un escaneo): sin texto nativo que extraer."""
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1400, 400), "white")
    try:
        font = ImageFont.truetype("arial.ttf", 64)
    except OSError:
        pytest.skip("fuente arial.ttf no disponible")
    ImageDraw.Draw(img).text((60, 140), text, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    doc = pymupdf.open()
    page = doc.new_page(width=700, height=200)
    page.insert_image(page.rect, stream=buf.getvalue())
    p = tmp_path / "escaneado.pdf"
    doc.save(p)
    doc.close()
    return p


def test_real_tesseract_reads_scanned_pdf(tmp_path):
    if not ex.tesseract_available():
        pytest.skip("Tesseract no instalado")
    r = extract(_scanned_pdf(tmp_path, "FACTURA 12345 Madrid"), "application/pdf", "escaneado.pdf")
    assert r.ocr_used and r.error is None
    assert "FACTURA" in r.text and "12345" in r.text


# --- Endpoint de subida (Doc 04 §9.1, Doc 03 §14 "Ingerir documento") ---
AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(engine):
    from fastapi.testclient import TestClient
    from nexus.api.app import create_app
    from tests.test_m1m2 import HashEmbedder, RagModel
    return TestClient(create_app(engine=engine, model=RagModel(), api_token="test-token", embedder=HashEmbedder()))


def test_upload_docx_is_indexed_and_searchable(client, tmp_path):
    from docx import Document
    d = Document()
    d.add_paragraph("El proyecto Orion usa Kubernetes en producción.")
    p = tmp_path / "orion.docx"
    d.save(p)
    r = client.post("/api/v1/knowledge/files", headers=AUTH, files={"file": ("orion.docx", p.read_bytes(), DOCX)})
    assert r.status_code == 201, r.text
    assert r.json()["chunks"] >= 1 and r.json()["ocr_used"] is False
    hits = client.get("/api/v1/knowledge/search", headers=AUTH, params={"q": "Orion Kubernetes"}).json()["hits"]
    assert hits[0]["title"] == "orion.docx"


def test_upload_scanned_pdf_uses_ocr(client, tmp_path):
    if not ex.tesseract_available():
        pytest.skip("Tesseract no instalado")
    p = _scanned_pdf(tmp_path, "CONTRATO 98765 Valencia")
    r = client.post("/api/v1/knowledge/files", headers=AUTH,
                    files={"file": ("contrato.pdf", p.read_bytes(), "application/pdf")}, data={"title": "Contrato"})
    assert r.status_code == 201, r.text
    assert r.json()["ocr_used"] is True
    hits = client.get("/api/v1/knowledge/search", headers=AUTH, params={"q": "contrato 98765"}).json()["hits"]
    assert hits and hits[0]["title"] == "Contrato"


def test_upload_rejections(client, monkeypatch):
    up = lambda name, data, mime="text/plain", h=AUTH: client.post(
        "/api/v1/knowledge/files", headers=h, files={"file": (name, data, mime)})
    assert up("a.txt", b"hola", h={}).status_code == 401
    assert up("virus.exe", b"MZ", "application/octet-stream").status_code == 415
    assert up("vacio.txt", b"   ").json()["detail"] == "NO_TEXT"
    assert up("roto.pdf", b"%PDF-1.4 roto", "application/pdf").json()["detail"] == "EXTRACTION_FAILED"
    monkeypatch.setattr("nexus.api.app.MAX_UPLOAD_BYTES", 10)
    assert up("grande.txt", b"x" * 11).status_code == 413
