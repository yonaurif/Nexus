# NEXUS AI — Plan de implementación y registro de progreso

> **Para agentes:** usar `superpowers:executing-plans` o `superpowers:subagent-driven-development` para ejecutar las tareas pendientes. Cada tarea sigue TDD (test que falla → código mínimo → test en verde). Marcar `[x]` al terminar y anotar en **Registro**.

**Objetivo:** construir NEXUS como orquestador controlado: *interpretar → contexto → planificar → validar → autorizar → ejecutar → verificar → responder* (Doc 02 §21).

**Arquitectura:** backend Python (FastAPI más adelante) con contratos Pydantic `extra=forbid`; Core (Planner/Validator/Executor/Verifier) que **solo** alcanza herramientas a través del Gateway (Tool Registry con hash aprobado); memoria en PostgreSQL + pgvector; frontend React+TS que solo habla con el Backend API.

**Stack actual:** Python 3.11 (venv `backend/.venv` con uv) · pydantic 2.13 · SQLAlchemy 2.1 · Alembic 1.20 · psycopg 3.3 · FastAPI 0.163 · uvicorn 0.54 · httpx 0.28 · pytest 8 · Docker Compose (pgvector/pgvector:pg16) · git → GitHub `yonaurif/Nexus`.

> **Equipo de desarrollo ≠ equipo de producción (D19).** Este PC se usa para desarrollar NEXUS y su IA en Python; NEXUS se ejecutará en **otro equipo**. Nada del diseño se dimensiona con este hardware: modelo, capas en GPU, rutas, Tesseract, raíces de carpetas y límites se configuran por `.env` en cada equipo. Los números medidos aquí sirven solo como referencia de desarrollo.

**Equipo de desarrollo (medido 2026-11-15):** NVIDIA RTX 3050 **8 GB VRAM** · AMD Ryzen 5 5600G 6C/12T · **23,4 GB RAM visibles** (los docs decían 32 GB: revisar). CUDA 13.3 + VS 2022 Build Tools. `llama-cpp-python` 0.3.37 **compilado con CUDA** en el venv (`sm_86`, 66 min), `gpu_offload True`. Modelos GGUF en `C:\Worker Primitivo\models` (Qwen2.5-7B, Qwen3-4B, Hermes-3-8B, Yi-1.5-9B, gemma-2-9b, todos Q4_K_M).

**Arranque local:**
```bash
docker compose up -d db          # .env en la raíz: NEXUS_DB_PASSWORD, NEXUS_API_TOKEN (no se suben)
cd backend && .venv/Scripts/alembic.exe upgrade head
.venv/Scripts/python.exe -m pytest -q                              # 181 passed (usa la DB nexus_test, nunca la de desarrollo)
.venv/Scripts/uvicorn.exe nexus.api.app:app --host 127.0.0.1 --port 8000
# Modelo (en .env o entorno; sin servicios externos):
#   NEXUS_GGUF_PATH=a.gguf;b.gguf   (cadena con respaldo, en orden de preferencia; NEXUS_GGUF_GPU_LAYERS=auto|N; NEXUS_GGUF_CTX)
#   NEXUS_EMBED_MODEL_DIR=<snapshot HF de paraphrase-multilingual-MiniLM-L12-v2>  (activo; ONNX, pip install -e ".[embeddings]")
#   OCR: Tesseract en C:\Program Files\Tesseract-OCR (auto) + backend/tessdata (spa/eng/osd, copiado de Primitivo, no se sube)
#   GitHub (opcional): NEXUS_GITHUB_TOKEN=<fine-grained, solo lectura>; sin token: repos públicos, 60 peticiones/h
#   carpetas: NEXUS_FOLDER_ROOTS=C:/ruta1;C:/ruta2  (raíces autorizadas; sin esto no se puede registrar ninguna)
#   reindexar vectores tras cambiar de embedder: .venv/Scripts/python.exe -m nexus.knowledge.reindex
#   reinstalar con CUDA (en ESTE equipo; en otro, su arquitectura o sin -DCMAKE_CUDA_ARCHITECTURES): CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86" CMAKE_GENERATOR="Visual Studio 17 2022" uv pip install -e ".[gguf]"
#   NEXUS_MODEL=paquete.modulo:Clase    (tu propia IA en Python; tiene prioridad)
```

---

## 1. Documentación leída (fuente de verdad)

| Doc | Archivo | Qué define | Fases |
|---|---|---|---|
| Base | `deep-research-report.md` | Visión global, memoria, reglas, agentes, Learning Center | MVP 1–8 |
| 02 | `02_..._Intelligence_Core_v1_0.md` | Core: clasificador, planner, estados, verifier, límites | C0–C6 |
| 03 | `03_..._Memoria_y_Conocimiento_v1_0.md` | Memoria episódica/semántica/procedimental, RAG, olvido | M0–M5 |
| 04 | `NEXUS_AI_Documento_04_..._v1_0.md` | Interfaz dinámica, UI declarativa, API backend, eventos | Fase 1–5 |
| 05 | `05_..._API_MCP_Gateway_v1_0.md` | Gateway, Tool Registry, MCP host, aprobaciones, errores | G0–G6 |
| TL | `NEXUS_Text_Learning_Research_v1_0.md` | Clasificador de intención TF-IDF+LR, datasets, evaluación | T0–T5 |

Dependencias (README): **02 → 03 + 05**; **03 → Core/agentes**; **05 → frontera de herramientas**; **04 → solo Backend API**.

## 2. Mapa de conexiones (cómo está cableado)

```text
            [Frontend React]  (pendiente: Fase 1 de Doc 04)
                  │ HTTPS + Bearer NEXUS_API_TOKEN / SSE
                  v
  nexus/api/app.py  create_app(engine, model, token, adapters)        ✅ HECHO (C1, C2)
     al arrancar: internal_tools.seed() registra y aprueba system.time.now
     POST /api/v1/chat/messages  → 202 {task_id, conversation_id, correlation_id}
     GET  /api/v1/tasks/{id}      → TaskView + AssistantResponse
     GET  /api/v1/tasks/{id}/events → SSE (id = execution_events.id, soporta Last-Event-ID)
     GET  /api/v1/system/health   → database + model (estados reales)
                  │ BackgroundTasks
                  v
  nexus/core/pipeline.py  run()                                       ✅ HECHO (C1, C2)
     classifier.classify → _context (últimos 10 mensajes + SYSTEM_PROMPT)
     ┌─> planning ──> planner.propose(model, tools=list_enabled())   (solo task_request)
     │      └─ fallo/JSON inválido/plan rechazado → synthesis_plan + PLAN_REJECTED
     │   plan_validating → validate_plan (techo global, riesgo read) → planner.save_plan
     │   running → executor.execute(engine, adapters, plan)
     │      └─ resolve() otra vez · timeout · tamaño · output_schema · evidencia → tool_executions
     │   verifying → verifier.verify → completed | partial | failed (+ retriable)
     └── replan ×1 si failed y retriable (el Planner recibe los códigos de error)
     → models.generate(contexto + resultados etiquetados "DATOS NO CONFIABLES") → messages (+ sources)
                  │                                  │
                  │                   nexus/core/models.py  StubModel | LlamaCppModel (GGUF) | tu clase ✅
                  v
  nexus/core/state.py  <── estado de tarea ── pipeline (orquestador)  ✅
        ^ transition()
        │
  nexus/core/task_store.py  create_task / set_status / get_status    ✅ HECHO (M0)
        │ UPDATE tasks + INSERT execution_events (misma transacción)
        v
  PostgreSQL: tasks, execution_events (append-only por trigger)    ✅ HECHO (M0)
                                                     │ Plan (contracts.Plan)
                                                     v
  nexus/core/plan_validator.py  ── validate_plan(plan, registry) ──┐    ✅ HECHO
                                                                   │ registry.resolve(tool_id)
                                                                   v
  nexus/gateway/registry.py                                          ✅ HECHO
     ToolRegistry (memoria, tests unitarios) ─┐ misma interfaz,
     SqlToolRegistry (tabla `tools`)  ────────┴─ misma regla _checked()
            │ ToolManifest.definition_hash (sha256, recalculado al leer)
            v
  nexus/contracts.py  (Plan, PlanStep, ToolManifest, ToolResult, Evidence) ✅ HECHO

  nexus/db.py  get_engine() ← NEXUS_DATABASE_URL | NEXUS_DB_PASSWORD | ../.env   ✅ HECHO
            │
  migrations/versions/0001_m0_base.py (Alembic, reversible)          ✅ HECHO
            v
  docker-compose.yml → PostgreSQL 16 + pgvector 127.0.0.1:5432
     tablas: memory_sources, tasks, plans, plan_steps, tools,
             tool_executions, execution_events, audit_events,
             conversations, messages (0002),
             memory_episodes, documents, document_chunks (tsv), embedding_profiles, chunk_embeddings (0003)

  nexus/knowledge/  sanitize.redact → chunking.chunk_text → store.ingest_document / store.search   ✅ (M2)
     embeddings.OnnxEmbedder (MiniLM multilingüe, 384 d, CPU, sin torch)
  nexus/memory/episodes.py  record / search (append-only)                                      ✅ (M1)
     extract.extract (PDF/DOCX/XLSX/CSV/HTML/JSON/imagen + OCR Tesseract; portado de Primitivo-f25)   ✅
     sources.register_folder / sync_folder / due_sources (carpetas incrementales; portado de f25)  ✅
       hilo nexus-sync (cada 60 s) → due_sources → sync_folder(trigger=schedule)
       tablas: source_files (manifiesto), sync_runs (pasadas) · documents.uri_ref (0004)
     API: POST/GET /api/v1/knowledge/sources · POST …/sources/{id}/sync[?force] · GET …/sources/{id}/runs
          POST /api/v1/knowledge/documents · POST /api/v1/knowledge/files (multipart) · GET /api/v1/knowledge/search · GET /api/v1/memory/episodes
```

**Conexiones reales en código hoy:**
1. `plan_validator.validate_plan` → llama a `ToolRegistry.resolve` por cada paso `tool_call`. Un `GatewayError` se convierte en `PlanRejected` con el mismo código (`TOOL_NOT_ALLOWED`, `TOOL_DEFINITION_CHANGED`). → Doc 02 aceptación #2, Doc 05 aceptación #4.
2. `ToolRegistry` guarda el `definition_hash` en el momento de `approve()`. Si se re-registra una definición distinta, `resolve` falla hasta nueva aprobación. → Doc 05 §8.5.
3. Todos los contratos heredan de `Strict` (`extra="forbid"`). → Doc 02 §14.
4. `state.transition` es la única forma de cambiar estado; los terminales no tienen salida. → Doc 02 §7.1.
5. `task_store.set_status` bloquea la fila (`FOR UPDATE`), llama a `transition()` **antes** de escribir y registra `task.status.changed` con el `correlation_id` de la tarea. Una transición inválida no deja rastro. → Doc 02 §15.
6. `execution_events` y `audit_events` rechazan UPDATE/DELETE con un trigger en la DB (no solo en código). → Doc 03 §3.1.
7. `validate_plan` funciona igual con `SqlToolRegistry`; el hash se recalcula desde el manifest guardado, no se confía en la columna. → Doc 05 §8.5.
8. `tool_executions` guarda solo `arguments_hash`, nunca argumentos en claro; `memory_sources.auth_ref` es una referencia, nunca el secreto. → Doc 05 §18, Doc 03 §7.1.
9. La API crea conversación + mensaje de usuario + tarea en **una** transacción y lanza `pipeline.run` en segundo plano; cada transición del pipeline se confirma por separado, así el SSE las ve en tiempo real. → Doc 04 §3.3, §9.2.
10. El clasificador solo enruta: `unknown` → `needs_input` sin llamar al modelo; clases sin capacidad todavía → respuesta + `partial` con `CAPABILITY_UNAVAILABLE`. → Doc 02 §4, §6.3.
11. Fallo de modelo → tarea `failed`, aviso `MODEL_UNAVAILABLE`, detalle solo en logs; `StubModel` → `partial` con `MODEL_NOT_CONFIGURED`. Nunca éxito aparente. → Doc 02 aceptación #8.
12. Token comparado con `secrets.compare_digest`; conversaciones y tareas filtradas por `owner_id` (404 si no son tuyas). → Doc 04 §11.
13. El Planner **solo** propone `summary_for_user` + `steps`; `plan_id`, versión y límites los pone el sistema. Si el modelo intenta fijar `limits`, el plan se rechaza (`PLAN_UNPARSEABLE`). → Doc 02 §6.1, §11.
14. El Planner solo ve `SqlToolRegistry.list_enabled()` (aprobadas con hash intacto); el Executor vuelve a llamar a `resolve()` justo antes de invocar. → Doc 02 aceptación #4–5.
15. Hasta C5 solo se ejecutan herramientas `risk_level=read` sin `requires_approval`; lo demás → `APPROVAL_REQUIRED`. → Doc 05 §6.2.
16. Los resultados de herramientas entran al modelo como bloque `system` etiquetado "DATOS NO CONFIABLES", truncado a 4000 caracteres, antes del último mensaje del usuario. → Doc 02 §16.
17. La evidencia de las herramientas se devuelve al cliente en `AssistantResponse.sources`. → Doc 02 aceptación #12.
18. Ingesta: `redact()` **antes** de hashear/trocear/indexar; el texto original con secretos nunca se guarda; documento marcado `sensitivity=redacted`. Dedupe por `(owner_id, content_hash)`. → Doc 03 §5, §11.
19. Búsqueda: filtro por `owner_id` y estado **antes** del ranking; full-text (≥2 lexemas de la consulta) + vectorial (mismo perfil, distancia < 0,6) → RRF → máx. 2 chunks por documento. → Doc 03 §8.3.
20. `knowledge_query` en el pipeline: se quita la frase de enrutado ("según mis documentos") antes de buscar; con resultados → fragmentos numerados como DATOS NO CONFIABLES + `sources` `doc:<id>#<chunk>`; **sin resultados → respuesta fija sin llamar al modelo**, estado `needs_input`. → Doc 03 §8.4, Doc 02 §2.9.
21. Cada turno de chat deja un episodio `chat.turn` (resumen sanitizado, `task_id`, `correlation_id`). → Doc 03 §3.1.

## 3. Skills / herramientas usadas para iniciar

| Skill / herramienta | Para qué |
|---|---|
| `superpowers:using-superpowers` | Protocolo de skills de la sesión |
| `superpowers:writing-plans` | Estructura de este plan (tareas, rutas exactas, TDD) |
| `superpowers:test-driven-development` (método) | Tests escritos primero; se vio el fallo y luego el verde |
| `ponytail` (modo full) | Código mínimo; simplificaciones marcadas con `# ponytail:` |
| `codebase-memory-mcp` | Indexado del repo para explorar código en sesiones futuras |
| Docker / git / uv / pytest | Toolchain verificada en la máquina |

No aplicadas aún (cuándo entran): `frontend-design` + `design:*` → Fase 1 frontend; `security-review` / `cybersecurity-skills:auditing-mcp-servers-for-tool-poisoning` → G2; `claude-api` → si se decide usar un LLM externo en el Model Router; `code-review` → antes de cada merge.

## 4. Fases y estado

### ✅ C0 + G0 — Contratos, estados y registro (HECHO)

- [x] `backend/pyproject.toml` (pytest con `pythonpath=["."]`)
- [x] `backend/nexus/contracts.py` — Plan, PlanStep, PlanLimits, ToolManifest (+hash), Evidence, ToolResult
- [x] `backend/nexus/core/state.py` — `TaskStatus`, `ALLOWED`, `transition()`
- [x] `backend/nexus/core/plan_validator.py` — límites, duplicados, deps, ciclos (`graphlib`), tool permitida, `required` del input
- [x] `backend/nexus/gateway/registry.py` — `ToolRegistry` en memoria, `GatewayError`
- [x] `backend/tests/test_c0_g0.py` — 14 tests en verde
- [x] `docker-compose.yml` — Postgres+pgvector, password por `.env`, puerto solo localhost
- [x] `.gitignore`, `pyrightconfig.json`, `git init`

Verificar: `cd backend && python -m pytest -q` → `14 passed`.

### ✅ M0 — Persistencia (HECHO) (Doc 03 §17, Doc 02 §13)

- [x] `.env` local con `NEXUS_DB_PASSWORD` aleatoria (ignorado por git); `docker compose up -d db`
- [x] `sqlalchemy`, `alembic`, `psycopg[binary]` en `pyproject.toml`; venv con uv
- [x] `backend/nexus/db.py` — URL desde entorno o `.env`
- [x] `backend/migrations/versions/0001_m0_base.py` — `vector`, 8 tablas, índices, triggers append-only; `downgrade` probado
- [x] `backend/nexus/core/task_store.py` — tareas persistidas + eventos
- [x] `SqlToolRegistry` en `backend/nexus/gateway/registry.py` (tabla `tools`)
- [x] `backend/tests/test_m0_db.py` — 7 tests de integración (extensión, tablas, ciclo de vida, transición inválida, append-only, registry, validator+registry)

Pendiente de M0 que se difiere: `plans`/`plan_steps`/`tool_executions` tienen tabla pero aún no repositorio (entran con C2, cuando haya Executor que los escriba).

### ✅ C1 — Core conversacional (HECHO) (Doc 02 §18, Doc 04 Fase 1)

- [x] `backend/nexus/config.py` — `env()` con respaldo en `.env`
- [x] `backend/migrations/versions/0002_conversations.py` — `conversations`, `messages`
- [x] Contratos `ChatRequest`, `ChatAccepted`, `AssistantResponse`, `TaskView`, `CoreEvent`, `RequestClass`
- [x] `backend/nexus/core/classifier.py` — reglas por palabras clave con abstención (se sustituye en T1)
- [x] `backend/nexus/core/models.py` — Model Router en proceso: `StubModel` (por defecto), `LlamaCppModel` (GGUF con `NEXUS_GGUF_PATH`, carga perezosa, lock por hilo) y modelo propio (`NEXUS_MODEL=modulo:Clase`). **Sin Ollama** por decisión del propietario.
- [x] `backend/tests/test_models.py` — 3 tests (GGUF con Llama simulado, archivo ausente, prioridad de selección)
- [x] `backend/nexus/core/pipeline.py` — classify → context → plan → validate → run → verify → responder
- [x] `backend/nexus/api/app.py` — 4 endpoints, auth Bearer, SSE con reconexión
- [x] `backend/tests/test_c1_api.py` — 20 tests; prueba manual con uvicorn + curl (health, 401, chat, 9 eventos SSE, tarea)

Diferido: tabla `model_invocations` (Doc 02 §13) → con el primer modelo real; presupuesto de contexto por tokens → cuando haya tokenizador del modelo elegido.

**Modelo usado en desarrollo (D6, no es una decisión de producción):** Qwen2.5-7B-Instruct Q4_K_M en GPU: carga 7 s, respuesta corta ~1,6 s. Probado por la API: chat, petición no disponible (GitHub → `partial`) y "¿qué hora es?" → Planner propone `system.time.now` → `completed` con fuente `internal:system_clock`. El prompt de sistema lista las herramientas reales del registro para que el modelo no prometa capacidades inexistentes.

### ✅ C2 — Planner/Executor/Verifier (HECHO) (Doc 02 §6–8, §11)

- [x] `backend/nexus/core/planner.py` — `propose()` (JSON del modelo, admite ```json```), `synthesis_plan()`, `save_plan()` → `plans`/`plan_steps`
- [x] `backend/nexus/core/executor.py` — orden topológico, re-`resolve`, timeout por herramienta y presupuesto total, validación de salida, `DEPENDENCY_FAILED`, `BUDGET_EXCEEDED`, registro en `tool_executions`
- [x] `backend/nexus/core/verifier.py` — `Verdict(completed|partial|failed, warnings, retriable)`; sin evidencia ≠ éxito
- [x] `backend/nexus/gateway/internal_tools.py` — `system.time.now` (determinista, sin red) + `seed()`
- [x] `plan_validator.py` — techo global (`max_steps` 8, `max_duration_s` 60) y bloqueo de riesgo ≠ `read`
- [x] `SqlToolRegistry.list_enabled()`
- [x] Pipeline con replanificación limitada (1) y fuentes en la respuesta
- [x] `backend/tests/test_c2.py` — 15 tests: verifier, techo, riesgo, planner, executor (7 resultados normalizados), registro sin argumentos, e2e con fuentes, herramienta desconocida, replan tras fallo transitorio

Diferido: paralelismo de pasos (C6); aislar adaptadores en proceso/contenedor (C6); `success_criteria` estructurados; cancelación cooperativa (C5).

### ✅ G1 — REST readonly + conector GitHub (HECHO) (Doc 05 §6–7, §10–11, §14)

- [x] `backend/nexus/gateway/http_safe.py` (del Worker `updater.py` H-12): host canónico, todas las IP públicas, **conexión a la IP validada con Host+SNI (anti DNS rebinding)**, redirecciones revalidadas (máx. 3), solo https sin credenciales en URL, `allowed_hosts` por conector, límite de bytes **descomprimidos**, errores Doc 05 §14 (AUTH_REQUIRED, SCOPE_MISSING, RESOURCE_NOT_FOUND, RATE_LIMITED, TIMEOUT, CONNECTOR_UNAVAILABLE, RESPONSE_TOO_LARGE, POLICY_DENIED, TOO_MANY_REDIRECTS).
- [x] `backend/nexus/gateway/rest.py`: `RestTool` (solo GET, ruta con plantilla, consulta permitida, campos de salida, listas acotadas) + `RestConnector` (host fijo, argumentos de ruta sin `/` ni `..`, token desde entorno nunca en datos/evidencia, evidencia `conector:GET ruta`).
- [x] `backend/nexus/gateway/connectors.py`: **GitHub readonly** (`github.repository.get`, `github.user.repos`), registrado en **`review`** al arrancar.
- [x] API: `GET /api/v1/connectors`, `POST /api/v1/connectors/tools/{id}/approve`, `POST …/disable` (con `audit_events`); deshabilitar no requiere desplegar y re-registrar no reactiva.
- [x] Executor conserva los códigos del adaptador (`RATE_LIMITED` reintentable); `agent_request` pasa por el Planner.
- [x] **Sin datos no hay respuesta inventada:** si todas las herramientas fallan, respuesta fija con los errores y sin LLM (medido: Qwen inventó lenguaje/rama y `{"repos": []}` con GitHub fallando).
- [x] Tests: `test_http_safe.py` (45: 24 hosts maliciosos del Worker, rebinding, redirecciones, gzip, bomba de descompresión) + `test_rest.py` (14).
- [x] Prueba real contra api.github.com sin token: en `review` → `PLAN_REJECTED`; aprobado → "Python, rama main" con fuente `github_readonly:GET /repos/yonaurif/Nexus`; lista real de repos (Nexus, GalaTrain).

Fallo encontrado solo con el servicio real: `iter_bytes()` ya descomprime y la respuesta reconstruida conservaba `Content-Encoding: gzip` → `zlib.error`. Corregido con test.

Diferido: `web.search`/`web.fetch` aislados (Primitivo `websearch`), webhooks (G4), escritura con aprobación contextual (G5, requiere C5), secret store cifrado (G3, `core/crypto.py` de Primitivo).

### ⬜ G2 — MCP readonly (Doc 05 §8)

- [ ] Validación JSON Schema completa (`jsonschema`) de input y output (sustituye el chequeo de `required`)
- [ ] MCP Host/Client (SDK oficial, versión fijada tras prueba en Windows/Docker); descubrimiento → `review` → aprobación

### ✅ M1/M2 — Episodios, documentos y RAG híbrido (HECHO) (Doc 03 §17)

- [x] `backend/migrations/versions/0003_memory_knowledge.py` — 5 tablas, FTS `spanish` generado, vectores sin dimensión fija por perfil, episodios append-only
- [x] `backend/nexus/knowledge/sanitize.py` — claves privadas, tokens GitHub/AWS/`sk-`, Bearer, `password|token|api_key = …`
- [x] `backend/nexus/knowledge/chunking.py` — títulos Markdown, párrafos, corte duro con offsets exactos
- [x] `backend/nexus/knowledge/embeddings.py` — `OnnxEmbedder` (onnxruntime + tokenizers, mean pooling + L2)
- [x] `backend/nexus/knowledge/store.py` — `ingest_document`, `search` (híbrida RRF), `ensure_profile`
- [x] `backend/nexus/memory/episodes.py` — `record`, `search` por tipo/rango temporal
- [x] Pipeline: RAG para `knowledge_query`, abstención determinista, episodios; API: 3 endpoints nuevos; health informa del embedder
- [x] `backend/tests/test_m1m2.py` — 18 tests (chunking, secretos, dedupe, perfil, citas, aislamiento por propietario, FTS solo, diversidad, episodios, API, RAG e2e, abstención, regresión "según mis documentos", embedder real)
- [x] Prueba real: 7 documentos de NEXUS → 303 chunks en 26,6 s; Qwen responde con citas; "receta de la paella" → abstención

Medido para calibrar: distancia coseno MiniLM — relevantes 0,32–0,60, irrelevantes ≥ 0,616. Umbral 0,6 (`NEXUS_RAG_MAX_DISTANCE`) con poco margen: recalibrar con un set de evaluación (Recall@k/MRR).

**Ampliación M2 — archivos y OCR (portado de Primitivo-f25, prioridad 1 de §4b): ✅ HECHO**
- [x] `backend/nexus/knowledge/extract.py` — PDF (PyMuPDF; página escaneada → OCR a 200 ppp en gris; imágenes incrustadas → OCR), DOCX (+ imágenes incrustadas), XLSX, CSV, HTML, JSON, TXT/MD, imágenes. OCR: salta < 10.000 px, caché de imágenes repetidas, reduce > 2500 px.
- [x] Mejoras sobre Primitivo: **errores en `Extraction.error`** (UNSUPPORTED_TYPE/EXTRACTION_FAILED/NO_TEXT), nunca como texto indexable; HTML sin `<script>/<style>`.
- [x] `POST /api/v1/knowledge/files`: extensión permitida (415), máx. 25 MB (413), error de extracción (422), archivo temporal propio (nunca la ruta del cliente), `uri_ref=upload://<nombre>`.
- [x] `max_seq_length` del embedder a 128 (detectado en f25); `model_version` incluye el truncado → perfil nuevo; `store.reembed_missing` + `python -m nexus.knowledge.reindex` (303 chunks en 11,4 s).
- [x] `backend/tests/test_extract.py` — 16 tests (13 portados/adaptados de Primitivo + OCR real con Tesseract sobre PDF escaneado + subida); `test_reembed_missing…` en test_m1m2.
- [x] Prueba real: `.docx` de NEXUS (20 chunks, 2,2 s) y acta escaneada (OCR, 1,1 s); Qwen responde "4.750 euros" y "NAS de la oficina" desde la imagen.

**Carpetas sincronizadas (portado de Primitivo-f25 `kb_service`/`kb_scheduler`, prioridad 2 de §4b): ✅ HECHO**
- [x] `backend/migrations/versions/0004_folder_sources.py` — `source_files`, `sync_runs`, `documents.uri_ref`; dedupe solo entre documentos activos (índice único parcial); downgrade probado ida y vuelta.
- [x] `backend/nexus/knowledge/sources.py` — de Primitivo: señal (mtime,size) ±1 s, manifiesto, contadores por pasada, un fallo no corta, retirada de borrados. Añadido para NEXUS:
  - raíces autorizadas `NEXUS_FOLDER_ROOTS` (también se revalida en cada pasada), sin seguir enlaces simbólicos, sin `.git/node_modules/.venv/...` ni temporales `~$`;
  - **archivos con nombre de secreto** (`credenciales*`, `*password*`, `.env`, `id_rsa`, `.pem`, `.kdbx`…) → `skipped: SENSITIVE_FILENAME`, nunca se leen (hallado en `Primitivo proyecto/Docs`, que tiene `credenciales_*.txt`);
  - modificado → versión anterior `superseded`; borrado → `deleted`; en ambos casos chunks y vectores borrados (Doc 03 §12);
  - una carpeta = una fuente (409 si se registra dos veces); una pasada a la vez (advisory lock → `busy`);
  - `force=true` regenera chunks de documentos sin cambios (`ingest_document(refresh=True)`).
- [x] Chunking: cada fragmento lleva la **ruta de títulos** ("Primitivo Worker › Estructura") y se descartan fragmentos que son solo un título. Medido: sin ruta, la sección con el puerto no se recuperaba.
- [x] `store.filter_by_names`: si la pregunta nombra entidades, solo cuentan fragmentos que las mencionan. Medido: "¿qué BD usa Primitivo Suite?" respondía "PostgreSQL" con fragmentos de NEXUS.
- [x] Planificador: hilo `nexus-sync` (solo en el servidor real), `interval_minutes` 5–10080 o manual.
- [x] Tests: `test_sync.py` (15) + 4 nuevos en `test_m1m2.py`.
- [x] Prueba real: carpeta con README/CHANGELOG de Primitivo + archivo de credenciales señuelo → 2 indexados, 1 omitido por nombre; modificación (puerto 8600→9700) y borrado detectados; Qwen responde "9700" y se abstiene sobre Primitivo Suite.

Diferido: grafo semántico (M3), procedimientos (M4), consolidación/olvido/expiración (M5), detección por hash (hoy mtime+size), rutas de red SMB, API para dar de baja una fuente, índice HNSW por perfil (>100k chunks), ingesta en cola, PII con NER, chunking por tokens, `.doc`/`.pptx`.

### ✅ Router de modelos por hardware (portado de Primitivo Worker + `model_fallback`, prioridad 4 de §4b)

- [x] `backend/nexus/core/hardware.py` — RAM total/libre, núcleos, % CPU, GPU y VRAM total/libre (psutil + `nvidia-smi`; sin NVIDIA → `gpu=None`, VRAM 0, solo CPU).
- [x] `models.auto_gpu_layers` (casos de test del Worker) + `LlamaCppModel(n_gpu_layers="auto")`: capas según VRAM libre **al cargar**, nº de capas desde metadatos GGUF; `fits()` comprueba RAM libre + VRAM útil.
- [x] `models.FallbackModel`: cadena `NEXUS_GGUF_PATH=a;b;…`; descarta sin cargar los que no caben (`unfit`); fallo de carga (`LOAD_FAILED`) o de ejecución (`RUNTIME_ERROR:…`) → libera y pasa al siguiente; errores de petición (`ValueError`, p. ej. contexto excedido) no cambian de modelo; reintento tras 300 s.
- [x] `strip_reasoning`: se eliminan bloques `<think>…</think>` (Qwen3/R1) — Doc 02 §1.2/§15.
- [x] `/system/health`: `hardware` real + `model.active` + `model.candidates[{name,status,reason,gpu_layers}]`.
- [x] `backend/tests/test_router.py` — 12 tests (tamaños **simulados**: un archivo "disperso" en Windows escribió 108 GB reales en el Temp de pytest; ya borrados).
- [x] Prueba real en el equipo de desarrollo: con 5,15 GB de VRAM libre eligió **26 capas** de Qwen2.5-7B (reparto GPU+CPU) en vez de todas; GGUF corrupto → `LOAD_FAILED` → Qwen3-4B con todas las capas en 4,5 s.

Diferido: vuelta automática al modelo principal (Primitivo la tiene), elección por tipo de tarea (Doc 02 §10), catálogo descargable del Worker.

### ⬜ T0/T1 — Text Learning (doc TL §12)

- [ ] Esquema JSONL + taxonomía de intenciones (clases de Doc 02 §4)
- [ ] Baseline TF-IDF + LogisticRegression con abstención → señal para el Intent Classifier del Core

### ⬜ M3–M5, C3–C6, G3–G6, Fases 2–5 de interfaz

Seguir el orden de cada documento; no empezar escritura externa (G5) sin aprobaciones (C5).

## 4a. Despliegue en el equipo de producción (D19)

Qué necesita el equipo destino (todo opcional salvo lo marcado):

| Pieza | Obligatorio | Cómo se configura | Si falta |
|---|---|---|---|
| Python 3.11+ y `backend/` con `pip install -e .` | Sí | — | — |
| PostgreSQL 16 + pgvector (`docker compose up -d db` o servidor propio) | Sí | `NEXUS_DATABASE_URL` o `NEXUS_DB_PASSWORD` | No arranca |
| `NEXUS_API_TOKEN` | Sí | `.env` | No arranca |
| Modelo GGUF + `.[gguf]` (CPU o GPU según el equipo) | No | `NEXUS_GGUF_PATH` (uno o varios con `;`), `NEXUS_GGUF_CTX`, `NEXUS_GGUF_GPU_LAYERS=auto` | `StubModel` (tareas `partial`); si un modelo no cabe o no carga, pasa al siguiente |
| IA propia en Python | No | `NEXUS_MODEL=modulo:Clase` | — |
| Embeddings ONNX + `.[embeddings]` | No | `NEXUS_EMBED_MODEL_DIR` | RAG solo full-text |
| Tesseract + `tessdata` (spa/eng) + `.[documents]` | No | `NEXUS_TESSERACT_CMD`, `NEXUS_TESSDATA_DIR`, `NEXUS_OCR_LANGUAGES` | Sin OCR (PDF con texto sí) |
| Carpetas a sincronizar | No | `NEXUS_FOLDER_ROOTS` | No se pueden registrar carpetas |
| Salida a internet (HTTPS) para conectores | No | `NEXUS_GITHUB_TOKEN` (opcional) + aprobar herramientas en `/api/v1/connectors` | Conectores externos no disponibles |

Ya adaptativo (prioridad 4 de §4b): NEXUS mide RAM/VRAM del equipo al cargar, decide las capas en GPU, descarta modelos que no caben y cae al siguiente de la cadena; `/system/health` muestra hardware y estado de cada candidato. Pendiente para producción: elegir la cadena de modelos para el equipo destino, empaquetado/servicio de arranque y backups.

## 4b. Reutilización desde Primitivo y Primitivo Worker

Fuente: `C:\Users\YonaPc\Documents\GitHub\Primitivo proyecto`. Versiones revisadas: `Primitivo` (rama `main`, 16-10), `Primitivo-f25` (rama `f25-kb-equipo`, 18-10, la más reciente: KB desde el equipo + optimizaciones de OCR/vectores) y `Primitivo_Worker` (`main`, 10-10). `Primitivo-base` es una copia anterior y se ignora.

**Regla de adaptación:** se copia la lógica, no el acoplamiento. Fuera: MariaDB/SQLAlchemy async de Primitivo, ChromaDB (NEXUS usa pgvector, D2), Ollama/proveedores cloud (D13), licencias. Cada módulo portado entra con sus tests de Primitivo adaptados y con TDD.

| Prioridad | Necesidad NEXUS (doc · fase) | Origen en Primitivo | Qué se adapta | Tests a portar |
|---|---|---|---|---|
| 1 ✅ | Ingesta de PDF/DOCX/XLSX/CSV/HTML/JSON/imágenes con **OCR** (Doc 03 §4–5 · M2) — **portado** | `Primitivo-f25/backend/app/gala/document_extractor.py` (PyMuPDF + Tesseract, OCR de páginas escaneadas y de imágenes incrustadas en PDF/DOCX; f25 lo hace en gris y 1 hilo) | Config por `env()` en vez de `settings`; **errores separados del texto** (hoy el mensaje de error se indexaría como contenido); HTML sin `<script>/<style>`; salida → `ingest_document()` (redacción de secretos ya incluida). Tesseract ya instalado en `C:\Program Files\Tesseract-OCR`; `tessdata` (spa/eng/osd) en `Primitivo/backend/tessdata`. Endpoint `POST /api/v1/knowledge/files` (multipart, límite de tamaño, tipos permitidos) | `test_document_extractor.py` |
| 2 ✅ | Sincronización incremental de carpetas como fuente (Doc 03 §5 Source Registry, `sync_policy` · M5) — **portado** | `gala/kb_service.py` (recorrido + manifiesto por `mtime,size`, reindexado incremental, borrado de huérfanos) + `gala/kb_scheduler.py` (APScheduler cron) | Manifiesto en `source_versions`/`documents` de NEXUS; rutas solo dentro de raíces autorizadas (Doc 02 §16); sin la parte SMB/UNC hasta que haga falta | `test_kb_device_sync.py` (f25) |
| 3 ✅ | Adaptador REST seguro: allowlist, **anti-SSRF**, redirecciones, límite de tamaño (Doc 05 §7 · G1) — **portado** (del Worker `updater.py`, más fuerte que `websearch`) | `websearch/service.py` (`_is_safe_url`, `_is_unsafe_ip`, `_fetch_page_html`: valida IP resuelta y cada redirección) | Módulo `nexus/gateway/http_safe.py` usado por todos los adaptadores REST; además herramienta `web.search` (DuckDuckGo/Tavily) **aislada sin acceso a DB**, como en Primitivo, resultados como datos no confiables | `test_websearch.py`, `Worker/tests/test_ssrf.py` |
| 4 ✅ | Router de modelos con conciencia de hardware (Doc 02 §10, Doc 04 §12 métricas reales) — **portado** | Worker `hardware.py` (psutil + nvidia-smi), `engine_llamacpp.py::auto_gpu_layers/resolve_gpu_layers` (capas en GPU según VRAM libre, margen 0,92), `model_catalog.py` (catálogo + compatibilidad RAM/VRAM), Primitivo `gala/model_fallback.py` (cadena de modelos de respaldo) | `NEXUS_GGUF_GPU_LAYERS=auto`; `/system/health` con CPU/RAM/GPU/VRAM reales; fallback entre tus GGUF de `C:\Worker Primitivo\models` si uno falla al cargar | `test_hardware.py`, `test_engine_llamacpp.py`, `test_model_catalog.py`, `test_gala_model_fallback.py` |
| 5 | Cola con contrapresión para el modelo (Doc 02 §11 límites) | Worker `queue_control.py::RequestQueue` (FIFO, concurrencia 1, 503 si se llena) | Sustituye el `threading.Lock` de `LlamaCppModel`; estado de cola en health | `test_queue_control.py`, `test_request_queue.py` |
| 6 | Métricas por fase y modelo (Doc 02 §13 `model_invocations`, §15) | `core/perf_log.py` (JSONL), timings de `gala/llm.py` | En NEXUS a tabla `model_invocations` (latencia, tokens, modelo) en vez de JSONL | `test_performance.py` |
| 7 | Credential Broker / secretos cifrados (Doc 05 §4.1, G3; Doc 03 §11 payloads cifrados) | `core/crypto.py` (AES-GCM: `encrypt_secret`, claves por fichero) | `credential_ref` → secreto cifrado con clave maestra fuera de la DB | `test_crypto.py` |
| 8 | Generación de documentos Word/Excel/PDF desde texto (herramienta del Core) | `gala/document_generator.py` (plantillas deterministas, sin ejecutar código) | Herramienta interna `documents.generate` (`write_reversible`, archivo en almacenamiento de NEXUS); entra con C5 (aprobaciones) | `test_document_generator.py` |
| 9 | Aprobación de acciones: proponer → tarjeta → confirmar → re-validar permiso (Doc 05 §11 · C5) | `gala/actions.py` (patrón `proposed_action` + `/actions/execute` con re-chequeo) | Solo el **patrón**; se implementa sobre `approvals` + `arguments_hash` del Doc 05 | `test_gala_actions.py` (como referencia) |
| 10 | Auth real con perfiles (Doc 04 §11 · Fase 4) | `packages/primitivo-core` (JWT, TOTP) + `core/security.py` | Sustituye el token único `NEXUS_API_TOKEN` (D11) | tests de `primitivo-core` |
| 11 | Ejecución de código en sandbox (Doc 02 §8 Trusted Services · C6) | Worker `sandbox.py` (audit hook: sin procesos/ctypes/red; FS restringido) + `environments.py` | **Bloqueado por decisión:** el Doc 02 §1.2 prohíbe ejecutar código generado por el modelo. Solo sería válido para procedimientos aprobados (M4) o con aprobación humana explícita. Requiere decisión del propietario | `test_sandbox.py`, `test_sandbox_escapes.py` |
| 12 | Interfaz (Doc 04 · Fase 1) | `client/` Electron 29 + React 19 + Vite (chat, KB, tema Sneat) | Candidato para la UI de NEXUS; es JSX (no TS) y está acoplado a la API de Primitivo: reutilizar componentes de chat/KB, no la app entera | tests de cliente (`tests-unit/`) |

Ideas sueltas de `rag/service.py` para M3 (entidades): `infer_entities`, `infer_doc_type`, `infer_year`, `search_exact`, `count_by_metadata`, `filter_out_code_files` (evita que se cuele código fuente en contenido generado; bug real visto en Primitivo).

Ajuste detectado gracias a f25 y **aplicado**: `max_seq_length` 128 en `OnnxEmbedder` (antes 256), con reindexado a perfil nuevo.

## 5. Decisiones técnicas

| # | Decisión | Estado | Origen |
|---|---|---|---|
| D1 | Orquestador Python propio y pequeño | Adoptada | Doc 02 §20 |
| D2 | PostgreSQL 16 + pgvector como fuente de verdad, sin Neo4j | Adoptada | Doc 03 §2 |
| D3 | Monorepo: `backend/` (Python) ahora, `frontend/` cuando llegue Fase 1 | Adoptada | Doc 04 §14 |
| D4 | Registro de herramientas: `SqlToolRegistry` en producción, `ToolRegistry` en memoria para tests unitarios | Adoptada (M0) | Doc 05 §6 |
| D9 | SQL explícito con `sa.text` (SQLAlchemy Core), sin ORM; migraciones Alembic en SQL plano | Adoptada | ponytail / Doc 03 §7 |
| D10 | Append-only forzado por trigger en Postgres | Adoptada | Doc 03 §3.1 |
| D5 | Validación de input solo `required` hasta G1 | Temporal | ponytail |
| D6 | LLM de desarrollo: Qwen2.5-7B-Instruct Q4_K_M (GGUF). El de producción se elige según el equipo destino | Solo desarrollo; pendiente para producción | Doc 02 §10, Doc 03 §8.1 |
| D14 | Tests en base de datos separada `nexus_test` (creada por `conftest.py`) | Adoptada | evita contaminar la DB real |
| D15 | Embeddings: `paraphrase-multilingual-MiniLM-L12-v2` en ONNX (ya estaba en la caché HF), en proceso y CPU | Adoptada; comparar con bge-m3/e5 cuando haya set de evaluación | Doc 03 §8.1 |
| D21 | Conectores externos: solo vía `http_safe` (IP fijada, allowlist por conector), solo GET hasta C5, en `review` hasta aprobación del propietario; fallo total de herramientas → respuesta en código | Adoptada | Doc 05 §3, §7, §8.1 |
| D20 | Modelos: cadena con respaldo y capas en GPU automáticas según el equipo; el razonamiento `<think>` nunca sale | Adoptada | D19, Doc 02 §10, §15 |
| D17 | Carpetas: solo bajo `NEXUS_FOLDER_ROOTS`; archivos con nombre de secreto nunca se leen; planificador en hilo propio (no APScheduler) | Adoptada | Doc 02 §16, Doc 04 §11 |
| D18 | Fragmentos con ruta de títulos + filtro por entidades nombradas en RAG | Adoptada (heurística hasta M3) | medido con datos reales |
| D16 | Sin evidencia en `knowledge_query` → abstención en código (no se llama al LLM) | Adoptada (medido: el LLM ignora "no inventes") | Doc 02 §2.9 |
| D19 | **El equipo de desarrollo no dimensiona NEXUS.** Todo lo dependiente del equipo (modelo, GPU/capas, rutas, Tesseract, `NEXUS_FOLDER_ROOTS`, límites) va por `.env`; el código detecta lo disponible y degrada sin fallar (sin GPU → CPU, sin embedder → solo full-text, sin Tesseract → sin OCR, sin modelo → Stub) | Adoptada (decisión del propietario) | despliegue en otro equipo |
| D13 | Runtime de modelos **en proceso**: GGUF vía llama-cpp-python o clase Python propia; **no Ollama** ni servidores externos | Adoptada (decisión del propietario) | Doc 02 §10 |
| D7 | SSE para estados de tarea (servidor → cliente), con id de `execution_events` | Adoptada (C1) | Doc 04 §9.2 |
| D11 | Auth inicial: un token Bearer por instancia (`NEXUS_API_TOKEN`), un único propietario | Temporal hasta Fase 4 | Doc 04 §11 |
| D12 | Procesado en `BackgroundTasks` de FastAPI; cola durable (Redis Streams) cuando haya agentes | Temporal | Doc 05 §15 |
| D8 | Secret store, cola (Redis Streams), versión MCP SDK | **Pendiente** | Doc 05 §22 |

## 6. Registro

| Fecha | Qué | Verificación |
|---|---|---|
| 2026-11-15 | Leídos los 7 documentos; creado este plan | — |
| 2026-11-15 | C0+G0: contratos, estados, validador, registry; compose de Postgres | `pytest` 14 passed; `docker compose config` OK |
| 2026-11-15 | Repo conectado a GitHub: `origin` → https://github.com/yonaurif/Nexus (rama `main`) | `git push -u origin main` |
| 2026-11-15 | M0: Postgres+pgvector levantado, migración 0001, task_store, SqlToolRegistry | `pytest` 21 passed contra Postgres real; `alembic downgrade base` + `upgrade head` OK |
| 2026-11-15 | C1: API FastAPI, pipeline conversacional, clasificador, Model Router, SSE, migración 0002 | `pytest` 41 passed; uvicorn + curl de punta a punta |
| 2026-11-15 | Model Router: Ollama sustituido por GGUF en proceso (llama-cpp-python, extra `[gguf]`) + modelo Python propio | `pytest` 44 passed |
| 2026-11-15 | C2: Planner, Executor, Verifier, herramienta interna `system.time.now`, replanificación, techo global | `pytest` 59 passed; uvicorn: tool sembrada, plan guardado, stub → `partial` |
| 2026-11-15 | Modelo real: llama-cpp-python CUDA en venv, Qwen2.5-7B por GPU; prompt con capacidades reales; tests movidos a `nexus_test` y DB de desarrollo reiniciada (solo tenía datos de pruebas) | `pytest` 60 passed; API con Qwen: chat, GitHub → partial, hora → completed con fuente |
| 2026-11-15 | M1/M2: episodios, ingesta con redacción de secretos, chunking, embeddings ONNX, búsqueda híbrida, RAG en el Core con abstención | `pytest` 77 passed; 7 docs de NEXUS ingeridos y consultados con Qwen |
| 2026-11-15 | Revisión de Primitivo / Primitivo Worker: mapa de reutilización (§4b), 12 piezas priorizadas con sus tests | — |
| 2026-11-15 | Portado de Primitivo-f25: extractor de documentos con OCR + `POST /knowledge/files`; embedder a 128 tokens con reindexado gradual | `pytest` 94 passed; docx real + PDF escaneado subidos y consultados con Qwen |
| 2026-11-15 | Portado de Primitivo-f25: carpetas sincronizadas (manifiesto, pasadas, planificador) con raíces autorizadas y exclusión de archivos de credenciales; ruta de títulos en chunks; filtro por entidades | `pytest` 111 passed; carpeta real: cambios y borrados detectados, Qwen responde "9700" y se abstiene sobre Primitivo Suite |
| 2026-11-15 | Portado del Worker: detección de hardware, capas GPU automáticas, cadena de modelos con respaldo; health con hardware real; filtrado de `<think>` | `pytest` 122 passed; real: 26 capas con 5,15 GB VRAM libre; GGUF corrupto → Qwen3-4B |
| 2026-11-15 | G1: `http_safe` (portado del Worker), adaptador REST, conector GitHub readonly en revisión + API de aprobación; sin respuesta inventada si fallan las herramientas | `pytest` 181 passed; real contra api.github.com: repo y lista de repos con fuentes |
