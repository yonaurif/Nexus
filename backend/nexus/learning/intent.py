"""Clasificador de intención propio en español (documento Text Learning §4.3, §7; fase T1).

TF-IDF de palabras (1–2) + caracteres (2–5, robusto a faltas y variantes) -> LogisticRegression con
pesos equilibrados. Umbral de abstención calibrado en validación; métricas en el test bloqueado;
comparación con la línea base de reglas (classifier.rules_classify). Es una señal de enrutamiento,
nunca una autorización (Doc 02 §4).
"""
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import get_args

from nexus.learning.dataset import Dataset, Label, split

LABELS = list(get_args(Label))
THRESHOLDS = [round(0.15 + 0.05 * i, 2) for i in range(16)]  # 0.15 … 0.90
TARGET_ACCEPTED_ACCURACY = 0.9   # ponytail: objetivos iniciales; fijarlos con datos reales (TL §7)
MIN_COVERAGE = 0.6
MIN_THRESHOLD = 0.3              # suelo: con 8 clases, por debajo acepta casi cualquier texto


@dataclass
class TrainResult:
    artifact_path: str
    artifact_sha256: str
    report: dict


class IntentModel:
    def __init__(self, pipeline, threshold: float, version: str):
        self.pipeline, self.threshold, self.version = pipeline, threshold, version

    def predict(self, text: str) -> tuple[str | None, float]:
        """(etiqueta, confianza); etiqueta None = se abstiene (por debajo del umbral)."""
        proba = self.pipeline.predict_proba([text])[0]
        i = int(proba.argmax())
        conf = float(proba[i])
        return (str(self.pipeline.classes_[i]) if conf >= self.threshold else None), conf


def _pipeline():
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    return Pipeline([
        ("features", FeatureUnion([
            ("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
            ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True)),
        ])),
        ("clf", LogisticRegression(max_iter=3000, class_weight="balanced", C=10.0, random_state=0)),
    ])


def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    return {"macro_f1": round(float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)), 4),
            "per_class": {lab: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3),
                                "f1": round(float(f[i]), 3), "support": int(s[i])} for i, lab in enumerate(LABELS)},
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist()}


def _cv(x: list[str], y: list[str]) -> dict:
    """5 particiones sobre train+validación: más estable que un test pequeño (no toca el test)."""
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    s = cross_val_score(_pipeline(), x, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), scoring="f1_macro")
    return {"folds": 5, "macro_f1_mean": round(float(s.mean()), 4), "macro_f1_std": round(float(s.std()), 4)}


def _choose_threshold(proba, classes, y_true) -> tuple[float, float, float]:
    best = (0.5, 0.0, 0.0)
    for t in THRESHOLDS:
        if t < MIN_THRESHOLD:
            continue
        accepted = [(classes[row.argmax()], y) for row, y in zip(proba, y_true) if row.max() >= t]
        coverage = len(accepted) / len(y_true)
        acc = sum(p == y for p, y in accepted) / len(accepted) if accepted else 0.0
        if acc >= TARGET_ACCEPTED_ACCURACY and coverage >= MIN_COVERAGE:
            return t, coverage, acc  # el menor umbral que cumple: máxima cobertura
        if acc > best[2] and coverage >= MIN_COVERAGE:
            best = (t, coverage, acc)
    return best


def train(ds: Dataset, out_dir: str | Path) -> TrainResult:
    import joblib
    from nexus.core.classifier import rules_classify

    parts = split(ds.examples)
    xs = {k: [e.text for e in v] for k, v in parts.items()}
    ys = {k: [e.label for e in v] for k, v in parts.items()}
    pipe = _pipeline().fit(xs["train"], ys["train"])
    classes = list(pipe.classes_)

    threshold, val_cov, val_acc = _choose_threshold(pipe.predict_proba(xs["validation"]), classes, ys["validation"])

    test_proba = pipe.predict_proba(xs["test"])
    test_pred = [classes[row.argmax()] for row in test_proba]
    accepted = [(p, y) for p, y, row in zip(test_pred, ys["test"], test_proba) if row.max() >= threshold]
    manifest = ds.manifest()
    report = {
        "task": "intent_es_v1", "dataset": manifest,
        "splits": {k: len(v) for k, v in parts.items()},
        "threshold": threshold,
        "validation": {"coverage": round(val_cov, 3), "accepted_accuracy": round(val_acc, 3)},
        "test": {**_metrics(ys["test"], test_pred),
                 "coverage": round(len(accepted) / len(test_pred), 3),
                 "accepted_accuracy": round(sum(p == y for p, y in accepted) / len(accepted), 3) if accepted else 0.0,
                 "baseline_rules_macro_f1": _metrics(ys["test"], [rules_classify(x) for x in xs["test"]])["macro_f1"],
                 # Métrica principal: lo que de verdad enruta (modelo si supera el umbral; si no, reglas).
                 "hybrid_macro_f1": _metrics(ys["test"], [classes[row.argmax()] if row.max() >= threshold
                                                          else rules_classify(x)
                                                          for row, x in zip(test_proba, xs["test"])])["macro_f1"]},
        "cross_validation": _cv(xs["train"] + xs["validation"], ys["train"] + ys["validation"]),
        "model": {"features": "tfidf word(1,2) + char_wb(2,5)", "classifier": "LogisticRegression(C=10, balanced)"},
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f"intent_es_v1-{manifest['version'][7:19]}"
    path = out / f"{name}.joblib"
    joblib.dump({"pipeline": pipe, "threshold": threshold, "version": name}, path)
    (out / f"{name}.report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return TrainResult(str(path), _sha256(path), report)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path: str, expected_sha256: str) -> IntentModel:
    """joblib usa pickle: deserializar un archivo manipulado ejecuta código. Solo se carga si el hash
    coincide con el registrado al entrenar."""
    if _sha256(Path(path)) != expected_sha256:
        raise ValueError("ARTIFACT_HASH_MISMATCH")
    import joblib
    blob = joblib.load(path)
    return IntentModel(blob["pipeline"], blob["threshold"], blob["version"])
