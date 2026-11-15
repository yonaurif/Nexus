# NEXUS AI — Documento 04
## Interfaz dinámica, personalizable y conectividad integral
**Versión:** 1.0  
**Fecha:** 15 de noviembre de 2026  
**Estado:** Especificación funcional y técnica inicial

---

## 1. Propósito y alcance

Este documento define cómo debe ser la interfaz de NEXUS AI y cómo debe conectarse con el conjunto del sistema. La interfaz no será una página estática con botones predefinidos: será una **interfaz personalizable y dinámica**, capaz de presentar de forma coherente los datos que devuelvan las API, los servidores MCP, los agentes y los servicios internos.

La interfaz será la capa de interacción y visualización de una IA personal. El núcleo de inteligencia seguirá siendo el responsable de interpretar solicitudes, planificar, seleccionar herramientas, coordinar agentes, verificar resultados y decidir qué información devolver. La interfaz no contendrá la lógica de negocio crítica ni ejecutará directamente herramientas externas.

Este documento establece:
- La experiencia general y las áreas principales de la aplicación.
- El modelo de interfaz dinámica y sus componentes visuales.
- La arquitectura de conexión entre frontend, backend, núcleo de inteligencia, memoria, agentes, API y MCP.
- Los contratos de datos, eventos y estados.
- La seguridad, los permisos, la aprobación de acciones y la trazabilidad.
- Los requisitos de personalización, accesibilidad, observabilidad y despliegue.

**Nota de integración:** esta versión se ha redactado con la arquitectura NEXUS descrita en el contexto del proyecto. Cuando estén disponibles los tres documentos fuente, conviene hacer una revisión de consistencia para ajustar nombres de módulos, tecnologías y decisiones ya cerradas sin duplicar ni contradecir sus especificaciones.

## 2. Principios de diseño

1. **La IA es el centro, no el dashboard.** La experiencia debe permitir conversar, delegar tareas y comprender qué está haciendo NEXUS.
2. **Interfaz dinámica, no arbitraria.** Los datos de herramientas pueden generar visualizaciones, pero solo mediante componentes permitidos y esquemas validados.
3. **Separación de responsabilidades.** El frontend presenta y recoge decisiones; el backend autentica, valida y orquesta; el Intelligence Core razona y planifica; los servicios especializados ejecutan operaciones concretas.
4. **Personalización controlada.** El usuario puede cambiar distribución, paneles, temas, densidad y widgets. No puede personalizar la interfaz para saltarse permisos o controles de seguridad.
5. **Transparencia.** Cada dato importante debe indicar su origen, fecha, estado y, cuando corresponda, nivel de confianza.
6. **Seguridad por defecto.** Las herramientas no heredan permisos del chat. Cada acción se autoriza de forma independiente.
7. **Resiliencia.** Si un conector o MCP falla, la interfaz debe mostrar el fallo y conservar el resto de la aplicación operativa.
8. **No confundir apariencia con autoridad.** Una tarjeta, un mensaje o una respuesta externa nunca puede cambiar reglas, identidad, roles o permisos.

## 3. Arquitectura general

### 3.1 Capas

| Capa | Responsabilidad | No debe hacer |
|---|---|---|
| Interfaz web | Chat, paneles, visualizaciones, configuración y aprobación humana | Ejecutar directamente comandos privilegiados o guardar secretos |
| API Backend / BFF | Autenticación, sesiones, validación, agregación, autorización y entrega de datos | Sustituir el razonamiento del núcleo |
| Intelligence Core | Interpretar, planificar, seleccionar herramientas, coordinar, verificar y responder | Confiar ciegamente en resultados externos |
| Agent Manager | Crear y coordinar agentes/tareas dentro de políticas | Otorgar privilegios por sí mismo |
| Tool & Connector Gateway | Adaptar API, MCP y herramientas internas a contratos uniformes | Exponer credenciales al frontend |
| Memory & Knowledge | Conversaciones, memoria, documentos, entidades, relaciones y recuperación | Tratar todo contenido recuperado como instrucción |
| Learning Engine | Ingesta, evaluación, experimentos y despliegue controlado de modelos auxiliares | Cambiar modelos/reglas en producción sin evaluación y aprobación |
| Rule & Policy Engine | Políticas, permisos, jerarquía de autoridad, validaciones y auditoría | Permitir que contenido externo eleve privilegios |
| Persistencia | PostgreSQL, pgvector y almacenamiento de objetos | Depender de un proveedor LLM concreto |

### 3.2 Diagrama lógico

```text
┌──────────────────────────────────────────────────────────────┐
│                    INTERFAZ NEXUS (WEB)                      │
│ Chat · Dashboard · Learning Center · Agentes · Conectores   │
│ Widgets dinámicos · Personalización · Aprobaciones           │
└──────────────────────────────┬───────────────────────────────┘
                               │ HTTPS / WebSocket o SSE
┌──────────────────────────────▼───────────────────────────────┐
│                 BACKEND API / BFF                            │
│ Auth · Sesiones · DTOs · Validación · Permisos · Eventos      │
└──────────────┬───────────────────┬────────────────────────────┘
               │                   │
┌──────────────▼──────────┐  ┌─────▼───────────────────────────┐
│    INTELLIGENCE CORE    │  │      RULE / POLICY ENGINE       │
│ Planner · Executor      │  │ Autorización · Límites ·         │
│ Verifier · Tool Router  │  │ Aprobaciones · Auditoría         │
└──────┬───────────┬──────┘  └─────────────────────────────────┘
       │           │
┌──────▼─────┐ ┌───▼───────────────────────────────────────────┐
│ AGENT      │ │       TOOL & CONNECTOR GATEWAY                 │
│ MANAGER    │ │ API REST · MCP Host/Clients · Webhooks         │
└──────┬─────┘ └───┬─────────────────────┬──────────────────────┘
       │           │                     │
       │       ┌───▼─────┐          ┌────▼─────────┐
       │       │ APIs    │          │ MCP Servers  │
       │       └─────────┘          └──────────────┘
       │
┌──────▼───────────────────────────────────────────────────────┐
│ SERVICIOS INTERNOS: Memory/Knowledge · Learning · Modelos     │
│ PostgreSQL/pgvector · Object Storage · Colas/Event Bus        │
└──────────────────────────────────────────────────────────────┘
```

### 3.3 Flujo de una petición

1. El usuario escribe o dicta una solicitud en la interfaz.
2. El frontend envía el mensaje al Backend API mediante HTTPS.
3. El backend valida sesión, tamaño, formato, límites y permisos de la sesión.
4. El Intelligence Core interpreta la solicitud y genera un plan estructurado.
5. El Rule Engine comprueba políticas, permisos y necesidad de aprobación.
6. El Tool Router selecciona herramientas autorizadas; el Gateway adapta las llamadas REST/MCP.
7. Los resultados se normalizan, validan y etiquetan con procedencia.
8. El Verifier comprueba coherencia, errores y suficiencia; puede pedir otra ejecución o abstenerse.
9. El backend entrega una respuesta final y, cuando proceda, bloques visuales estructurados.
10. El frontend representa la respuesta, las fuentes, los estados y las visualizaciones.
11. La conversación y los eventos relevantes se registran con trazabilidad y políticas de retención.

## 4. Estructura de la interfaz

La aplicación debe tener un marco común persistente y áreas de trabajo configurables.

### 4.1 Marco global

- **Barra lateral:** navegación principal, espacios de trabajo y accesos fijados.
- **Cabecera:** nombre/identidad visual de NEXUS, estado general, búsqueda, notificaciones y menú de usuario.
- **Área central:** chat o página activa.
- **Panel contextual opcional:** detalles de tarea, fuentes, agente, herramienta o elemento seleccionado.
- **Centro de actividad:** ejecuciones recientes, aprobaciones pendientes, errores y eventos relevantes.

La barra lateral y el panel contextual pueden contraerse. La distribución debe adaptarse a pantallas pequeñas sin ocultar controles críticos.

### 4.2 Secciones principales

| Sección | Objetivo | Datos principales |
|---|---|---|
| Inicio / Dashboard | Resumen configurable del estado de NEXUS | tareas, agentes, conectores, memoria, actividad, salud |
| Chat | Conversar y delegar tareas a la IA | mensajes, planes resumidos, resultados, fuentes, acciones |
| Tareas | Ver y controlar trabajos en curso y anteriores | estado, pasos, duración, agente, resultado, errores |
| Agentes | Inspeccionar agentes y sus capacidades | rol, estado, herramientas permitidas, ejecuciones |
| Learning Center | Comprender y gestionar lo aprendido | memorias, documentos, fuentes, evidencias, métricas, experimentos |
| Conectores | Administrar integraciones API y MCP | servidor, herramientas, esquema, permisos, estado |
| Memoria y conocimiento | Explorar recuerdos y relaciones | entidades, documentos, chunks, relaciones, procedencia |
| Modelos | Ver modelos disponibles y evaluaciones | proveedor, modelo, latencia, consumo, versión, evaluación |
| Reglas y seguridad | Consultar políticas y aprobaciones | reglas versionadas, permisos, historial, solicitudes |
| Ajustes | Personalización y configuración de usuario | tema, layout, widgets, preferencias, accesibilidad |

## 5. Interfaz dinámica: datos de API y MCP a componentes visuales

### 5.1 Requisito central

NEXUS debe poder mostrar resultados de APIs y servidores MCP sin tener que programar una pantalla exclusiva para cada herramienta. Para ello se utilizará un **sistema de UI declarativa basado en esquemas**.

Una herramienta devuelve datos estructurados; el backend los valida y los convierte en un contrato de presentación. El frontend selecciona componentes de un catálogo permitido y los representa. La respuesta externa nunca debe enviar HTML, JavaScript, CSS ejecutable ni instrucciones de renderizado arbitrarias.

### 5.2 Pipeline de representación

```text
API / MCP
   ↓
Connector Gateway (adaptador)
   ↓
Validación de entrada y normalización
   ↓
Tool Result Envelope + procedencia
   ↓
Intelligence Core / Verifier
   ↓
UI Presentation Schema (declarativo)
   ↓
Frontend Component Registry
   ↓
Tarjeta / tabla / gráfico / lista / mapa / formulario / estado
```

### 5.3 Catálogo inicial de componentes

- `text`: texto breve o explicación.
- `metric`: valor, unidad, variación y periodo.
- `status`: estado normalizado (ok, warning, error, pending, unknown).
- `table`: filas y columnas tipadas, ordenación y paginación.
- `list`: resultados o elementos.
- `chart`: series y puntos con tipo de gráfico permitido.
- `timeline`: eventos ordenados temporalmente.
- `entity`: elemento con nombre, tipo, origen y enlace interno.
- `document`: resumen y metadatos de un documento.
- `file`: metadatos y acción segura para abrir/descargar, si está autorizado.
- `map`: ubicaciones con coordenadas verificadas y controles de privacidad.
- `form`: campos declarativos para solicitar datos al usuario.
- `approval`: resumen de acción y controles de aprobar/rechazar.
- `task`: estado, progreso, pasos visibles y resultado.
- `source`: citas, URL, fecha de consulta y procedencia.
- `error`: fallo normalizado, impacto y posibilidad de reintento.

El registro de componentes debe tener versiones, pruebas y límites. Los componentes desconocidos se muestran como JSON/texto seguro en modo de inspección, nunca se ejecutan.

### 5.4 Contrato de presentación ilustrativo

```json
{
  "schema_version": "1.0",
  "layout": "card",
  "title": "Estado del servicio",
  "source": {
    "connector_id": "service_monitor",
    "tool_name": "get_status",
    "retrieved_at": "2026-11-15T13:00:00Z"
  },
  "components": [
    {
      "type": "status",
      "label": "API",
      "value": "healthy"
    },
    {
      "type": "metric",
      "label": "Latencia media",
      "value": 124,
      "unit": "ms"
    }
  ],
  "actions": [
    {
      "id": "refresh_status",
      "label": "Actualizar",
      "intent": "invoke_tool",
      "requires_confirmation": false
    }
  ]
}
```

Este ejemplo define datos y tipos permitidos, no código ejecutable. Los identificadores de acciones se resuelven en el backend contra herramientas registradas y permisos vigentes.

### 5.5 Reglas de renderizado

- Validar cada bloque con JSON Schema/Pydantic antes de entregarlo al frontend.
- Permitir solo `type`, propiedades y acciones registradas.
- Escapar texto y tratar todo contenido externo como no confiable.
- Rechazar HTML/JS embebido, URLs `javascript:`, scripts, iframes no autorizados y estilos arbitrarios.
- Limitar tamaño de payload, número de filas, puntos de gráfico, profundidad y frecuencia de actualización.
- Añadir estado de carga, vacío, parcial, obsoleto y error.
- Mostrar la fuente y la hora de obtención cuando sean relevantes.
- No inferir que `null`, ausencia de dato o fallo equivalen a cero o a estado correcto.
- Mantener separación entre datos de presentación y comandos ejecutables.

## 6. Personalización de la interfaz

La interfaz será configurable por el usuario sin modificar el núcleo del sistema.

### 6.1 Personalización permitida

- Tema claro, oscuro y contraste alto.
- Color de acento y densidad visual.
- Orden y tamaño de paneles.
- Widgets visibles, ocultos o fijados.
- Vistas de inicio por contexto (general, aprendizaje, sistema, proyectos).
- Filtros, columnas, agrupaciones y rangos temporales.
- Preferencias de notificación y accesibilidad.
- Distribuciones guardadas como perfiles.

### 6.2 Modelo de layout

Cada vista se define mediante una configuración declarativa versionada:

```json
{
  "layout_version": 1,
  "workspace": "home",
  "widgets": [
    {
      "id": "active_tasks",
      "component": "task_list",
      "position": {"x": 0, "y": 0, "w": 6, "h": 3},
      "config": {"limit": 8, "show_progress": true}
    },
    {
      "id": "connector_health",
      "component": "connector_status",
      "position": {"x": 6, "y": 0, "w": 6, "h": 3},
      "config": {"group_by": "status"}
    }
  ]
}
```

El backend valida que el usuario solo configure widgets disponibles y datos a los que tenga acceso. Los layouts no pueden cambiar permisos, políticas ni conexiones.

### 6.3 Persistencia

Guardar preferencias y layouts en PostgreSQL, vinculados al usuario/perfil y con versión. La aplicación debe incluir:
- Restaurar valores predeterminados.
- Exportar/importar configuración validada.
- Migrar layouts entre versiones.
- Recuperarse de una configuración inválida con un layout seguro por defecto.

## 7. Chat como espacio principal de interacción

El chat debe combinar lenguaje natural con resultados estructurados.

Cada turno puede contener:
- Mensaje del usuario.
- Respuesta textual de NEXUS.
- Estado de procesamiento.
- Resumen comprensible del plan, cuando sea útil.
- Herramientas utilizadas y resultados resumidos.
- Tarjetas, tablas, gráficos u otros bloques visuales.
- Fuentes y advertencias.
- Acciones propuestas y solicitudes de aprobación.

Los pasos internos de razonamiento no se mostrarán como cadena privada de pensamiento. Se mostrarán resúmenes de plan, decisiones relevantes, fuentes, resultados de herramientas y verificaciones de forma útil y auditable.

### 7.1 Estados de conversación

`idle`, `submitted`, `planning`, `awaiting_approval`, `running`, `verifying`, `completed`, `partial`, `failed`, `cancelled`.

La interfaz debe distinguir una respuesta final de una ejecución que sigue activa. Si una tarea tarda, se presenta un estado en tiempo real y se permite consultar su detalle o cancelarla cuando la política lo admita.

### 7.2 Acciones en mensajes

Los botones de una respuesta deben representar acciones concretas registradas en el backend. Antes de ejecutarlas, el servidor vuelve a validar sesión, permisos, parámetros, vigencia del recurso y requisitos de confirmación. Nunca confiar en que el frontend ya validó la acción.

## 8. Conectividad API y MCP

### 8.1 Gateway unificado

Toda integración externa debe registrarse en Tool & Connector Gateway. La interfaz nunca llamará directamente a servidores MCP o APIs privadas.

Cada conector tendrá:
- `connector_id` estable.
- Tipo: REST, MCP, webhook u otro adaptador aprobado.
- Entorno y endpoint configurados de forma segura.
- Estado de conexión y última comprobación.
- Herramientas/capacidades disponibles.
- Esquemas de entrada y salida.
- Ámbitos de permiso y roles autorizados.
- Límites de tasa, timeout y presupuesto.
- Versión, propietario lógico y auditoría.

### 8.2 Descubrimiento MCP

El MCP Host/Client del backend descubre herramientas y recursos MCP, valida sus metadatos y los registra en un catálogo interno. La descripción de una herramienta sirve para entender su función, pero no es una instrucción de sistema ni concede permisos.

Antes de invocar una herramienta:
1. Comprobar que el servidor está aprobado y habilitado.
2. Verificar que la herramienta está en allowlist.
3. Validar el JSON de entrada contra su esquema.
4. Comprobar permisos del usuario y del agente.
5. Aplicar timeout, rate limit y límites de recursos.
6. Ejecutar en el entorno aislado adecuado.
7. Validar la respuesta y normalizar errores.
8. Registrar llamada, resultado, duración y correlación.

### 8.3 Contrato interno de herramienta

```json
{
  "tool_id": "calendar.list_events",
  "connector_id": "calendar_main",
  "description": "Lista eventos autorizados del calendario",
  "input_schema": {},
  "output_schema": {},
  "risk_level": "read",
  "required_scopes": ["calendar.events.read"],
  "requires_approval": false,
  "timeout_ms": 10000
}
```

`risk_level` y `requires_approval` son metadatos de política del servidor, no valores que el conector remoto pueda rebajar.

### 8.4 Acciones sensibles

Lectura, escritura y acciones de impacto deben clasificarse. Para operaciones de escritura, borrado, publicación, cambios de configuración, acceso a archivos sensibles o efectos externos, exigir autorización explícita según la política. La aprobación debe mostrar:
- Qué herramienta se ejecutará.
- Qué recurso se modificará.
- Qué datos se enviarán.
- Qué efecto se espera.
- Qué permisos se usarán.
- Si la acción es reversible.
- Caducidad de la solicitud.

La aprobación es específica para una acción y sus parámetros. Cambiar parámetros invalida la aprobación anterior.

## 9. API del backend y eventos en tiempo real

### 9.1 Endpoints orientativos

| Método | Endpoint | Uso |
|---|---|---|
| POST | `/api/v1/chat/messages` | Enviar mensaje |
| GET | `/api/v1/chat/conversations` | Listar conversaciones |
| GET | `/api/v1/chat/conversations/{id}` | Obtener conversación |
| GET | `/api/v1/tasks` | Listar tareas |
| GET | `/api/v1/tasks/{id}` | Detalle de tarea |
| POST | `/api/v1/tasks/{id}/cancel` | Solicitar cancelación |
| GET | `/api/v1/agents` | Estado de agentes |
| GET | `/api/v1/connectors` | Catálogo/estado de conectores |
| POST | `/api/v1/approvals/{id}/decision` | Aprobar o rechazar |
| GET | `/api/v1/knowledge/search` | Buscar conocimiento autorizado |
| GET/PUT | `/api/v1/ui/layouts/{workspace}` | Leer/guardar layout |
| GET | `/api/v1/system/health` | Salud agregada del sistema |

Los endpoints son una propuesta inicial y deben consolidarse con la especificación del backend. Las respuestas deben usar DTOs versionados, paginación, errores normalizados e identificadores de correlación.

### 9.2 Transporte de eventos

Usar WebSocket cuando se necesite comunicación bidireccional frecuente; usar Server-Sent Events (SSE) cuando el flujo sea principalmente servidor-a-cliente. La elección debe ser uniforme por caso de uso y documentada.

Eventos orientativos:
- `chat.message.accepted`
- `assistant.status.changed`
- `task.created`
- `task.progress`
- `task.completed`
- `task.failed`
- `tool.call.started`
- `tool.call.completed`
- `approval.required`
- `connector.status.changed`
- `learning.ingestion.updated`
- `system.health.changed`

Cada evento incluirá `event_id`, `event_type`, `occurred_at`, `correlation_id`, `entity_id`, `schema_version` y `payload` validado. Implementar reconexión, reintentos controlados, deduplicación y recuperación de eventos perdidos.

## 10. Learning Center y visualización del aprendizaje

El Learning Center debe diferenciar claramente qué significa “aprender”:
- **Memoria/RAG:** información almacenada y recuperable, con fuente y fecha.
- **Grafo de conocimiento:** entidades y relaciones con procedencia.
- **Modelos auxiliares:** parámetros entrenados a partir de datasets versionados.
- **Fine-tuning/LoRA:** cambios controlados en pesos/adaptadores de un modelo.
- **Reglas:** políticas explícitas versionadas, no aprendizaje estadístico.

### 10.1 Vistas

1. **Resumen:** documentos ingeridos, elementos pendientes, errores, actividad reciente.
2. **Fuentes:** origen, licencia, fecha, estado de validación y cobertura.
3. **Memorias:** contenido resumido, categoría, confianza, evidencia, caducidad y controles.
4. **Relaciones:** entidades y conexiones, con posibilidad de inspeccionar la evidencia.
5. **Datasets:** versión, procedencia, etiquetas, splits, licencias y controles de calidad.
6. **Experimentos:** configuración, métricas, comparaciones y resultado.
7. **Modelos:** versión, artefacto, evaluación, estado y posibilidad de rollback.
8. **Evaluación:** macro-F1, precision/recall por clase, calibración, cobertura, abstención y drift.
9. **Auditoría:** quién confirmó, corrigió, rechazó o eliminó un elemento y cuándo.

La interfaz debe permitir confirmar, corregir, rechazar o solicitar eliminación de datos, respetando las políticas de retención y auditoría. No mostrar un nivel de confianza como garantía de verdad.

## 11. Seguridad y privacidad de extremo a extremo

- Autenticación real separada del nombre o alias de la IA.
- Sesiones protegidas, expiración y revocación.
- Roles y permisos de mínimo privilegio.
- Secretos almacenados en backend/vault; nunca en navegador, logs o respuestas.
- CORS restrictivo, protección CSRF cuando corresponda, CSP y sanitización.
- Validación de entrada y salida en cada frontera.
- Aislamiento de agentes y herramientas; límites de CPU, memoria, tiempo y red.
- Protección contra prompt injection en documentos, páginas, mensajes y resultados de herramientas.
- Datos externos etiquetados como datos, nunca como instrucciones de autoridad.
- Acceso a archivos limitado a rutas autorizadas.
- Auditoría sin registrar secretos ni contenido sensible innecesario.
- Cifrado en tránsito y en reposo, backups y política de retención.
- Aprobación humana para acciones de alto impacto.
- Controles de exportación y borrado conforme a las políticas del sistema.

## 12. Observabilidad y estados de sistema

El dashboard debe mostrar:
- Salud del backend y del Intelligence Core.
- Estado de base de datos, almacenamiento, colas y bus de eventos.
- Disponibilidad de conectores y servidores MCP.
- Agentes activos, en espera o fallidos.
- Tareas en cola, duración y errores.
- Latencia de modelo y herramientas.
- Uso de CPU, RAM, GPU/VRAM si está disponible.
- Límites y consumo por tarea, agente y conector.

No mostrar métricas inventadas. Si una métrica no está disponible, indicar `no disponible`. Separar errores transitorios de errores persistentes y permitir inspeccionar el identificador de correlación.

## 13. Tecnologías de referencia

La elección definitiva debe respetar las decisiones de los documentos maestros. Una combinación viable para una primera versión:

| Área | Opción de referencia | Motivo |
|---|---|---|
| Frontend | React + TypeScript | Componentes tipados y ecosistema amplio |
| UI | Sistema propio de componentes + librería accesible | Control del catálogo dinámico |
| Backend | Python + FastAPI | Encaja con servicios y modelos Python |
| Contratos | Pydantic + JSON Schema / OpenAPI | Validación y documentación |
| Tiempo real | SSE inicialmente; WebSocket si hace falta bidireccionalidad | Simplicidad y streaming |
| Persistencia | PostgreSQL + pgvector | Fuente de verdad y búsqueda vectorial |
| Eventos/colas | Redis Streams o alternativa durable | Desacoplar tareas y eventos |
| Archivos | Object storage compatible S3 o almacenamiento local controlado | Documentos y artefactos |
| Despliegue | Docker Compose en homelab | Servicios reproducibles |

Estas son recomendaciones, no decisiones irrevocables. Evitar añadir tecnologías sin una necesidad medida.

## 14. Organización de módulos propuesta

```text
nexus/
  frontend/
    src/
      app/
      pages/
      components/
        registry/
        data-display/
        chat/
        dashboards/
      features/
        tasks/
        agents/
        connectors/
        learning/
        settings/
      services/
      state/
      schemas/
  backend/
    api/
      routes/
      middleware/
      schemas/
      websocket/
    core/
      intelligence/
      planner/
      executor/
      verifier/
      tool_router/
    agents/
    connectors/
      gateway/
      rest/
      mcp/
    memory/
    knowledge/
    learning/
    policies/
    approvals/
    events/
    persistence/
    observability/
  shared/
    contracts/
    ui_schemas/
  infra/
    docker/
    migrations/
    monitoring/
  tests/
    contract/
    integration/
    security/
    frontend/
```

## 15. Fases de implementación

### Fase 1 — Base segura
- Backend API, autenticación y contratos.
- Marco web, navegación, chat básico.
- Persistencia de conversaciones.
- Registro de eventos y errores.
- Catálogo inicial de componentes estáticos.

### Fase 2 — Núcleo conectado
- Conexión con Intelligence Core.
- Streaming de estados del chat.
- Tareas y Agent Manager.
- Gateway REST y primer servidor MCP de solo lectura.
- Visualización de resultados tipados.

### Fase 3 — Interfaz dinámica
- UI Presentation Schema.
- Component Registry con validación.
- Tablas, métricas, gráficos, timelines y documentos.
- Personalización de layouts y perfiles.

### Fase 4 — Operación y control
- Conectores administrables.
- Aprobaciones y permisos granulares.
- Auditoría, límites, cancelación y recuperación.
- Dashboard de salud y observabilidad.

### Fase 5 — Learning Center
- Memoria/RAG y grafo.
- Ingesta y procedencia.
- Datasets, experimentos, evaluación y modelos.
- Visualización de calidad, drift y rollback.

## 16. Requisitos de aceptación

La interfaz se considerará lista para una versión inicial cuando:
1. Un usuario pueda conversar con NEXUS y recibir estados de procesamiento sin recargar la página.
2. Una tarea pueda pasar por planificación, ejecución, verificación y resultado visible.
3. Una API y un servidor MCP autorizados puedan devolver datos que se visualicen mediante componentes registrados.
4. Una respuesta externa con HTML/JS o un componente desconocido no pueda ejecutarse.
5. El usuario pueda reorganizar widgets y conservar su layout.
6. La interfaz muestre origen, hora y estado de los datos cuando proceda.
7. Una acción protegida exija aprobación y el backend vuelva a validar los permisos.
8. Un conector caído aparezca como no disponible sin bloquear el resto de la interfaz.
9. Los eventos duplicados o fuera de orden no corrompan el estado visual.
10. Los datos de aprendizaje puedan inspeccionarse con su fuente y evidencia.
11. Los errores tengan identificador de correlación y un mensaje comprensible.
12. Ningún secreto o credencial sea enviado al navegador.

## 17. Decisiones pendientes para cerrar la especificación

- Confirmar framework frontend y sistema visual.
- Confirmar si el primer despliegue será solo LAN o también acceso remoto.
- Definir autenticación local y gestión de perfiles.
- Elegir SSE o WebSocket para cada flujo.
- Definir el catálogo inicial de componentes dinámicos.
- Cerrar el contrato común de herramientas API/MCP.
- Establecer clasificación de riesgo y matriz de aprobaciones.
- Definir política de retención, exportación y borrado.
- Alinear endpoints y nombres de módulos con los otros documentos.

## 18. Resumen

NEXUS tendrá una interfaz web que actúa como **panel de control, espacio de conversación y ventana de observabilidad de una IA personal**. Será dinámica y personalizable, pero no ejecutará contenido arbitrario recibido de herramientas. Las API y MCP se conectarán exclusivamente a través de un Gateway en el backend; sus resultados se validarán, normalizarán y transformarán en contratos declarativos que el frontend representará mediante componentes seguros.

La interfaz permitirá entender qué está haciendo NEXUS, qué agentes y conectores intervienen, qué datos se han recuperado, qué resultados se han verificado y qué acciones requieren aprobación. El diseño debe mantener una separación estricta entre presentación, razonamiento, ejecución, memoria y políticas de seguridad.
