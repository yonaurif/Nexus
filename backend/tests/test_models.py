"""Model Router (Doc 02 §10): GGUF local en proceso o modelo Python propio; sin servicios externos."""
from nexus.core.models import LlamaCppModel, StubModel, get_model


class FakeLlama:
    instances = 0

    def __init__(self, **kwargs):
        FakeLlama.instances += 1
        self.kwargs, self.calls = kwargs, []

    def create_chat_completion(self, messages, **kw):
        self.calls.append((messages, kw))
        return {"choices": [{"message": {"content": " hola desde gguf "}}]}


class MyOwnModel:
    """Ejemplo de 'tu propia IA': solo necesita name, generate() y health()."""
    name = "mi-ia"

    def generate(self, messages):
        return "respuesta propia"

    def health(self):
        return "ok"


def test_gguf_model_loads_once_and_generates(tmp_path):
    gguf = tmp_path / "modelo.gguf"
    gguf.write_bytes(b"GGUF")
    FakeLlama.instances = 0
    m = LlamaCppModel(str(gguf), n_ctx=2048, n_gpu_layers=20, llama_cls=FakeLlama)
    msgs = [{"role": "user", "content": "hola"}]
    assert m.generate(msgs) == "hola desde gguf"
    m.generate(msgs)
    assert FakeLlama.instances == 1  # carga perezosa, una sola vez
    llama = m._llama
    assert llama.kwargs["model_path"] == str(gguf) and llama.kwargs["n_gpu_layers"] == 20
    assert llama.calls[0][0] == msgs
    assert m.name == "gguf:modelo.gguf" and m.health() == "ok"


def test_gguf_missing_file_is_reported(tmp_path):
    assert LlamaCppModel(str(tmp_path / "no.gguf"), llama_cls=FakeLlama).health() == "model_missing"


def test_router_selection(monkeypatch, tmp_path):
    for k in ("NEXUS_MODEL", "NEXUS_GGUF_PATH"):
        monkeypatch.delenv(k, raising=False)
    assert isinstance(get_model(), StubModel)

    monkeypatch.setenv("NEXUS_GGUF_PATH", str(tmp_path / "m.gguf"))
    assert isinstance(get_model(), LlamaCppModel)

    monkeypatch.setenv("NEXUS_MODEL", "tests.test_models:MyOwnModel")  # tiene prioridad
    assert get_model().generate([]) == "respuesta propia"
