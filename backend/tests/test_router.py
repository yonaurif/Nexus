"""Router de modelos según el hardware (Doc 02 §10, Doc 04 §12, D19). Portado de Primitivo Worker
(hardware.py, engine_llamacpp.auto_gpu_layers) y de Primitivo gala/model_fallback.py."""
import pytest

from nexus.core import hardware
from nexus.core.models import FallbackModel, LlamaCppModel, auto_gpu_layers, get_model

MSGS = [{"role": "user", "content": "hola"}]


def hw(ram_free=16.0, vram_free=8.0):
    return lambda: {"ram_total_gb": 32.0, "ram_free_gb": ram_free, "cpu_cores": 8, "gpu": "Test GPU",
                    "vram_total_gb": vram_free, "vram_free_gb": vram_free}


class FakeLlama:
    created: list = []
    fail_load: set = set()
    fail_generate: dict = {}

    def __init__(self, model_path, **kw):
        if model_path in FakeLlama.fail_load:
            raise ValueError(f"Failed to load model from file: {model_path}")
        self.path, self.kw = model_path, kw
        FakeLlama.created.append(self)

    def create_chat_completion(self, messages, **kw):
        if exc := FakeLlama.fail_generate.get(self.path):
            raise exc
        return {"choices": [{"message": {"content": f"respuesta de {self.path.split('/')[-1].split(chr(92))[-1]}"}}]}


@pytest.fixture(autouse=True)
def reset_fake():
    FakeLlama.created, FakeLlama.fail_load, FakeLlama.fail_generate = [], set(), {}


SIZES: dict[str, float] = {}  # tamaño SIMULADO por ruta, en GB


def gguf(tmp_path, name, size_gb=0.001):
    """GGUF falso de 4 bytes con tamaño simulado. Nunca crear archivos grandes: en Windows el
    archivo "disperso" escribía los GB reales en disco (llegó a 108 GB en el Temp de pytest)."""
    p = tmp_path / name
    p.write_bytes(b"GGUF")
    SIZES[str(p)] = size_gb
    return str(p)


class SizedModel(LlamaCppModel):
    @property
    def size_gb(self):
        return SIZES.get(str(self.path), super().size_gb)


def model(path, **kw):
    kw.setdefault("hardware", hw())
    kw.setdefault("offload", True)
    kw.setdefault("block_count", 32)
    return SizedModel(path, llama_cls=FakeLlama, **kw)


# --- Capas en GPU (casos del Worker: tests/test_engine_llamacpp.py) ---
def test_auto_gpu_layers_full_partial_and_cpu():
    assert auto_gpu_layers(2.0, 6.0, 28, True) == -1   # cabe con margen -> todas
    assert auto_gpu_layers(8.0, 6.0, 32, True) == 19   # no cabe: ~(6*.92-.6)/8 de las capas
    assert auto_gpu_layers(8.0, 0.5, 32, True) == 0    # sin hueco útil -> CPU
    assert auto_gpu_layers(2.0, 6.0, 28, False) == 0   # llama-cpp compilado solo CPU
    assert auto_gpu_layers(2.0, 0, 28, True) == 0      # sin GPU


def test_layers_are_resolved_from_hardware_at_load(tmp_path):
    big = gguf(tmp_path, "big.gguf", 8.0)
    assert model(big, hardware=hw(vram_free=6.0)).load().kw["n_gpu_layers"] == 19
    assert model(big, hardware=hw(vram_free=0.0)).load().kw["n_gpu_layers"] == 0
    assert model(big, offload=False).load().kw["n_gpu_layers"] == 0
    assert model(gguf(tmp_path, "small.gguf"), hardware=hw(vram_free=6.0)).load().kw["n_gpu_layers"] == -1
    assert model(big, n_gpu_layers=12).load().kw["n_gpu_layers"] == 12  # valor fijo: se respeta


def test_fits_checks_ram_plus_usable_vram(tmp_path):
    p = gguf(tmp_path, "m.gguf", 6.0)
    assert model(p, hardware=hw(ram_free=2.0, vram_free=8.0)).fits() is None   # cabe gracias a la GPU
    assert model(p, hardware=hw(ram_free=8.0, vram_free=0.0)).fits() is None   # cabe en RAM
    reason = model(p, hardware=hw(ram_free=2.0, vram_free=0.0)).fits()
    assert reason.startswith("INSUFFICIENT_MEMORY")
    assert model(p, offload=False, hardware=hw(ram_free=2.0, vram_free=8.0)).fits().startswith("INSUFFICIENT_MEMORY")


# --- Cadena de respaldo (Primitivo model_fallback.py) ---
def test_unfit_model_is_skipped_without_loading(tmp_path):
    huge = gguf(tmp_path, "huge.gguf", 40.0)
    small = gguf(tmp_path, "small.gguf")
    fb = FallbackModel([model(huge), model(small)])
    assert fb.generate(MSGS) == "respuesta de small.gguf"
    assert [l.path for l in FakeLlama.created] == [small]  # el enorme ni se intentó cargar
    d = fb.details()
    assert d["active"] == "gguf:small.gguf" and d["candidates"][0]["status"] == "unfit"


def test_load_failure_falls_back_to_next(tmp_path):
    a, b = gguf(tmp_path, "a.gguf"), gguf(tmp_path, "b.gguf")
    FakeLlama.fail_load = {a}
    fb = FallbackModel([model(a), model(b)])
    assert fb.generate(MSGS) == "respuesta de b.gguf"
    assert fb.details()["candidates"][0] == {"name": "gguf:a.gguf", "status": "failed",
                                             "reason": "LOAD_FAILED", "gpu_layers": None}
    assert fb.name == "gguf:b.gguf"


def test_runtime_failure_unloads_and_switches(tmp_path):
    a, b = gguf(tmp_path, "a.gguf"), gguf(tmp_path, "b.gguf")
    fb = FallbackModel([model(a), model(b)])
    assert fb.generate(MSGS) == "respuesta de a.gguf"
    FakeLlama.fail_generate = {a: RuntimeError("CUDA error: out of memory")}
    assert fb.generate(MSGS) == "respuesta de b.gguf"
    assert fb.candidates[0]._llama is None  # liberado antes de cargar el siguiente (un modelo en memoria)


def test_request_errors_do_not_switch_models(tmp_path):
    a, b = gguf(tmp_path, "a.gguf"), gguf(tmp_path, "b.gguf")
    fb = FallbackModel([model(a), model(b)])
    FakeLlama.fail_generate = {a: ValueError("Requested tokens (9000) exceed context window of 4096")}
    with pytest.raises(ValueError, match="context window"):
        fb.generate(MSGS)
    assert len(FakeLlama.created) == 1  # otro modelo no arregla una petición demasiado larga


def test_all_failing_raises_and_failed_models_are_retried_later(tmp_path, monkeypatch):
    a = gguf(tmp_path, "a.gguf")
    FakeLlama.fail_load = {a}
    fb = FallbackModel([model(a)])
    with pytest.raises(RuntimeError, match="NO_MODEL_AVAILABLE"):
        fb.generate(MSGS)
    assert fb.health() == "unavailable"
    FakeLlama.fail_load = set()
    with pytest.raises(RuntimeError):
        fb.generate(MSGS)  # dentro del enfriamiento no se reintenta
    monkeypatch.setattr("nexus.core.models.RETRY_AFTER_S", 0)
    assert fb.generate(MSGS) == "respuesta de a.gguf"  # pasado el enfriamiento, vuelve a probarse


def test_get_model_builds_chain_from_env(monkeypatch, tmp_path):
    monkeypatch.setattr("nexus.config._dotenv", lambda: {})
    monkeypatch.delenv("NEXUS_MODEL", raising=False)
    monkeypatch.setenv("NEXUS_GGUF_PATH", f"{tmp_path / 'a.gguf'} ; {tmp_path / 'b.gguf'}")
    m = get_model()
    assert isinstance(m, FallbackModel) and [c.path.name for c in m.candidates] == ["a.gguf", "b.gguf"]
    assert all(c.n_gpu_layers == "auto" for c in m.candidates)


# --- Hardware real (portable: sin GPU NVIDIA devuelve gpu=None y VRAM 0) ---
def test_hardware_info_shape():
    h = hardware.get_hardware_info()
    assert h["ram_total_gb"] > 0 and h["cpu_cores"] >= 1
    assert set(h) >= {"ram_free_gb", "gpu", "vram_total_gb", "vram_free_gb"}
    assert (h["gpu"] is None) == (h["vram_total_gb"] == 0)


def test_reasoning_blocks_are_never_exposed():
    from nexus.core.models import strip_reasoning
    assert strip_reasoning("<think>\nprimero sumo 2 y 2\n</think>\n\n4") == "4"
    assert strip_reasoning("<THINK>a</THINK>Hola <think>b</think>mundo") == "Hola mundo"
    assert strip_reasoning("Respuesta.<think>razonamiento cortado por max_tokens") == "Respuesta."
    assert strip_reasoning("Sin bloques.") == "Sin bloques."


def test_generate_json_uses_grammar_constrained_output(tmp_path):
    class JsonLlama(FakeLlama):
        def create_chat_completion(self, messages, **kw):
            JsonLlama.kw = kw
            return {"choices": [{"message": {"content": '{"steps": []}'}}]}
    m = SizedModel(gguf(tmp_path, "j.gguf"), llama_cls=JsonLlama, hardware=hw(), offload=True, block_count=32)
    fb = FallbackModel([m])
    assert fb.generate_json(MSGS) == '{"steps": []}'
    assert JsonLlama.kw["response_format"] == {"type": "json_object"}
    fb.generate(MSGS)
    assert "response_format" not in JsonLlama.kw  # la conversación normal no se restringe
