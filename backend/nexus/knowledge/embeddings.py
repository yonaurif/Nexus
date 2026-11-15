"""Embedding Service (Doc 03 §8.1), en proceso. Un embedder expone:
    provider, model_name, model_version: str · dimensions: int · embed(texts) -> list[list[float]] (L2)

Selección: NEXUS_EMBED_MODEL_DIR = carpeta sentence-transformers con onnx/model.onnx y
tokenizer.json (pip install -e ".[embeddings]"). Sin configurar -> None (solo full-text).
"""
import threading
from pathlib import Path

from nexus.config import env


class OnnxEmbedder:
    """Modelo sentence-transformers exportado a ONNX, mean pooling + L2 (sin torch)."""
    provider = "onnx"

    # 128 = max_seq_length del modelo (sentence_bert_config.json); más allá no se entrenó (visto en f25).
    def __init__(self, model_dir: str, max_tokens: int = 128, batch: int = 32):
        self.dir = Path(model_dir)
        self.model_name = self.dir.parent.parent.name.removeprefix("models--").replace("--", "/") \
            if self.dir.parent.name == "snapshots" else self.dir.name
        # Snapshot HF + truncado: cambiar cualquiera de los dos da vectores incompatibles -> perfil nuevo.
        self.model_version = f"{self.dir.name[:12]}-t{max_tokens}"
        self.max_tokens, self.batch = max_tokens, batch
        self._session = self._tok = None
        self._dims: int | None = None
        self._lock = threading.Lock()

    def _load(self):
        if self._session is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer
            tok = Tokenizer.from_file(str(self.dir / "tokenizer.json"))
            tok.enable_truncation(max_length=self.max_tokens)
            tok.enable_padding()
            self._tok = tok
            self._session = ort.InferenceSession(str(self.dir / "onnx" / "model.onnx"),
                                                 providers=["CPUExecutionProvider"])
            self._dims = self._session.get_outputs()[0].shape[-1]

    @property
    def dimensions(self) -> int:
        self._load()
        return self._dims

    def embed(self, texts: list[str]) -> list[list[float]]:
        import numpy as np
        out: list[list[float]] = []
        with self._lock:
            self._load()
            names = {i.name for i in self._session.get_inputs()}
            for i in range(0, len(texts), self.batch):
                enc = self._tok.encode_batch(texts[i:i + self.batch])
                ids = np.array([e.ids for e in enc], dtype=np.int64)
                mask = np.array([e.attention_mask for e in enc], dtype=np.int64)
                feed = {"input_ids": ids, "attention_mask": mask}
                if "token_type_ids" in names:
                    feed["token_type_ids"] = np.zeros_like(ids)
                hidden = self._session.run(None, feed)[0]
                m = mask[..., None].astype(hidden.dtype)
                pooled = (hidden * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
                pooled /= np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
                out.extend(pooled.tolist())
        return out


def get_embedder():
    if d := env("NEXUS_EMBED_MODEL_DIR"):
        return OnnxEmbedder(d)
    return None
