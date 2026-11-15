"""Datos de entrenamiento gobernados (documento Text Learning §4.4, §5, §6; fase T0).

Cada ejemplo lleva procedencia, permiso de uso, idioma, tarea, etiqueta y estado de revisión.
Antes de entrar al corpus: esquema estricto, solo `approved`, sin secretos (redact), normalización
Unicode conservadora (sin tocar acentos ni mayúsculas del original), deduplicación tras normalizar.
La versión del dataset es el hash del contenido aceptado: identifica exactamente con qué se entrenó.
"""
import hashlib
import json
import random
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError

from nexus.contracts import Strict
from nexus.knowledge.sanitize import redact

# Clases de Doc 02 §4. `unknown` no se entrena: es la abstención del clasificador.
Label = Literal["conversation", "knowledge_query", "task_request", "agent_request", "memory_update",
                "feedback", "rule_proposal", "system_admin"]
SPLIT_SEED = 13
SPLIT = {"validation": 0.15, "test": 0.2}


class Example(Strict):
    example_id: str = Field(min_length=1, max_length=100)
    task: Literal["intent_es_v1"]
    text: str = Field(min_length=1, max_length=2000)
    label: Label
    language: Literal["es"]
    source_type: Literal["owner_feedback", "owner_written", "synthetic", "public_dataset"]
    source_ref: str = Field(min_length=1, max_length=300)
    license_or_permission: str = Field(min_length=1, max_length=200)
    review_status: Literal["approved", "needs_review", "rejected"]
    schema_version: Literal[1]


def normalize(text: str) -> str:
    """Unicode NFC + espacios; conserva acentos, negaciones y puntuación (TL §4.3)."""
    return " ".join(unicodedata.normalize("NFC", text).split())


@dataclass
class Dataset:
    examples: list[Example]
    rejected: list[dict] = field(default_factory=list)

    def manifest(self) -> dict:
        body = "\n".join(f"{e.example_id}\t{e.label}\t{normalize(e.text)}" for e in self.examples)
        return {"version": "sha256:" + hashlib.sha256(body.encode()).hexdigest(), "examples": len(self.examples),
                "label_counts": dict(sorted(Counter(e.label for e in self.examples).items())),
                "rejected": len(self.rejected)}


def load(path: str | Path) -> Dataset:
    accepted, rejected, seen = [], [], set()
    for n, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        raw = None
        try:
            raw = json.loads(line)
            e = Example(**raw)
        except (json.JSONDecodeError, ValidationError, TypeError) as err:
            eid = raw.get("example_id", f"line-{n}") if isinstance(raw, dict) else f"line-{n}"
            rejected.append({"example_id": eid, "reason": f"INVALID_SCHEMA: {type(err).__name__}"})
            continue
        if e.review_status != "approved":
            rejected.append({"example_id": e.example_id, "reason": "NOT_APPROVED"})
            continue
        if redact(e.text)[1]:  # TL §5.5: ningún secreto entra en el corpus
            rejected.append({"example_id": e.example_id, "reason": "SECRET_DETECTED"})
            continue
        key = normalize(e.text).lower()
        if key in seen:
            rejected.append({"example_id": e.example_id, "reason": "DUPLICATE"})
            continue
        seen.add(key)
        accepted.append(e.model_copy(update={"text": normalize(e.text)}))
    return Dataset(accepted, rejected)


def split(examples: list[Example]) -> dict[str, list[Example]]:
    """Estratificado por clase, determinista (semilla fija). Sin solapes entre particiones.
    ponytail: sin agrupar por conversación (los ejemplos semilla son independientes); agrupar por
    `source_ref` cuando haya ejemplos reales del mismo hilo (TL §6.3)."""
    by_label: dict[str, list[Example]] = defaultdict(list)
    for e in sorted(examples, key=lambda x: x.example_id):
        by_label[e.label].append(e)
    out: dict[str, list[Example]] = {"train": [], "validation": [], "test": []}
    rng = random.Random(SPLIT_SEED)
    for label in sorted(by_label):
        items = by_label[label][:]
        rng.shuffle(items)
        n_test = max(1, round(len(items) * SPLIT["test"]))
        n_val = max(1, round(len(items) * SPLIT["validation"]))
        out["test"] += items[:n_test]
        out["validation"] += items[n_test:n_test + n_val]
        out["train"] += items[n_test + n_val:]
    return out
