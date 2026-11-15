# NEXUS AI — Plan de implementación y registro de progreso

> **Para agentes:** usar `superpowers:executing-plans` o `superpowers:subagent-driven-development` para ejecutar las tareas pendientes. Cada tarea sigue TDD (test que falla → código mínimo → test en verde). Marcar `[x]` al terminar y anotar en **Registro**.

**Objetivo:** construir NEXUS como orquestador controlado: *interpretar → contexto → planificar → validar → autorizar → ejecutar → verificar → responder* (Doc 02 §21).

**Arquitectura:** backend Python (FastAPI más adelante) con contratos Pydantic `extra=forbid`; Core (Planner/Validator/Executor/Verifier) que **solo** alcanza herramientas a través del Gateway (Tool Registry con hash aprobado); memoria en PostgreSQL + pgvector; frontend React+TS que solo habla con el Backend API.

**Stack actual:** Python 3.11 (venv `backend/.venv` con uv) · pydantic 2.13 · SQLAlchemy 2.1 · Alembic 1.20 · psycopg 3.3 · FastAPI 0.163 · uvicorn 0.54 · httpx 0.28 · pytest 8 · Docker Compose (pgvector/pgvector:pg16) · git → GitHub `yonaurif/Nexus`.

**Hardware real (medido 2026-11-15):** NVIDIA RTX 3050 **8 GB VRAM** · AMD Ryzen 5 5600G 6C/12T · **23,4 GB RAM visibles** (los docs decían 32 GB: revisar). Ollama **no instalado**.

**Arranque local:**
```bash
docker compose up -d db          # .env en la raíz: NEXUS_DB_PASSWORD, NEXUS_API_TOKEN (no se suben)
cd backend && .venv/Scripts/alembic.exe upgrade head
.venv/Scripts/python.exe -m pytest -q                              # 41 passed
.venv/Scripts/uvicorn.exe nexus.api.app:app --host 127.0.0.1 --port 8000
# Opcional, modelo local: NEXUS_OLLAMA_MODEL=<modelo> (y NEXUS_OLLAMA_URL si no es :11434)
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
  nexus/api/app.py  create_app(engine, model, token)                  ✅ HECHO (C1)
     POST /api/v1/chat/messages  → 202 {task_id, conversation_id, correlation_id}
     GET  /api/v1/tasks/{id}      → TaskView + AssistantResponse
     GET  /api/v1/tasks/{id}/events → SSE (id = execution_events.id, soporta Last-Event-ID)
     GET  /api/v1/system/health   → database + model (estados reales)
                  │ BackgroundTasks
                  v
  nexus/core/pipeline.py  run()                                       ✅ HECHO (C1)
     classifier.classify → _context (últimos 10 mensajes + SYSTEM_PROMPT)
     → Plan(1 paso synthesis) → validate_plan → models.generate → verificar → messages
                  │                                  │
                  │                   nexus/core/models.py  StubModel | OllamaModel ✅
                  v
  nexus/core/state.py  <── estado de tarea ──  [Orchestrator real]    (pendiente: C2)
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
             conversations, messages (0002)
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
- [x] `backend/nexus/core/models.py` — Model Router: `StubModel` (por defecto) y `OllamaModel` (con `NEXUS_OLLAMA_MODEL`)
- [x] `backend/nexus/core/pipeline.py` — classify → context → plan → validate → run → verify → responder
- [x] `backend/nexus/api/app.py` — 4 endpoints, auth Bearer, SSE con reconexión
- [x] `backend/tests/test_c1_api.py` — 20 tests; prueba manual con uvicorn + curl (health, 401, chat, 9 eventos SSE, tarea)

Diferido: tabla `model_invocations` (Doc 02 §13) → con el primer modelo real; presupuesto de contexto por tokens → cuando haya tokenizador del modelo elegido.

**Siguiente paso de modelo (D6):** con 8 GB de VRAM caben modelos de 7–8B en Q4 (unos 5 GB). Instalar Ollama y probar un modelo multilingüe pequeño antes de fijarlo.

### ⬜ C2 — Planner/Executor/Verifier (Doc 02 §6–8)

- [ ] Executor que solo invoca `ToolRegistry.resolve(...)` + adaptador simulado
- [ ] Verifier: compara `success_criteria` con `ToolResult`; distingue succeeded/partial/failed/sin evidencia
- [ ] Presupuestos (pasos, tiempo) y replanificación limitada (`verifying → planning`)
- [ ] Test integración: chat → plan → validator → tool simulada → verifier → respuesta (Doc 02 §17.2)

### ⬜ G1/G2 — REST y MCP readonly (Doc 05 §7–8)

- [ ] Validación JSON Schema completa (`jsonschema`) de input y output (sustituye el chequeo de `required`)
- [ ] Adaptador REST con allowlist de hosts y bloqueo SSRF
- [ ] MCP Host/Client (SDK oficial, versión fijada tras prueba en Windows/Docker); descubrimiento → `review` → aprobación
- [ ] Primer conector: **GitHub readonly** (`github.repository.get`)

### ⬜ T0/T1 — Text Learning (doc TL §12)

- [ ] Esquema JSONL + taxonomía de intenciones (clases de Doc 02 §4)
- [ ] Baseline TF-IDF + LogisticRegression con abstención → señal para el Intent Classifier del Core

### ⬜ M1–M5, C3–C6, G3–G6, Fases 2–5 de interfaz

Seguir el orden de cada documento; no empezar escritura externa (G5) sin aprobaciones (C5).

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
| D6 | Modelo LLM/embeddings | **Pendiente**: hardware ya conocido (RTX 3050 8 GB); falta instalar Ollama y comparar | Doc 02 §10, Doc 03 §8.1 |
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
