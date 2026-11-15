"""Entrenamiento offline del clasificador de intención (Text Learning §5 pasos 9–14, §8).

    python -m nexus.learning.train_intent [data/intent/intent_es_v1.jsonl] [--promote]

Valida el dataset, entrena, evalúa en el test bloqueado contra la línea base de reglas, guarda el
artefacto + informe en NEXUS_MODELS_DIR (por defecto backend/artifacts, fuera de git) y lo registra
como CANDIDATO. Solo con --promote (decisión del propietario) pasa a activo, y solo si supera la base.
"""
import sys
from pathlib import Path

from nexus.config import env
from nexus.db import get_engine
from nexus.learning import dataset, intent, registry

BACKEND = Path(__file__).resolve().parents[2]


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else BACKEND / "data" / "intent" / "intent_es_v1.jsonl"
    ds = dataset.load(path)
    m = ds.manifest()
    print(f"dataset {path.name}: {m['examples']} ejemplos, {m['rejected']} rechazados, versión {m['version'][:19]}…")
    for r in ds.rejected[:10]:
        print(f"  rechazado {r['example_id']}: {r['reason']}")

    result = intent.train(ds, env("NEXUS_MODELS_DIR") or BACKEND / "artifacts")
    rep, t = result.report, result.report["test"]
    print(f"particiones {rep['splits']} · umbral de abstención {rep['threshold']}")
    cv = rep["cross_validation"]
    print(f"TEST  híbrido macro-F1 {t['hybrid_macro_f1']:.3f} · solo modelo {t['macro_f1']:.3f} · "
          f"solo reglas {t['baseline_rules_macro_f1']:.3f}")
    print(f"      cobertura del modelo {t['coverage']:.0%} · acierto en lo aceptado {t['accepted_accuracy']:.0%} · "
          f"CV {cv['folds']} particiones {cv['macro_f1_mean']:.3f} ± {cv['macro_f1_std']:.3f}")
    for label, c in t["per_class"].items():
        print(f"  {label:16} P {c['precision']:.2f}  R {c['recall']:.2f}  F1 {c['f1']:.2f}  n={c['support']}")

    engine = get_engine()
    with engine.begin() as c:
        model_id = registry.register(c, "intent_es", result)
    print(f"registrado como candidato: {model_id}\nartefacto: {result.artifact_path}")
    if "--promote" in argv:
        with engine.begin() as c:
            registry.promote(c, model_id)
        print("promovido a ACTIVO (se carga al arrancar el servidor o al promover por la API)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
