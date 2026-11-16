"""Clasificador de intención propio en español (documento Text Learning §4.3, §7; fase T1).

TF-IDF de palabras (1–2) + caracteres (2–5, robusto a faltas y variantes) -> LogisticRegression con
pesos equilibrados. Umbral de abstención calibrado en validación; métricas en el test bloqueado;
comparación con la línea base de reglas (classifier.rules_classify). Es una señal de enrutamiento,
nunca una autorización (Doc 02 §4).

T3 (variante "+enc"): a esas features se suman los embeddings del encoder multilingüe que ya usa el RAG
(MiniLM, congelado). Medido con 463 ejemplos: test 0,844 -> 0,88 y 14 -> 17 de 20 sondas no vistas.
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


class EncoderFeatures:
    """Embeddings L2 del encoder como features densas. La sesión ONNX no se serializa: el artefacto solo
    guarda nombre+versión del encoder y `load` inyecta uno idéntico (vectores de otro modelo = basura).
    ponytail: encoder congelado (sin torch). Afinarlo solo si se queda corto con datos reales."""

    def __init__(self, embedder):
        self.embedder = embedder
        self.encoder = {"name": embedder.model_name, "version": embedder.model_version}
        self._cache: dict[str, list[float]] = {}

    def fit(self, x, y=None):
        return self

    def transform(self, texts):
        import numpy as np
        from scipy.sparse import csr_matrix
        missing = [t for t in dict.fromkeys(texts) if t not in self._cache]
        if missing:
            self._cache.update(zip(missing, self.embedder.embed(missing)))
        return csr_matrix(np.array([self._cache[t] for t in texts]))

    def get_params(self, deep=True):
        return {}

    def __sklearn_clone__(self):  # validación cruzada: comparte encoder y caché (no copia la sesión ONNX)
        twin = EncoderFeatures(self.embedder)
        twin._cache = self._cache
        return twin

    def __getstate__(self):
        return {"encoder": self.encoder}

    def __setstate__(self, state):
        self.encoder, self.embedder, self._cache = state["encoder"], None, {}


def _pipeline(encoder=None):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import FeatureUnion, Pipeline
    feats = [("word", TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True)),
             ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True))]
    if encoder is not None:
        feats.append(("encoder", EncoderFeatures(encoder)))
    return Pipeline([
        ("features", FeatureUnion(feats)),
        ("clf", LogisticRegression(max_iter=3000, class_weight="balanced", C=10.0, random_state=0)),
    ])


def _metrics(y_true: list[str], y_pred: list[str]) -> dict:
    from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=LABELS, zero_division=0)
    return {"macro_f1": round(float(f1_score(y_true, y_pred, labels=LABELS, average="macro", zero_division=0)), 4),
            "per_class": {lab: {"precision": round(float(p[i]), 3), "recall": round(float(r[i]), 3),
                                "f1": round(float(f[i]), 3), "support": int(s[i])} for i, lab in enumerate(LABELS)},
            "confusion_matrix": confusion_matrix(y_true, y_pred, labels=LABELS).tolist()}


def _cv(x: list[str], y: list[str], encoder=None) -> dict:
    """5 particiones sobre train+validación: más estable que un test pequeño (no toca el test)."""
    from sklearn.model_selection import StratifiedKFold, cross_val_score
    s = cross_val_score(_pipeline(encoder), x, y, cv=StratifiedKFold(5, shuffle=True, random_state=0), scoring="f1_macro")
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


def _external(pipe, threshold, exam: Dataset) -> dict:
    """Examen externo fijo (frases de los tests de GALA nunca vistas en entrenamiento): mide si generaliza."""
    from nexus.core.classifier import rules_classify
    xs, ys = [e.text for e in exam.examples], [e.label for e in exam.examples]
    classes, proba = list(pipe.classes_), pipe.predict_proba(xs)
    model = [classes[row.argmax()] for row in proba]
    hybrid = [m if row.max() >= threshold else rules_classify(x) for m, row, x in zip(model, proba, xs)]
    acc = lambda pred: round(sum(p == y for p, y in zip(pred, ys)) / len(ys), 3)  # noqa: E731
    return {"name": exam.manifest()["version"][:19], "examples": len(ys), "model_accuracy": acc(model),
            "hybrid_accuracy": acc(hybrid), "rules_accuracy": acc([rules_classify(x) for x in xs]),
            "misses": [{"text": x, "label": y, "predicted": h} for x, y, h in zip(xs, ys, hybrid) if h != y]}


def train(ds: Dataset, out_dir: str | Path, encoder=None, external: Dataset | None = None) -> TrainResult:
    import joblib
    from nexus.core.classifier import rules_classify

    parts = split(ds.examples)
    xs = {k: [e.text for e in v] for k, v in parts.items()}
    ys = {k: [e.label for e in v] for k, v in parts.items()}
    pipe = _pipeline(encoder).fit(xs["train"], ys["train"])
    classes = list(pipe.classes_)

    threshold, val_cov, val_acc = _choose_threshold(pipe.predict_proba(xs["validation"]), classes, ys["validation"])

    test_proba = pipe.predict_proba(xs["test"])
    test_pred = [classes[row.argmax()] for row in test_proba]
    accepted = [(p, y) for p, y, row in zip(test_pred, ys["test"], test_proba) if row.max() >= threshold]
    manifest = ds.manifest()
    variant = "+enc" if encoder is not None else ""
    model_info = {"features": "tfidf word(1,2) + char_wb(2,5)", "classifier": "LogisticRegression(C=10, balanced)"}
    if encoder is not None:
        model_info |= {"features": model_info["features"] + " + embeddings del encoder",
                       "encoder": {"name": encoder.model_name, "version": encoder.model_version}}
    report = {
        "task": "intent_es_v1", "variant": variant, "dataset": manifest,
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
        "cross_validation": _cv(xs["train"] + xs["validation"], ys["train"] + ys["validation"], encoder),
        "model": model_info,
    }
    if external is not None and external.examples:
        report["external_eval"] = _external(pipe, threshold, external)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = f"intent_es_v1{variant.replace('+', '-')}-{manifest['version'][7:19]}"
    # Nombre con el hash del contenido: un reentrenamiento con el mismo dataset no puede pisar el artefacto de
    # un modelo registrado (medido: el activo dejó de cargar con ARTIFACT_HASH_MISMATCH).
    tmp = out / f"{name}.joblib.tmp"
    joblib.dump({"pipeline": pipe, "threshold": threshold, "version": name}, tmp)
    sha = _sha256(tmp)
    path = out / f"{name}-{sha[7:19]}.joblib"
    tmp.replace(path)
    path.with_suffix(".report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return TrainResult(str(path), sha, report)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path: str, expected_sha256: str, embedder=None) -> IntentModel:
    """joblib usa pickle: deserializar un archivo manipulado ejecuta código. Solo se carga si el hash
    coincide con el registrado al entrenar. Variante +enc: necesita el MISMO encoder con que se entrenó."""
    if _sha256(Path(path)) != expected_sha256:
        raise ValueError("ARTIFACT_HASH_MISMATCH")
    import joblib
    blob = joblib.load(path)
    for _name, step in blob["pipeline"].named_steps["features"].transformer_list:
        if isinstance(step, EncoderFeatures):
            if embedder is None:
                raise ValueError("ENCODER_UNAVAILABLE")
            if {"name": embedder.model_name, "version": embedder.model_version} != step.encoder:
                raise ValueError("ENCODER_MISMATCH")
            step.embedder = embedder
    return IntentModel(blob["pipeline"], blob["threshold"], blob["version"])
