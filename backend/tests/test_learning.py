"""Text Learning T0/T1 (documento TL §4–8, §12): dataset gobernado + clasificador de intención propio."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nexus.learning import dataset, intent, registry

SEED = Path(__file__).resolve().parents[1] / "data" / "intent" / "intent_es_v1.jsonl"


def ex(i, text, label="conversation", **over):
    return {"example_id": f"t-{i}", "task": "intent_es_v1", "text": text, "label": label, "language": "es",
            "source_type": "owner_feedback", "source_ref": "test", "license_or_permission": "owner-provided",
            "review_status": "approved", "schema_version": 1, **over}


def write(tmp_path, rows):
    p = tmp_path / "d.jsonl"
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    return p


# --- T0: datos gobernados (TL §4.4, §5, §6) ---
def test_schema_requires_provenance_permission_and_known_label(tmp_path):
    rows = [ex(1, "hola"), {**ex(2, "sin licencia"), "license_or_permission": ""}, ex(3, "x", label="inventada"),
            {k: v for k, v in ex(4, "sin fuente").items() if k != "source_ref"}]
    ds = dataset.load(write(tmp_path, rows))
    assert [e.example_id for e in ds.examples] == ["t-1"]
    assert {r["example_id"]: r["reason"].split(":")[0] for r in ds.rejected} == {
        "t-2": "INVALID_SCHEMA", "t-3": "INVALID_SCHEMA", "t-4": "INVALID_SCHEMA"}


def test_secrets_never_enter_the_corpus(tmp_path):
    ds = dataset.load(write(tmp_path, [ex(1, "mi token=abc123456789 para github"), ex(2, "hola")]))
    assert [e.example_id for e in ds.examples] == ["t-2"] and ds.rejected[0]["reason"] == "SECRET_DETECTED"


def test_only_approved_examples_and_dedup_after_normalization(tmp_path):
    rows = [ex(1, "Hola  NEXUS"), ex(2, "hola nexus"), ex(3, "pendiente", review_status="needs_review")]
    ds = dataset.load(write(tmp_path, rows))
    assert [e.example_id for e in ds.examples] == ["t-1"]  # duplicado (normalizado) y no aprobado fuera
    reasons = {r["example_id"]: r["reason"] for r in ds.rejected}
    assert reasons == {"t-2": "DUPLICATE", "t-3": "NOT_APPROVED"}


def test_split_is_deterministic_stratified_and_disjoint():
    ds = dataset.load(SEED)
    a, b = dataset.split(ds.examples), dataset.split(ds.examples)
    assert {k: [e.example_id for e in v] for k, v in a.items()} == {k: [e.example_id for e in v] for k, v in b.items()}
    ids = [set(e.example_id for e in a[k]) for k in ("train", "validation", "test")]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    for part in ("validation", "test"):  # todas las clases aparecen en validación y test
        assert {e.label for e in a[part]} == set(intent.LABELS)


def test_manifest_hash_identifies_the_exact_dataset(tmp_path):
    p = write(tmp_path, [ex(1, "hola"), ex(2, "adiós")])
    m1 = dataset.load(p).manifest()
    assert m1["examples"] == 2 and m1["version"].startswith("sha256:")
    p.write_text(p.read_text(encoding="utf-8") + "\n" + json.dumps(ex(3, "nuevo")), encoding="utf-8")
    assert dataset.load(p).manifest()["version"] != m1["version"]


def test_seed_dataset_is_valid_and_covers_every_class():
    ds = dataset.load(SEED)
    assert ds.rejected == [] and len(ds.examples) >= 150
    counts = ds.manifest()["label_counts"]
    assert set(counts) == set(intent.LABELS) and min(counts.values()) >= 15


# --- T1: clasificador TF-IDF + LogisticRegression con abstención (TL §4.3, §7) ---
@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    return intent.train(dataset.load(SEED), tmp_path_factory.mktemp("models"))


def test_training_is_reproducible_and_reports_per_class(trained, tmp_path):
    again = intent.train(dataset.load(SEED), tmp_path)
    assert again.report["test"]["macro_f1"] == trained.report["test"]["macro_f1"]
    r = trained.report
    assert set(r["test"]["per_class"]) == set(intent.LABELS)
    assert len(r["test"]["confusion_matrix"]) == len(intent.LABELS)
    assert 0 < r["threshold"] < 1 and 0 < r["test"]["coverage"] <= 1
    assert r["dataset"]["version"] == dataset.load(SEED).manifest()["version"]


def test_beats_the_keyword_rules_baseline(trained):
    """TL §7: criterio inicial de promoción = superar la línea base en la métrica principal."""
    t = trained.report["test"]
    assert t["hybrid_macro_f1"] > t["baseline_rules_macro_f1"] and t["macro_f1"] > t["baseline_rules_macro_f1"]
    assert 0 < trained.report["cross_validation"]["macro_f1_mean"] <= 1


def test_abstains_on_text_without_signal(trained):
    model = intent.load(trained.artifact_path, trained.artifact_sha256)
    label, confidence = model.predict("zxq plf wrr")
    assert label is None and confidence < model.threshold
    assert model.predict("según mis documentos, ¿qué presupuesto tiene Helios?")[0] == "knowledge_query"


def test_tampered_artifact_is_never_loaded(trained, tmp_path):
    """El artefacto se deserializa con joblib (pickle): solo si su sha256 coincide con el registrado."""
    copy = tmp_path / "m.joblib"
    copy.write_bytes(Path(trained.artifact_path).read_bytes() + b"x")
    with pytest.raises(ValueError, match="ARTIFACT_HASH_MISMATCH"):
        intent.load(str(copy), trained.artifact_sha256)


# --- Registro, promoción e integración (TL §8: sin auto-modificación; promoción del propietario) ---
def test_registry_promotion_and_classifier_integration(engine, trained):
    from nexus.core import classifier
    with engine.begin() as c:
        mid = registry.register(c, "intent_es", trained)
        assert registry.get(c, mid)["status"] == "candidate"
        assert classifier.classify("¿qué sabes del NAS?") == "conversation"  # sin modelo activo: reglas
        registry.promote(c, mid)
        assert registry.get(c, mid)["status"] == "active"
    registry.activate_intent(engine)
    try:
        assert classifier.active_model() is not None
        assert classifier.classify("¿qué sabes del NAS?") == "knowledge_query"
        assert classifier.classify("?!") == "unknown"
    finally:
        classifier.set_model(None)
        with engine.begin() as c:
            registry.retire(c, mid)  # no dejar un modelo activo en la DB de tests


def test_promotion_requires_beating_the_baseline(engine, trained):
    worse = intent.TrainResult(trained.artifact_path, trained.artifact_sha256,
                               {**trained.report, "test": {**trained.report["test"], "macro_f1": 0.1,
                                                            "hybrid_macro_f1": 0.1}})
    with engine.begin() as c:
        mid = registry.register(c, "intent_es", worse)
        with pytest.raises(registry.RegistryError, match="NOT_BETTER_THAN_BASELINE"):
            registry.promote(c, mid)


def test_learning_api(engine, trained):
    from nexus.api.app import create_app
    from tests.test_c1_api import FakeModel
    with engine.begin() as c:
        mid = registry.register(c, "intent_es", trained)
    client = TestClient(create_app(engine=engine, model=FakeModel(), api_token="test-token", embedder=None))
    auth = {"Authorization": "Bearer test-token"}
    assert client.get("/api/v1/learning/models").status_code == 401
    models = client.get("/api/v1/learning/models", headers=auth).json()["models"]
    assert any(m["id"] == mid and m["metrics"]["test"]["macro_f1"] > 0 for m in models)
    r = client.post(f"/api/v1/learning/models/{mid}/promote", headers=auth)
    assert r.status_code == 200 and r.json()["status"] == "active"
    from nexus.core import classifier
    try:
        assert classifier.active_model() is not None  # se activa sin reiniciar
    finally:
        classifier.set_model(None)
        with engine.begin() as c:
            registry.retire(c, mid)
