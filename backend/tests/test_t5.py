"""T5 — aprendizaje continuo gobernado (documento TL §8, §12): ninguna corrección cambia el modelo en
producción; feedback -> revisión del propietario -> dataset versionado -> entrenamiento offline ->
evaluación (test bloqueado + regresión) -> promoción o no."""
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.learning import dataset, intent, registry
from tests.test_c1_api import FakeModel
from tests.test_learning import SEED

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(engine, tmp_path, monkeypatch):
    from nexus.api.app import create_app
    monkeypatch.setenv("NEXUS_MODELS_DIR", str(tmp_path / "models"))
    return TestClient(create_app(engine=engine, model=FakeModel("ok"), api_token="test-token", embedder=None))


def ask(client, text):
    tid = client.post("/api/v1/chat/messages", headers=AUTH, json={"message": text}).json()["task_id"]
    return tid, client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()


def test_each_task_records_its_request_class(client):
    tid, t = ask(client, "hola, ¿qué tal?")
    assert t["request_class"] == "conversation"


def test_feedback_is_validated_and_stays_pending(client):
    tid, _ = ask(client, f"¿cómo va lo del NAS de la oficina? {uuid.uuid4().hex[:6]}")
    bad = lambda body, t=tid: client.post(f"/api/v1/tasks/{t}/feedback", headers=AUTH, json=body)  # noqa: E731
    assert bad({"correct_label": "conversation"}).json()["detail"] == "SAME_LABEL"
    assert bad({"correct_label": "inventada"}).status_code == 422
    assert bad({"correct_label": "knowledge_query"}, "task_nope").status_code == 404
    assert client.post(f"/api/v1/tasks/{tid}/feedback", json={"correct_label": "knowledge_query"}).status_code == 401
    r = bad({"correct_label": "knowledge_query"})
    assert r.status_code == 201 and r.json()["status"] == "pending"
    assert bad({"correct_label": "knowledge_query"}).json()["detail"] == "FEEDBACK_EXISTS"
    pending = client.get("/api/v1/learning/feedback", headers=AUTH, params={"status": "pending"}).json()["feedback"]
    fb = next(f for f in pending if f["task_id"] == tid)
    assert fb["predicted_label"] == "conversation" and fb["corrected_label"] == "knowledge_query"


def test_messages_with_secrets_never_become_examples(client):
    tid, _ = ask(client, "mi password=Secreta123 no funciona")
    r = client.post(f"/api/v1/tasks/{tid}/feedback", headers=AUTH, json={"correct_label": "feedback"})
    assert r.status_code == 422 and r.json()["detail"] == "SECRET_DETECTED"


def test_owner_review_and_dataset_from_feedback(client, engine):
    tid, _ = ask(client, f"pásame lo que tengo sobre el router {uuid.uuid4().hex[:6]}")
    fid = client.post(f"/api/v1/tasks/{tid}/feedback", headers=AUTH, json={"correct_label": "knowledge_query"}).json()["feedback_id"]
    with engine.connect() as c:
        assert fid not in {e.source_ref for e in dataset.from_feedback(c)}  # sin revisar no entra
    r = client.post(f"/api/v1/learning/feedback/{fid}/review", headers=AUTH, json={"decision": "approve"})
    assert r.status_code == 200
    assert client.post(f"/api/v1/learning/feedback/{fid}/review", headers=AUTH, json={"decision": "reject"}).status_code == 409
    with engine.connect() as c:
        ex = next(e for e in dataset.from_feedback(c) if e.source_ref == f"feedback:{fid}")
    assert ex.source_type == "owner_feedback" and ex.label == "knowledge_query" and ex.review_status == "approved"


def test_feedback_goes_to_train_and_the_test_set_stays_locked():
    seed = dataset.load(SEED)
    fb = [dataset.Example(example_id=f"fb-{i}", task="intent_es_v1", text=f"ejemplo real número {i}",
                          label="conversation", language="es", source_type="owner_feedback",
                          source_ref=f"feedback:{i}", license_or_permission="owner-provided",
                          review_status="approved", schema_version=1) for i in range(30)]
    before, after = dataset.split(seed.examples), dataset.split(seed.examples + fb)
    for part in ("validation", "test"):
        assert [e.example_id for e in before[part]] == [e.example_id for e in after[part]]
    assert all(e.example_id in {x.example_id for x in after["train"]} for e in fb)
    assert dataset.Dataset(seed.examples + fb).manifest()["version"] != seed.manifest()["version"]


def test_retrain_from_api_registers_a_candidate_with_feedback(client, engine):
    r = client.post("/api/v1/learning/train", headers=AUTH)
    assert r.status_code == 202
    models = client.get("/api/v1/learning/models", headers=AUTH).json()["models"]
    newest = models[0]
    assert newest["status"] == "candidate" and newest["metrics"]["dataset"]["examples"] >= 183
    assert "feedback_examples" in newest["metrics"]["dataset"]
    with engine.begin() as c:
        registry.retire(c, newest["id"])


def test_promotion_blocks_regressions_against_the_active_model(engine, tmp_path):
    good = intent.train(dataset.load(SEED), tmp_path)
    worse = intent.TrainResult(good.artifact_path, good.artifact_sha256, {
        **good.report, "test": {**good.report["test"], "hybrid_macro_f1": good.report["test"]["hybrid_macro_f1"] - 0.05}})
    with engine.begin() as c:
        active_before = c.scalar(sa.text("SELECT id FROM model_registry WHERE task='intent_es' AND status='active'"))
        gid, wid = registry.register(c, "intent_es", good), registry.register(c, "intent_es", worse)
        registry.promote(c, gid)
        with pytest.raises(registry.RegistryError, match="REGRESSION"):
            registry.promote(c, wid)  # supera a las reglas, pero empeora respecto al activo
        registry.retire(c, gid)
        registry.retire(c, wid)
        if active_before:
            c.execute(sa.text("UPDATE model_registry SET status='active' WHERE id=:i"), {"i": active_before})
