"""M3 — memoria semántica (Doc 03 §3.2, §6.1, §7.3, §9.2, §10): lo que dice el propietario entra como hecho
`suggested` con evidencia; solo lo confirmado se usa como dato; las contradicciones quedan como conflicto."""
import json
import uuid

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from nexus.memory import facts

AUTH = {"Authorization": "Bearer test-token"}


class FactModel:
    """Extrae lo que le digan (JSON) y responde con texto fijo; guarda lo que recibe."""
    name, configured = "fact-model", True

    def __init__(self, extracted=None, reply="De acuerdo."):
        self.extracted, self.reply, self.calls = extracted or [], reply, []

    def generate(self, messages):
        self.calls.append(messages)
        if facts.EXTRACTOR_MARK in messages[0]["content"]:
            return json.dumps({"facts": self.extracted}, ensure_ascii=False)
        return self.reply

    def health(self):
        return "ok"


def tag():
    return uuid.uuid4().hex[:6]


def owner():
    return f"owner_{tag()}"


def fact(subject, predicate, obj, entity=False, stype="project", otype=None):
    return {"subject": subject, "subject_type": stype, "predicate": predicate, "object": obj,
            "object_is_entity": entity, "object_type": otype}


# --- Extracción: el modelo propone, el código valida (nunca autoridad del LLM) ---
def test_extract_validates_normalizes_and_limits():
    model = FactModel([fact("yo", "Se Llama", "Yona", stype="person"),
                       fact("NAS", "ubicado en", "oficina de Madrid", entity=True, stype="device", otype="place"),
                       fact("x", "a", "b"), fact("y", "usa", "z"), fact("w", "usa", "q")])
    got = facts.extract(model, "me llamo Yona y el NAS está en la oficina de Madrid")
    assert len(got) == facts.MAX_PER_MESSAGE == 3
    assert (got[0].subject, got[0].predicate) == (facts.OWNER, "se_llama")
    assert got[1].predicate == "ubicado_en" and got[1].object_is_entity


@pytest.mark.parametrize("raw", ["no es json", json.dumps({"facts": [{"subject": ""}]}), json.dumps({"facts": []})])
def test_extract_falls_back_to_the_owner_statement(raw):
    class Bad(FactModel):
        def generate(self, messages):
            return raw
    got = facts.extract(Bad(), "Recuerda que prefiero respuestas cortas")
    assert [(g.subject, g.predicate, g.object) for g in got] == [(facts.OWNER, "dice", "prefiero respuestas cortas")]


def test_passwords_and_secrets_never_enter_memory():
    assert facts.sensitive("recuerda que la contraseña del wifi es hunter22")
    assert facts.sensitive("guarda ghp_" + "a" * 36)
    assert not facts.sensitive("recuerda que prefiero respuestas cortas")


# --- Entidades y evidencia (Doc 03 §7.3: no una entidad por mención) ---
def test_entities_are_deduplicated_and_facts_accumulate_evidence(conn):
    o, t = owner(), tag()
    p1 = facts.Proposal(**fact(f"Proyecto Hélios {t}", "usa", "Python", entity=True, otype="technology"))
    p2 = facts.Proposal(**fact(f"proyecto helios {t}", "usa", "python", entity=True, otype="technology"))
    a = facts.propose(conn, o, [p1], source_ref="task:a", quote="usa Python")
    b = facts.propose(conn, o, [p2], source_ref="task:b", quote="usa python")
    assert a[0]["fact_id"] == b[0]["fact_id"] and a[0]["status"] == "suggested"
    assert conn.scalar(sa.text("SELECT count(*) FROM entities WHERE owner_id=:o"), {"o": o}) == 2
    assert conn.scalar(sa.text("SELECT count(*) FROM fact_evidence WHERE fact_id=:f"), {"f": a[0]["fact_id"]}) == 2
    aliases = conn.scalars(sa.text("SELECT alias FROM entity_aliases a JOIN entities e ON e.id=a.entity_id "
                                   "WHERE e.owner_id=:o"), {"o": o}).all()
    assert f"proyecto helios {t}" in aliases  # la otra grafía queda como alias


# --- Estados y contradicciones (Doc 03 §6.1, §9.2) ---
def horario(o, conn, value):
    p = facts.Proposal(**fact("propietario", "horario_laboral", value, stype="owner"))
    return facts.propose(conn, o, [p], source_ref="task:x", quote=value)[0]


def test_contradiction_is_kept_until_the_owner_resolves_it(conn):
    o = owner()
    old = horario(o, conn, "de 9 a 18")
    facts.review(conn, o, old["fact_id"], "confirm")
    new = horario(o, conn, "de 8 a 17")
    assert new["conflicts"] == ["propietario · horario_laboral · de 9 a 18"]
    facts.review(conn, o, new["fact_id"], "confirm", replace=True)
    st = dict(conn.execute(sa.text("SELECT id, status FROM facts WHERE owner_id=:o"), {"o": o}).all())
    assert st == {old["fact_id"]: "superseded", new["fact_id"]: "confirmed"}
    row = conn.execute(sa.text("SELECT status, resolution FROM knowledge_conflicts WHERE owner_id=:o"), {"o": o}).one()
    assert tuple(row) == ("resolved", "replaced")
    with pytest.raises(facts.FactError, match="ALREADY_REVIEWED"):
        facts.review(conn, o, new["fact_id"], "reject")


def test_rejected_fact_resolves_its_conflict_and_is_not_used(conn):
    o = owner()
    facts.review(conn, o, horario(o, conn, "de 9 a 18")["fact_id"], "confirm")
    new = horario(o, conn, "de 10 a 19")
    facts.review(conn, o, new["fact_id"], "reject")
    assert conn.scalar(sa.text("SELECT resolution FROM knowledge_conflicts WHERE fact_b_id=:f"),
                       {"f": new["fact_id"]}) == "rejected"
    assert [f["object"] for f in facts.relevant(conn, o, "hola")] == ["de 9 a 18"]


def test_only_confirmed_facts_reach_the_context(conn):
    o, t = owner(), tag()
    nas = facts.Proposal(**fact(f"NAS{t}", "ubicado_en", "oficina de Madrid", stype="device"))
    pref = facts.Proposal(**fact("propietario", "prefiere", "respuestas cortas", stype="owner"))
    f_nas, f_pref = facts.propose(conn, o, [nas, pref], source_ref="task:x", quote="...")
    assert facts.relevant(conn, o, f"¿dónde está el NAS{t}?") == []  # sugeridos: no son datos
    facts.review(conn, o, f_nas["fact_id"], "confirm")
    facts.review(conn, o, f_pref["fact_id"], "confirm")
    assert [f["object"] for f in facts.relevant(conn, o, "hola")] == ["respuestas cortas"]  # sobre el propietario
    got = facts.relevant(conn, o, f"¿dónde está el nas{t}?")
    assert {f["object"] for f in got} == {"respuestas cortas", "oficina de Madrid"}


# --- De punta a punta por la API ---
@pytest.fixture
def make_client(engine):
    from nexus.api.app import create_app
    return lambda model: TestClient(create_app(engine=engine, model=model, api_token="test-token", embedder=None))


def ask(client, text):
    tid = client.post("/api/v1/chat/messages", headers=AUTH, json={"message": text}).json()["task_id"]
    return tid, client.get(f"/api/v1/tasks/{tid}", headers=AUTH).json()


def test_memory_update_becomes_a_suggestion_then_evidence_after_confirmation(make_client):
    t = tag()
    model = FactModel([fact(f"NAS{t}", "ubicado_en", "oficina de Madrid", stype="device")],
                      reply="Está en la oficina de Madrid.")
    client = make_client(model)
    tid, task = ask(client, f"recuerda que el NAS{t} está en la oficina de Madrid")
    assert task["status"] == "completed" and task["request_class"] == "memory_update"
    assert "sugerencia" in task["response"]["text"] and "ubicado_en" in task["response"]["text"]
    fid = task["response"]["sources"][0]["source_ref"].removeprefix("fact:")

    listed = client.get("/api/v1/memory/facts?status=suggested", headers=AUTH).json()["facts"]
    mine = next(f for f in listed if f["fact_id"] == fid)
    assert mine["subject"] == f"NAS{t}" and mine["evidence"][0]["source_ref"] == f"task:{tid}"

    # Sin confirmar: la pregunta no tiene evidencia (abstención en código)
    _, before = ask(client, f"¿qué sabes del NAS{t}?")
    assert "NO_EVIDENCE:knowledge" in before["response"]["warnings"]

    r = client.post(f"/api/v1/memory/facts/{fid}/review", headers=AUTH, json={"decision": "confirm"})
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert client.post(f"/api/v1/memory/facts/{fid}/review", headers=AUTH,
                       json={"decision": "confirm"}).status_code == 409

    _, after = ask(client, f"¿qué sabes del NAS{t}?")
    assert after["status"] == "completed" and after["response"]["sources"][0]["source_ref"] == f"fact:{fid}"
    ctx = json.dumps(model.calls[-1], ensure_ascii=False)
    assert f"NAS{t} · ubicado_en · oficina de Madrid" in ctx and "confirmados por el propietario" in ctx


def test_memory_update_with_a_password_is_refused(make_client, engine):
    client = make_client(FactModel([fact("wifi", "contraseña", "hunter22")]))
    _, task = ask(client, "recuerda que la contraseña del wifi es hunter22")
    assert "SECRET_DETECTED" in task["response"]["warnings"]
    with engine.connect() as c:
        assert not c.scalar(sa.text("SELECT count(*) FROM facts WHERE object_value LIKE '%hunter22%'"))


def test_unknown_fact_review_is_404(make_client):
    r = make_client(FactModel()).post("/api/v1/memory/facts/fct_nope/review", headers=AUTH,
                                      json={"decision": "confirm"})
    assert r.status_code == 404


def test_the_order_itself_is_not_a_predicate():
    """Medido con Qwen: devolvió «propietario · recuerda · <frase>». Eso no es un hecho: se cae al respaldo."""
    got = facts.extract(FactModel([fact("propietario", "recuerda", "el NAS está en el rack 2", stype="owner")]),
                        "recuerda que el NAS está en el rack 2")
    assert [(g.predicate, g.object) for g in got] == [("dice", "el NAS está en el rack 2")]
