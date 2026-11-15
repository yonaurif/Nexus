"""Chunking por límites semánticos (Doc 03 §8.2): títulos Markdown abren chunk nuevo, los
párrafos se agrupan hasta `max_chars`, y cada chunk guarda offsets exactos en el texto original.

ponytail: tamaño por caracteres; por tokens cuando se fije el tokenizador del embedder.
"""
import re
from dataclasses import dataclass

PARAGRAPH = re.compile(r"[^\n]+(?:\n(?![ \t]*\n)[^\n]*)*")  # líneas no vacías consecutivas
HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*\s*$")


@dataclass
class Chunk:
    index: int
    text: str
    start: int
    end: int
    heading: str | None


def _hard_split(text: str, start: int, end: int, max_chars: int):
    pos = start
    while pos < end:
        cut = min(pos + max_chars, end)
        if cut < end:  # cortar en el último espacio de la segunda mitad de la ventana
            space = text.rfind(" ", pos + max_chars // 2, cut)
            cut = space if space > pos else cut
        yield pos, cut
        pos = cut
        while pos < end and text[pos].isspace():
            pos += 1


def chunk_text(text: str, max_chars: int = 1200) -> list[Chunk]:
    """`heading` es la ruta de títulos ("Doc › Sección › Sub"): sin ella, un fragmento de
    "Estructura" no sabe que pertenece a "Primitivo Worker" y la búsqueda no lo encuentra (medido)."""
    spans: list[tuple[int, int, str | None]] = []
    heading, cur = None, None  # cur = [start, end, tiene_cuerpo]
    path: list[tuple[int, str]] = []  # (nivel, título)

    def flush():
        nonlocal cur
        if cur and cur[2]:  # un título sin cuerpo ya va en la ruta de los fragmentos siguientes
            spans.append((cur[0], cur[1], heading))
        cur = None

    for m in PARAGRAPH.finditer(text):
        s, e = m.start(), m.end()
        e = s + len(text[s:e].rstrip())
        if s == e:
            continue
        is_heading = bool(h := HEADING.match(text[s:e].splitlines()[0]))
        if is_heading:
            flush()
            level = len(text[s:e]) - len(text[s:e].lstrip("#"))
            path = [p for p in path if p[0] < level] + [(level, h.group(1))]
            heading = " › ".join(t for _, t in path)
        if e - s > max_chars:
            flush()
            spans.extend((a, b, heading) for a, b in _hard_split(text, s, e, max_chars))
            continue
        if cur and e - cur[0] > max_chars:
            flush()
        body = not is_heading or len(text[s:e].splitlines()) > 1
        cur = [cur[0], e, cur[2] or body] if cur else [s, e, body]
    flush()
    return [Chunk(i, text[a:b], a, b, h) for i, (a, b, h) in enumerate(spans)]
