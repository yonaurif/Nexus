# NEXUS AI — Plan de implementación y registro de progreso

> **Para agentes:** usar `superpowers:executing-plans` o `superpowers:subagent-driven-development` para ejecutar las tareas pendientes. Cada tarea sigue TDD (test que falla → código mínimo → test en verde). Marcar `[x]` al terminar y anotar en **Registro**.

**Objetivo:** construir NEXUS como orquestador controlado: *interpretar → contexto → planificar → validar → autorizar → ejecutar → verificar → responder* (Doc 02 §21).

**Arquitectura:** backend Python (FastAPI más adelante) con contratos Pydantic `extra=forbid`; Core (Planner/Validator/Executor/Verifier) que **solo** alcanza herramientas a través del Gateway (Tool Registry con hash aprobado); memoria en PostgreSQL + pgvector; frontend React+TS que solo habla con el Backend API.

**Stack actual:** Python 3.11 · pydantic 2.13 · pytest 8 · Docker Compose (pgvector/pgvector:pg16) · git.

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
            [Frontend React]  ── HTTPS/SSE ──>  [Backend API]          (pendiente: Fase 1 / C1)
                                                     │
                                                     v
  nexus/core/state.py  <── estado de tarea ──  [Orchestrator]           (pendiente: C2)
                                                     │ Plan (contracts.Plan)
                                                     v
  nexus/core/plan_validator.py  ── validate_plan(plan, registry) ──┐    ✅ HECHO
                                                                   │ registry.resolve(tool_id)
                                                                   v
  nexus/gateway/registry.py  (ToolRegistry: register/approve/resolve) ✅ HECHO
            │ ToolManifest.definition_hash (sha256)
            v
  nexus/contracts.py  (Plan, PlanStep, ToolManifest, ToolResult, Evidence) ✅ HECHO
            │
            v
  docker-compose.yml → PostgreSQL 16 + pgvector (127.0.0.1:5432)      ✅ definido, sin tablas aún
```

**Conexiones reales en código hoy:**
1. `plan_validator.validate_plan` → llama a `ToolRegistry.resolve` por cada paso `tool_call`. Un `GatewayError` se convierte en `PlanRejected` con el mismo código (`TOOL_NOT_ALLOWED`, `TOOL_DEFINITION_CHANGED`). → Doc 02 aceptación #2, Doc 05 aceptación #4.
2. `ToolRegistry` guarda el `definition_hash` en el momento de `approve()`. Si se re-registra una definición distinta, `resolve` falla hasta nueva aprobación. → Doc 05 §8.5.
3. Todos los contratos heredan de `Strict` (`extra="forbid"`). → Doc 02 §14.
4. `state.transition` es la única forma de cambiar estado; los terminales no tienen salida. → Doc 02 §7.1.

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

### ⬜ M0 — Persistencia (Doc 03 §17, Doc 02 §13)

- [ ] Crear `.env` con `NEXUS_DB_PASSWORD` y levantar `docker compose up -d db`
- [ ] Añadir `sqlalchemy`, `alembic`, `psycopg[binary]` a `pyproject.toml`
- [ ] Migración 0001: `CREATE EXTENSION vector`; tablas `tasks`, `plans`, `plan_steps`, `tool_executions`, `execution_events`, `audit_events`, `memory_sources` (todas con `owner_id`, timestamps)
- [ ] Test de integración: insertar tarea, transicionar con `state.transition`, persistir evento con `correlation_id`
- [ ] Mover `ToolRegistry` de memoria a tabla `tools` (`tool_id`, `manifest jsonb`, `approved_hash`, `status`)

### ⬜ C1 — Core conversacional (Doc 02 §18, Doc 04 Fase 1)

- [ ] FastAPI: `POST /api/v1/chat/messages`, `GET /api/v1/tasks/{id}`, `GET /api/v1/system/health`
- [ ] Contratos `ChatRequest`, `Task`, `AssistantResponse`, `CoreEvent` en `contracts.py`
- [ ] Model Router con interfaz única (`generate(prompt, profile)`) y un adaptador local (Ollama) — **pendiente hardware CPU/GPU/VRAM**
- [ ] SSE para `assistant.status.changed`

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
| D4 | Registro de herramientas en memoria hasta M0 | Temporal | ponytail |
| D5 | Validación de input solo `required` hasta G1 | Temporal | ponytail |
| D6 | Modelo LLM/embeddings | **Pendiente** (falta CPU/GPU/VRAM) | Doc 02 §10, Doc 03 §8.1 |
| D7 | SSE vs WebSocket | SSE inicial propuesto | Doc 04 §13 |
| D8 | Secret store, cola (Redis Streams), versión MCP SDK | **Pendiente** | Doc 05 §22 |

## 6. Registro

| Fecha | Qué | Verificación |
|---|---|---|
| 2026-11-15 | Leídos los 7 documentos; creado este plan | — |
| 2026-11-15 | C0+G0: contratos, estados, validador, registry; compose de Postgres | `pytest` 14 passed; `docker compose config` OK |
| 2026-11-15 | Repo conectado a GitHub: `origin` → https://github.com/yonaurif/Nexus (rama `main`) | `git push -u origin main` |
