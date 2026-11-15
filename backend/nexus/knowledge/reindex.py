"""Reindexado gradual: `python -m nexus.knowledge.reindex` calcula los vectores que faltan
en el perfil del embedder configurado (NEXUS_EMBED_MODEL_DIR)."""
import time

from nexus.db import get_engine
from nexus.knowledge.embeddings import get_embedder
from nexus.knowledge.store import reembed_missing

if __name__ == "__main__":
    emb = get_embedder()
    if emb is None:
        raise SystemExit("NEXUS_EMBED_MODEL_DIR no configurado")
    t0 = time.time()
    n = reembed_missing(get_engine(), emb)
    print(f"{emb.model_name} {emb.model_version}: {n} chunks reindexados en {time.time() - t0:.1f}s")
