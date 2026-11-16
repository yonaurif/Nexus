"""Entrenamiento offline compartido por la CLI y la API (Text Learning §5 pasos 9–14, §8 pasos 5–7).
Corpus base + correcciones aprobadas -> dataset versionado -> entrenar -> evaluar -> registrar CANDIDATO.
Nunca promueve: eso lo decide el propietario."""
import threading
from pathlib import Path

from nexus.config import env
from nexus.learning import dataset, intent, registry

BACKEND = Path(__file__).resolve().parents[2]
SEED_PATH = BACKEND / "data" / "intent" / "intent_es_v1.jsonl"
EXAM_PATH = BACKEND / "data" / "intent" / "eval_gala_v1.jsonl"  # examen externo: nunca se entrena con él
_training = threading.Lock()  # una sesión de entrenamiento a la vez


class Busy(Exception):
    pass


def models_dir() -> Path:
    return Path(env("NEXUS_MODELS_DIR") or BACKEND / "artifacts")


def train_and_register(engine, seed_path: Path = SEED_PATH, include_feedback: bool = True, encoder=None):
    """encoder = el embedder del RAG (variante +enc); None = solo TF-IDF."""
    if not _training.acquire(blocking=False):
        raise Busy
    try:
        ds = dataset.load(seed_path)
        if include_feedback:
            with engine.connect() as c:
                ds = dataset.merge(ds, dataset.from_feedback(c))
        exam = dataset.load(EXAM_PATH) if EXAM_PATH.exists() else None
        result = intent.train(ds, models_dir(), encoder=encoder, external=exam)
        with engine.begin() as c:
            model_id = registry.register(c, "intent_es", result)
        return model_id, result
    finally:
        _training.release()
