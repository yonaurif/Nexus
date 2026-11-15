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
    spans: list[tuple[int, int, str | None]] = []
    heading, cur = None, None  # cur = [start, end]

    def flush():
        nonlocal cur
        if cur:
            spans.append((cur[0], cur[1], heading))
        cur = None

    for m in PARAGRAPH.finditer(text):
        s, e = m.start(), m.end()
        e = s + len(text[s:e].rstrip())
        if s == e:
            continue
        if h := HEADING.match(text[s:e].splitlines()[0]):
            flush()
            heading = h.group(1)
        if e - s > max_chars:
            flush()
            spans.extend((a, b, heading) for a, b in _hard_split(text, s, e, max_chars))
            continue
        if cur and e - cur[0] > max_chars:
            flush()
        cur = [cur[0] if cur else s, e]
    flush()
    return [Chunk(i, text[a:b], a, b, h) for i, (a, b, h) in enumerate(spans)]
