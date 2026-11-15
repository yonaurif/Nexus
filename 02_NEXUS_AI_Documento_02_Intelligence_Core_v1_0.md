# NEXUS AI — Documento 02
## Intelligence Core: cerebro central, planificación y ejecución
**Versión:** 1.0 · **Fecha:** 15 de noviembre de 2026 · **Estado:** Especificación técnica propuesta

> **Relación con la documentación existente.** Este documento desarrolla la arquitectura del Core descrita en `deep-research-report.md`: Core de Inteligencia, agentes especializados, ciclo Sense–Plan–Act–Verify, contratos JSON/Pydantic, límites de ejecución, memoria de eventos y reglas jerárquicas. También se alinea con el Documento 04 de interfaz. Las decisiones nuevas se marcan como propuestas cuando no estaban cerradas en las fuentes.

---

## 1. Propósito

El **Intelligence Core** es el cerebro central de NEXUS. Recibe una solicitud, interpreta su objetivo, reúne el contexto autorizado, decide si puede responder directamente o necesita planificar una tarea, selecciona capacidades y agentes, coordina su ejecución, verifica los resultados y entrega una respuesta comprensible.

No es simplemente un LLM conectado a herramientas. Es un sistema de orquestación con estado, políticas, memoria, límites, observabilidad y mecanismos de recuperación. El modelo de lenguaje ayuda a interpretar y proponer; el código de aplicación y los motores de políticas conservan la autoridad sobre permisos, parámetros, ejecución y persistencia.

### 1.1 Objetivos funcionales

- Comprender solicitudes en lenguaje natural y convertirlas en objetivos estructurados.
- Distinguir conversación, consulta de conocimiento, actualización de memoria, petición de agente, tarea con herramientas y cambio de reglas.
- Preparar contexto desde memoria y conocimiento sin volcar toda la base de datos al prompt.
- Elaborar planes legibles, acotados y verificables.
- Delegar subtareas a agentes con capacidades explícitas.
- Invocar herramientas exclusivamente mediante contratos tipados y el Gateway.
- Aplicar políticas y aprobaciones antes de cualquier efecto externo.
- Verificar resultados y comunicar incertidumbre, errores o resultados parciales.
- Registrar cada ejecución para auditoría y mejora.

### 1.2 Fuera de alcance del Core

El Core no debe: almacenar credenciales en prompts; ejecutar código arbitrario generado por el modelo; acceder directamente a bases de datos de negocio sin repositorios autorizados; alterar identidad o reglas fundamentales; decidir sus propios permisos; entrenarse automáticamente en producción; ni exponer razonamiento privado paso a paso. La interfaz puede mostrar un resumen de plan y operaciones relevantes, no una cadena interna de pensamiento.

## 2. Principios de arquitectura

1. **El modelo propone; el sistema dispone.** Ninguna salida del LLM autoriza por sí misma una acción.
2. **Separación de autoridad.** La autenticación, políticas y aprobación se comprueban mediante código confiable, no por la interpretación del modelo.
3. **Planner → Executor → Verifier.** Es el ciclo central establecido en la investigación original.
4. **Agentes especializados, no autónomos en privilegios.** Un agente ejecuta dentro de su ámbito; no puede ampliar sus permisos.
5. **Herramientas tipadas.** Cada operación tiene un esquema de entrada/salida y una política asociada.
6. **Presupuestos finitos.** Toda ejecución dispone de límites temporales, pasos, llamadas, tokens y recursos.
7. **Trazabilidad de extremo a extremo.** Cada mensaje, plan, paso y llamada lleva identificadores correlacionables.
8. **Cálculo exacto fuera del LLM.** Fechas, aritmética, filtros, SQL y conversiones se resuelven con código determinista.
9. **Abstención segura.** Si faltan datos, permiso o confianza, NEXUS pregunta, devuelve parcial o se abstiene.
10. **Independencia del proveedor de modelos.** El Core usa una abstracción de modelos y no depende de una marca concreta.

## 3. Arquitectura lógica del Core

```text
Solicitud del usuario
       |
       v
Request Gateway / Session Context
       |
       v
Intent & Request Classifier ----> Policy / Rule Engine
       |                                  |
       v                                  v
Context Builder <---- Memory / Knowledge Access
       |
       v
Planner (plan estructurado)
       |
       v
Plan Validator + Policy Gate
       |
       +---- ¿requiere aprobación? ----> Approval Service / UI
       |
       v
Orchestrator / Task State Machine
       |
       +---- Tool Router ----> Connector Gateway (API / MCP)
       |
       +---- Agent Manager --> Agentes especializados
       |
       +---- Trusted Services --> Python / DB / archivos autorizados
       |
       v
Verifier (resultado, evidencia, criterios)
       |
       +---- replanificar / fallback / pedir datos
       |
       v
Response Composer + Evidence Pack
       |
       v
Backend API --> Interfaz NEXUS

Todos los pasos --> Event Log / Audit / Metrics
```

### 3.1 Componentes y responsabilidades

| Componente | Responsabilidad | Autoridad que conserva | No debe hacer |
|---|---|---|---|
| Request Gateway | Validar solicitud, sesión, límites y correlación | Identidad de sesión | Inferir permisos por el texto |
| Intent Classifier | Clasificar tipo de petición y señales | Ninguna de ejecución | Autorizar una herramienta |
| Context Builder | Recuperar recuerdos y documentos pertinentes | Filtros de acceso | Mezclar datos privados de otros ámbitos |
| Model Router | Elegir modelo según tarea y disponibilidad | Política de modelos | Cambiar modelo base sin configuración |
| Planner | Proponer pasos y dependencias | Ninguna autorización | Ejecutar o aprobar operaciones |
| Plan Validator | Verificar estructura, tipos, límites y dependencias | Validez estructural | Aceptar campos desconocidos |
| Policy Gate | Evaluar reglas, scopes y riesgo | Autoridad de permisos | Delegar esa decisión al LLM |
| Orchestrator | Mantener estado y coordinar pasos | Estado de tarea | Saltarse el Policy Gate |
| Agent Manager | Seleccionar y coordinar agentes autorizados | Registro y ámbito de agentes | Otorgar permisos nuevos |
| Tool Router | Resolver tool_id hacia Gateway | Catálogo de herramientas | Llamar a endpoints arbitrarios |
| Executor | Ejecutar una operación ya autorizada | Runtime aislado | Interpretar instrucciones externas como código |
| Verifier | Comprobar resultado frente al objetivo | Criterios de verificación | Declarar éxito sin evidencia |
| Response Composer | Crear respuesta y evidencias | Formato de salida | Mostrar secretos o razonamiento interno |

### 3.2 Separación con Rule Engine

El Rule/Policy Engine es una autoridad independiente del razonamiento. El Core le solicita una decisión antes de ejecutar cada acción. Las reglas fundamentales —por ejemplo, que NEXUS no pueda autoasignarse privilegios o que la identidad del propietario solo la cambie el propietario autenticado— no se almacenan como simples recuerdos ni se modifican mediante entrenamiento.

## 4. Clasificación de solicitudes y enrutamiento

El Core debe identificar al menos estas clases iniciales, manteniendo una clase `unknown`:

| Clase | Ejemplo conceptual | Ruta principal |
|---|---|---|
| `conversation` | Conversación sin necesidad de herramientas | Modelo conversacional |
| `knowledge_query` | Pregunta sobre documentación o proyectos | Context Builder + RAG |
| `task_request` | Solicitud de ejecutar una tarea | Planner + Orchestrator |
| `agent_request` | Solicitud relacionada con GitHub, correo o YouTube | Agent Manager |
| `memory_update` | Guardar una preferencia o hecho | Memory Service con validación |
| `feedback` | Corregir una respuesta o dato aprendido | Feedback / Learning staging |
| `rule_proposal` | Proponer una regla | Rule parser + confirmación |
| `system_admin` | Configurar NEXUS o una integración | Ruta administrativa autenticada |
| `unknown` | Petición ambigua o confianza baja | Pregunta de aclaración / abstención |

La clasificación propuesta en `NEXUS Text Learning v1` comienza con TF-IDF + Logistic Regression, con abstención y posibilidad de derivar al LLM. El clasificador será una señal de enrutamiento, nunca un mecanismo de autorización. La línea base debe evaluarse con macro-F1, precision/recall por clase y calibración; umbrales numéricos se establecerán con datos reales, no se inventarán.

## 5. Context Builder y gestión del contexto

### 5.1 Fuentes de contexto

El Context Builder puede solicitar: identidad y preferencias autorizadas; memoria episódica relevante; hechos semánticos; documentos/chunks RAG; historial reciente de la conversación; estado de la tarea; resultados de herramientas; reglas aplicables (solo lectura); y perfiles de herramientas permitidas.

### 5.2 Política de inclusión

- Recuperar solo lo necesario para la petición.
- Aplicar permisos y clasificación de sensibilidad antes de recuperar.
- Priorizar fuentes actuales y con procedencia verificable.
- Etiquetar contenido recuperado como dato no confiable, nunca como instrucción de sistema.
- Mantener separado el prompt de sistema, las reglas confiables y el contenido externo.
- Incluir referencia, fecha y estado de confirmación cuando corresponda.
- Respetar el límite de contexto del modelo y reservar espacio para salida.
- Evitar repetir chunks o pasar documentos enteros cuando basten fragmentos.

### 5.3 Presupuesto de contexto

El Model Router y Context Builder deben usar un perfil por modelo: límite de tokens, reserva para salida, coste o uso de RAM/VRAM, ventana útil recomendada y tokenizador. El tamaño real debe calcularse con el tokenizador del modelo, no solo por caracteres. La estrategia inicial es resumen + recuperación selectiva, no insertar la memoria completa.

## 6. Planificación: Planner

El Planner convierte la solicitud en un plan con objetivo, pasos, dependencias, capacidades requeridas, criterios de éxito y puntos de aprobación. En la primera versión se recomienda un DAG acotado de pasos; la ejecución paralela se habilitará solo cuando dependencias e idempotencia lo permitan.

### 6.1 Contrato de plan

```json
{
  "plan_id": "plan_01J...",
  "task_id": "task_01J...",
  "goal": "Consultar el estado de un repositorio autorizado",
  "summary_for_user": "Consultaré el repositorio y resumiré su estado.",
  "steps": [
    {
      "step_id": "step_1",
      "kind": "tool_call",
      "tool_id": "github.repository.get",
      "depends_on": [],
      "input": {"repository_ref": "repo_allowed_123"},
      "success_criteria": ["Se devuelve el repositorio solicitado"],
      "risk_level": "read"
    },
    {
      "step_id": "step_2",
      "kind": "synthesis",
      "depends_on": ["step_1"],
      "success_criteria": ["El resumen se basa en campos devueltos"]
    }
  ],
  "limits": {"max_steps": 8, "max_duration_s": 60},
  "plan_version": 1
}
```

Los valores son ilustrativos. El servidor comprueba que `tool_id` existe, que sus parámetros coinciden con el esquema registrado y que el riesgo calculado por política no se rebaja por la salida del Planner.

### 6.2 Validación del plan

Antes de ejecutarlo, validar: tamaño máximo; esquema estricto; pasos permitidos; herramientas registradas; dependencias sin ciclos; ninguna referencia a secretos; presupuestos; idempotencia/reintentos; necesidad de aprobación; ausencia de pasos que cambien identidad, permisos o reglas protegidas; y que cada paso tenga criterio de éxito o una razón explícita para ser exploratorio.

### 6.3 Planes incompletos

Si se necesita un dato que no está disponible, el Planner debe generar `needs_user_input`. No debe inventar IDs, rutas, fechas, repositorios ni destinatarios. Si el coste de preguntar es bajo y la ambigüedad afecta a la ejecución, se pregunta antes de actuar.

## 7. Ciclo de ejecución y máquina de estados

### 7.1 Estados de tarea

`created` → `classifying` → `context_building` → `planning` → `plan_validating` → (`awaiting_approval`) → `queued` → `running` → `verifying` → `completed`.

Estados alternativos: `needs_input`, `partial`, `failed`, `cancel_requested`, `cancelled`, `expired`. Las transiciones deben ser explícitas y validadas. Una tarea completada no vuelve a `running`; una nueva ejecución genera un intento nuevo vinculado a la tarea original.

### 7.2 Bucle Planner–Executor–Verifier

1. **Planner:** propone los pasos con sus dependencias y criterios.
2. **Plan Validator / Policy Gate:** valida estructura, permisos, scopes, riesgo y aprobación.
3. **Executor:** invoca herramienta o agente a través de una interfaz tipada.
4. **Verifier:** verifica el output, cumplimiento del objetivo, procedencia y errores.
5. **Replanificación limitada:** si el resultado no basta, el Core puede solicitar un plan revisado dentro del presupuesto.
6. **Respuesta:** comunica resultado, límites y referencias.

No se permite que el Verifier declare correcto un resultado solo porque el modelo lo considere plausible. Debe contrastar criterios y datos devueltos.

### 7.3 Verificación por tipo de tarea

| Tipo | Evidencia de éxito |
|---|---|
| Consulta | Resultado de fuente, filtros aplicados y frescura |
| Cálculo | Resultado de función determinista y datos de entrada |
| Escritura externa | Confirmación del sistema remoto y referencia de operación |
| Ingesta | Documento registrado, estado de parsing e índice actualizado |
| Memoria | Registro persistido y política de privacidad satisfecha |
| Agente compuesto | Subtareas finalizadas, fallidas o parciales con resumen |
| Respuesta generativa | Evidencias disponibles, límites y ausencia de contradicciones no resueltas |

## 8. Executor y herramientas confiables

El Executor solo ejecuta acciones declaradas en catálogos internos. Los LLM no generan comandos shell libres ni SQL libre para ejecución. Para operaciones exactas se llama a funciones Python controladas o repositorios parametrizados.

Cada ejecución recibe: `task_id`, `step_id`, `correlation_id`, identidad de sesión validada, identidad del agente, `tool_id`, input validado, scopes temporales, deadline, idempotency key y contexto mínimo. No recibe tokens de otros conectores.

### 8.1 Resultado normalizado

```json
{
  "execution_id": "exec_01J...",
  "status": "succeeded",
  "tool_id": "github.repository.get",
  "started_at": "2026-11-15T13:20:00Z",
  "finished_at": "2026-11-15T13:20:01Z",
  "data": {"repository": "example", "visibility": "private"},
  "evidence": [{"source_ref": "github:repo:123", "retrieved_at": "2026-11-15T13:20:01Z"}],
  "error": null,
  "correlation_id": "corr_01J..."
}
```

El ejemplo no define una herramienta real. El contrato del resultado incluye estado, datos tipados, evidencia, timestamps y correlación. Los datos devueltos permanecen no confiables hasta validarse.

## 9. Agent Manager y agentes especializados

Los agentes previstos en la documentación original incluyen GitHub Agent, Email Agent, YouTube Agent y Productivity Agent. Se añaden solo cuando haya un dominio funcional que justifique aislar instrucciones, herramientas y memoria.

### 9.1 Ficha de agente

Cada agente debe declarar: `agent_id`, nombre, versión, propósito, capacidades permitidas, herramientas permitidas, ámbitos de memoria, modelo recomendado (opcional), límites de ejecución, contenedor/runtime, propietario lógico, estado y suite de pruebas.

### 9.2 Aislamiento

La investigación original propone un contenedor Docker por agente y comunicación HTTP interno o RPC. Se mantiene como patrón preferido para agentes con dependencias o riesgos diferenciados, pero no se exige crear un contenedor por cada tarea ligera. El aislamiento se dimensionará con pruebas.

Un agente no recibe acceso general al host. Sus carpetas, red, CPU, memoria, duración y credenciales se limitan a su función. Cada servidor MCP y conector obtiene scopes propios. El agente no puede pedir un token más potente que el asignado.

### 9.3 Ciclo Sense–Plan–Act–Verify

- **Sense:** recibir un evento o tarea autorizada.
- **Plan:** producir subtareas estructuradas para su dominio.
- **Act:** ejecutar herramientas registradas y cálculos fiables.
- **Verify:** devolver resultados, evidencia, errores y estado.

El Core conserva la orquestación global y puede detener o cancelar el agente. Los agentes no se coordinan mediante mensajes de lenguaje libre sin esquema; intercambian envelopes estructurados.

### 9.4 Comunicación entre agentes

Toda delegación se representa como una subtarea con `parent_task_id`, `assigned_agent_id`, objetivo, contexto mínimo, permisos, deadline y contrato de salida. No se comparte todo el historial de chat automáticamente. Las dependencias y resultados se almacenan en el registro de tareas.

## 10. Model Router y abstracción de modelos

El Core debe tener una interfaz única para modelos de lenguaje, clasificadores y embeddings, separando proveedores/servidores de la lógica de negocio.

El Model Router seleccionará por: tipo de tarea; idioma; tamaño de contexto; latencia; capacidad local disponible; modalidad; disponibilidad; política de privacidad y coste computacional. El sistema debe poder usar un LLM local vía runtime elegido más adelante y, solo si se configura y autoriza, un servicio externo. El hardware declarado actualmente es Windows/Docker y 32 GB de RAM; CPU, GPU y VRAM siguen sin especificarse. Por eso no se fija un LLM definitivo.

Los clasificadores de intención y embeddings no deben confundirse con el LLM conversacional. Se versionan y evalúan por separado. Los cálculos exactos no se delegan al modelo.

## 11. Límites, timeouts y recuperación

Cada ejecución tiene presupuestos combinables:

- pasos máximos por plan;
- llamadas totales y por conector;
- profundidad de delegación y número de agentes;
- tiempo total y timeout por herramienta;
- tokens de entrada y salida;
- tamaño máximo de resultados;
- memoria/CPU/VRAM según runtime;
- reintentos y presupuesto de replanificación.

Los valores numéricos por defecto quedan pendientes de benchmark local. El contrato debe admitir límites configurables por perfil de tarea y un techo global no modificable por el LLM.

### 11.1 Política de reintentos

- Reintentar automáticamente solo errores transitorios y operaciones idempotentes.
- No reintentar ciegamente operaciones de escritura cuando no se conoce si se aplicaron.
- Usar idempotency key para evitar duplicaciones cuando el conector lo soporte.
- Aplicar backoff acotado y circuit breaker por conector.
- Cuando se agote el presupuesto, devolver estado parcial/fallo con causa comprensible.

### 11.2 Cancelación

La cancelación es cooperativa: marca tarea y propagación de señal a agentes/ejecutores. Una acción remota ya iniciada puede no ser reversible; la interfaz debe mostrarlo y no prometer que cancelar borra el efecto.

## 12. Integración con memoria y aprendizaje

El Core consulta Memory Service y Knowledge Service mediante contratos internos. No accede directamente a tablas. Después de una ejecución puede emitir eventos para guardar el episodio, sus fuentes y el resultado. La consolidación de episodios en hechos semánticos se realiza como proceso separado y gobernado.

El feedback de usuario se registra como evento. No actualiza automáticamente pesos del modelo en producción: se puede enviar a staging del Learning Engine para revisión, dataset, experimento, evaluación y aprobación, siguiendo `NEXUS Text Learning v1`.

## 13. Persistencia mínima del Core

El documento 03 define el esquema canónico de memoria y datos. El Core requiere como mínimo entidades lógicas para:

| Entidad | Propósito |
|---|---|
| `conversations` / `messages` | Historial de interacción |
| `tasks` | Objetivo y estado de ejecución |
| `plans` / `plan_steps` | Plan versionado y pasos |
| `agent_runs` | Ejecuciones de agentes |
| `tool_executions` | Llamadas a herramientas |
| `approvals` | Aprobaciones ligadas a acción y parámetros |
| `execution_events` | Eventos cronológicos y correlación |
| `model_invocations` | Modelo/versión y métricas técnicas |
| `audit_events` | Cambios de estado y acciones relevantes |

No todos los payloads deben guardarse en claro. Aplicar minimización, clasificación de sensibilidad y referencias a objetos almacenados cuando proceda.

## 14. Contratos internos principales

Los contratos se definirán con Pydantic y se publicarán como JSON Schema versionado. Los modelos deben rechazar campos desconocidos en contratos sensibles (`extra=forbid` o equivalente), validar tamaños y tipos, y soportar compatibilidad explícita.

| Contrato | Campos mínimos |
|---|---|
| `ChatRequest` | conversation_id opcional, message, locale, attachments refs |
| `Task` | task_id, owner/session, goal, status, created_at, deadline |
| `Plan` | plan_id, task_id, summary, steps, limits, version |
| `PlanStep` | step_id, kind, dependency IDs, tool/agent ID, input schema ref, criteria |
| `ToolInvocation` | tool_id, connector_id, arguments, principal, scopes, idempotency_key |
| `ToolResult` | execution_id, status, data, evidence, error, timestamps |
| `ApprovalRequest` | target, exact action, parameters hash, risk, expiry |
| `AgentTask` | parent_task_id, agent_id, allowed context, capabilities, deadline |
| `CoreEvent` | event_id, type, occurred_at, correlation_id, entity_id, schema_version, payload |
| `AssistantResponse` | text, presentation blocks, sources, task status, warnings |

## 15. Observabilidad y auditoría

Toda operación debe propagar `correlation_id` y `trace_id`. Registrar: actor, sesión, tarea, plan, agente, herramienta, conector, versión de esquema, resultado, duración, error normalizado y política aplicada. No registrar secretos, tokens ni contenido sensible innecesario.

Métricas mínimas: tasa de finalización; tareas parciales/fallidas; latencia por fase; llamadas por tarea; reintentos; aprobaciones; abstenciones; errores por agente/conector; consumo de tokens; uso de RAM/CPU/GPU si existe; y tasa de corrección posterior.

La interfaz recibirá estados y resúmenes. No expondrá chain-of-thought, prompts internos, claves ni detalles de sandbox que permitan eludir controles.

## 16. Seguridad y amenazas

- Prompt injection en chat, documentos o resultados de herramientas: delimitar y etiquetar datos no confiables; validar acciones en backend.
- Confused deputy: verificar usuario, agente, conector, herramienta y objeto en cada invocación.
- Escalada de privilegios: scopes inmutables durante una ejecución y política externa al LLM.
- Bucles de agentes: límites de profundidad, pasos, tiempo y presupuesto.
- Salida maliciosa de herramientas: validar salida antes de reinyectarla en el contexto.
- Fuga de secretos: vault/variables seguras; filtro de logs; nunca enviar credenciales al prompt.
- Código arbitrario: no ejecutar cadenas de texto generadas; funciones permitidas y sandbox.
- Abuso de memoria: segmentación por propietario/ámbito y filtros antes de recuperación.
- Acciones irreversibles: aprobación humana contextual y registro de efecto remoto.

## 17. Pruebas

### 17.1 Unitarias

Validación de contratos, transiciones de estados, límites, permisos, orden de pasos, dependencias, idempotencia, cálculo determinista, selección de modelos y normalización de errores.

### 17.2 Integración

Chat → Planner → Policy Gate → herramienta simulada → Verifier → respuesta. Otra prueba debe incluir un agente especializado y otra un resultado parcial por conector no disponible.

### 17.3 Seguridad

Intentos de prompt injection en contenido recuperado; herramienta desconocida; schema alterado; parámetros extra; permiso revocado entre planificación y ejecución; token de otro conector; IDOR; salida demasiado grande; loop; timeout; cancelación durante ejecución; reintento de una escritura.

### 17.4 Regresión

Mantener un conjunto de tareas representativas y resultados esperados. Cada cambio de modelo, prompt de sistema, política o herramienta debe ejecutar pruebas de regresión antes de promoverse.

## 18. Fases de implementación

**C0 — Contratos y estado:** modelos Pydantic, IDs, estados, persistencia de tareas y errores.

**C1 — Core conversacional:** request gateway, clasificador simple, model router inicial, chat y response composer sin herramientas de escritura.

**C2 — Planner/Executor/Verifier:** planes estructurados, validador, ejecución simulada, presupuestos y verificación.

**C3 — Memoria:** integración con los contratos del Documento 03, recuperación limitada y episodios.

**C4 — Gateway y primer agente:** integración de solo lectura con una herramienta autorizada (GitHub readonly como primer ejemplo existente en la documentación).

**C5 — Aprobaciones y resiliencia:** políticas, cancelación, idempotencia, errores y auditoría.

**C6 — Multiagente y optimización:** aislamiento y ejecución paralela solo después de validar carga y seguridad.

## 19. Criterios de aceptación

1. Una solicitud se convierte en tarea identificable y trazable.
2. Un plan inválido o con herramienta desconocida se rechaza antes de ejecutar.
3. El Planner no puede autorizarse a sí mismo.
4. El Policy Gate verifica permisos en el instante de ejecución.
5. El Executor solo llama a interfaces registradas.
6. Cada paso tiene estado, timeout y resultado normalizado.
7. El Verifier distingue éxito, parcial, fallo y falta de evidencia.
8. Un error de conector no bloquea la aplicación ni se transforma en éxito aparente.
9. Los reintentos no duplican escrituras cuando hay idempotencia disponible.
10. La cancelación actualiza el estado y comunica límites de reversibilidad.
11. Los agentes usan contextos y herramientas limitados.
12. La salida al usuario incluye resumen, estado, fuente y advertencias cuando proceda.
13. El Core no revela secretos ni razonamiento privado paso a paso.
14. Las métricas y trazas permiten reconstruir la ejecución sin almacenar secretos.
15. La configuración del Core no depende de un modelo LLM específico.

## 20. Decisiones pendientes

- Framework de orquestación: código propio explícito vs librería especializada. Recomendación inicial: orquestador Python propio y pequeño para mantener estados transparentes.
- Runtime local de modelos y Model Router definitivo, pendiente del hardware CPU/GPU/VRAM.
- Límites cuantitativos iniciales, pendientes de pruebas.
- Transporte interno entre Core y agentes: HTTP/RPC y colas, según despliegue.
- Qué tareas permiten paralelismo en MVP.
- Política de retención del historial y payloads de ejecución.

## 21. Resumen

El Intelligence Core es un orquestador controlado, no un LLM con autoridad total. Su ciclo central será **interpretar → recuperar contexto → planificar → validar → autorizar → ejecutar → verificar → responder**. Los agentes son especialistas limitados; las API/MCP se alcanzan a través del Gateway; la memoria se consulta mediante servicios; y las reglas protegidas se mantienen fuera de los pesos del modelo. Esta separación convierte la idea de NEXUS en un sistema auditable, ampliable y seguro.
