"""Registro de modelos propios (Text Learning §8, §11). Ninguna corrección cambia el modelo en
producción automáticamente: se entrena offline, se evalúa contra el test bloqueado y la línea base,
y el propietario lo promueve (o no). Un solo modelo activo por tarea (índice único parcial)."""
import json
import logging
import uuid

import sqlalchemy as sa

log = logging.getLogger("nexus.learning")


class RegistryError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def register(conn, task: str, result) -> str:
    model_id = f"mdl_{uuid.uuid4().hex}"
    r = result.report
    conn.execute(sa.text(
        "INSERT INTO model_registry (id, task, version, dataset_version, metrics, threshold, artifact_path, "
        "artifact_sha256) VALUES (:i, :t, :v, :d, CAST(:m AS jsonb), :th, :p, :h)"),
        {"i": model_id, "t": task, "v": f"{r['task']}:{r['dataset']['version'][7:19]}",
         "d": r["dataset"]["version"], "m": json.dumps(r), "th": r["threshold"],
         "p": result.artifact_path, "h": result.artifact_sha256})
    return model_id


def get(conn, model_id: str) -> dict | None:
    row = conn.execute(sa.text("SELECT * FROM model_registry WHERE id=:i"), {"i": model_id}).first()
    return row._asdict() if row else None


def list_models(conn, task: str | None = None) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT id, task, version, dataset_version, metrics, threshold, status, created_at, promoted_at "
        "FROM model_registry WHERE CAST(:t AS text) IS NULL OR task = :t ORDER BY created_at DESC"), {"t": task})
    return [r._asdict() for r in rows]


def promote(conn, model_id: str) -> None:
    """TL §7: solo si supera la línea base en la métrica principal: macro-F1 del HÍBRIDO (modelo +
    reglas de respaldo, lo que de verdad enruta) en el test bloqueado."""
    m = get(conn, model_id)
    if m is None:
        raise RegistryError("MODEL_NOT_FOUND")
    test = m["metrics"]["test"]
    if test.get("hybrid_macro_f1", test["macro_f1"]) <= test["baseline_rules_macro_f1"]:
        raise RegistryError("NOT_BETTER_THAN_BASELINE")
    conn.execute(sa.text("UPDATE model_registry SET status='retired' WHERE task=:t AND status='active'"),
                 {"t": m["task"]})
    conn.execute(sa.text("UPDATE model_registry SET status='active', promoted_at=now() WHERE id=:i"), {"i": model_id})


def retire(conn, model_id: str) -> None:
    conn.execute(sa.text("UPDATE model_registry SET status='retired' WHERE id=:i"), {"i": model_id})


def activate_intent(engine) -> bool:
    """Carga en el clasificador el modelo de intención activo (si lo hay y su hash coincide)."""
    from nexus.core import classifier
    from nexus.learning import intent
    with engine.connect() as c:
        row = c.execute(sa.text("SELECT artifact_path, artifact_sha256, version FROM model_registry "
                                "WHERE task='intent_es' AND status='active'")).first()
    if row is None:
        classifier.set_model(None)
        return False
    try:
        classifier.set_model(intent.load(row.artifact_path, row.artifact_sha256))
        return True
    except Exception:  # artefacto ausente, manipulado o sin scikit-learn: se sigue con las reglas
        log.exception("no se pudo cargar el modelo de intención %s", row.version)
        classifier.set_model(None)
        return False
