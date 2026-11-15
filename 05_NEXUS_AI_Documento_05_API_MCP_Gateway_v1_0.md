# NEXUS AI — Documento 05
## API, MCP y Gateway universal de conectores
**Versión:** 1.0 · **Fecha:** 15 de noviembre de 2026 · **Estado:** Especificación técnica propuesta

> **Relación con la documentación existente.** Desarrolla el `Tool & Connector Gateway`, MCP Host/Clients, herramientas tipadas, allowlists, scopes, API REST, webhooks y eventos descritos en `deep-research-report.md` y el Documento 04. La documentación original propone empezar con GitHub en modo solo lectura y centralizar las conexiones para que la interfaz nunca llame directamente a API/MCP.

---

## 1. Propósito

El **Gateway de conectores** es la frontera controlada entre NEXUS y sistemas externos o internos. Normaliza API REST, servidores MCP y webhooks detrás de un catálogo único de conectores y herramientas. El Intelligence Core y los agentes solicitan operaciones por identificador estable; el Gateway resuelve el conector, valida parámetros, comprueba scopes y riesgo, ejecuta la operación, normaliza el resultado y registra la trazabilidad.

La interfaz web no conoce credenciales ni llama directamente a integraciones privadas. El LLM tampoco recibe tokens de acceso. El único camino de ejecución será: Core/Agent → Tool Router → Policy Gate → Connector Gateway → API/MCP.

## 2. Objetivos y límites

- Una API interna uniforme para herramientas de diferentes proveedores.
- Registrar, descubrir, versionar y deshabilitar conectores.
- Admitir adaptadores REST, MCP y webhooks entrantes.
- Validar esquemas de entrada/salida y normalizar errores.
- Aplicar permisos mínimos por usuario, agente, conector, herramienta y recurso.
- Gestionar OAuth/credenciales en backend o vault.
- Exigir aprobación contextual para operaciones sensibles.
- Aislar servidores y ejecuciones con límites y observabilidad.
- Mantener compatibilidad mediante versiones de contrato.

No es objetivo del Gateway permitir que cualquier URL, shell command, servidor MCP o herramienta desconocida sea invocada libremente. Tampoco almacena lógica de planificación ni decide la respuesta conversacional: eso corresponde al Intelligence Core.

## 3. Principios de seguridad y diseño

1. **Una sola ruta de acceso.** Ningún acceso externo privado desde el frontend.
2. **Allowlist explícita.** Solo conectores y herramientas revisados y habilitados.
3. **Mínimo privilegio.** Scopes y credenciales separados por conector y finalidad.
4. **Esquemas estrictos.** Entradas y salidas se validan en cada frontera.
5. **Riesgo calculado por el backend.** El servidor remoto no puede rebajar `risk_level` ni eliminar la aprobación exigida por NEXUS.
6. **Salidas externas no confiables.** Se limpian/estructuran antes de reinyectarlas al modelo.
7. **Aprobación ligada a parámetros exactos.** Cambios invalidan la aprobación.
8. **Trazabilidad total.** Toda llamada tiene actor, herramienta, conector, duración, resultado y correlación.
9. **Despliegue aislado.** Los servidores MCP locales no reciben acceso irrestricto al host.
10. **Cambios de esquema revisables.** Una modificación de tool definition requiere nueva revisión.

## 4. Arquitectura del Gateway

```text
Intelligence Core / Agent Manager
              |
              v
           Tool Router
              |
              v
        Policy Enforcement
     (principal, scopes, risk)
              |
              v
      Connector Gateway API
              |
     +--------+---------+
     |        |         |
     v        v         v
 REST      MCP Host   Webhook Intake
 Adapter   / Client   (inbound events)
     |        |
     v        v
 API      MCP Servers
              |
              v
   Normalizer + Output Validator
              |
              v
      Tool Result Envelope
              |
      Core / Verifier / Memory

Connector Registry · Secret Store · Audit · Metrics
```

### 4.1 Módulos

| Módulo | Responsabilidad |
|---|---|
| Connector Registry | Configuración, tipo, propietario lógico, versión y estado |
| Tool Registry | Herramientas permitidas, schemas, hash, riesgo y scopes |
| MCP Host/Client | Descubrir y llamar herramientas/recursos MCP |
| REST Adapter | Adaptar endpoints HTTP a contratos internos |
| Webhook Intake | Recibir eventos autenticados y deduplicarlos |
| Credential Broker | Obtener token/secret sin exponerlo al LLM o frontend |
| Policy Enforcement | Comprobar usuario, agente, scopes, recurso y riesgo |
| Invocation Runtime | Ejecutar llamada con timeout, límites y cancelación |
| Schema Validator | Validar argumentos y resultados |
| Normalizer | Unificar formato y códigos de error |
| Audit & Telemetry | Guardar eventos y métricas sin secretos |

## 5. Modelo de un conector

Cada conector tendrá un registro independiente de sus herramientas. Campos lógicos mínimos:

| Campo | Descripción |
|---|---|
| `connector_id` | ID estable y único |
| `display_name` | Nombre visible en UI |
| `connector_type` | `rest`, `mcp_stdio`, `mcp_http`, `webhook`, `internal` |
| `publisher/source` | Quién mantiene el conector y de dónde se obtuvo |
| `environment` | local, homelab, remoto o sandbox |
| `endpoint_ref` | Referencia segura al endpoint; no credencial |
| `credential_ref` | Referencia al almacén de secretos, nunca el valor |
| `status` | draft, review, enabled, degraded, disabled, revoked |
| `protocol_version` | Versión de API/MCP cuando aplique |
| `connector_version` | Versión del adaptador de NEXUS |
| `approved_at/by` | Registro de revisión |
| `last_health_check` | Última comprobación |
| `rate_limits` | Límites por conexión |
| `timeout_policy` | Timeout de conexión y operación |
| `allowed_scopes` | Permisos máximos concedidos |
| `definition_hash` | Huella de la configuración revisada |

No guardar tokens en la tabla del conector. Solo `credential_ref` gestionado por un secret store o mecanismo protegido del entorno.

## 6. Catálogo de herramientas

Una herramienta representa una operación atómica invocable. Ejemplo: `github.repository.get`, `calendar.events.list`, `files.authorized.read`. Evitar nombres ambiguos como `run`, `execute` o `do_action`.

### 6.1 Tool manifest

```json
{
  "tool_id": "github.repository.get",
  "connector_id": "github_primary",
  "version": "1.0.0",
  "description": "Obtiene metadatos de un repositorio permitido",
  "input_schema_ref": "schemas/github.repository.get.input.v1.json",
  "output_schema_ref": "schemas/github.repository.get.output.v1.json",
  "risk_level": "read",
  "required_scopes": ["github.repository.read"],
  "resource_constraints": {"timeout_ms": 10000, "max_response_bytes": 200000},
  "idempotent": true,
  "requires_approval": false,
  "enabled": true,
  "definition_hash": "sha256:..."
}
```

Los valores son demostrativos, no configuran un conector real. El catálogo interno debe añadir el hash de definición revisada y el estado de aprobación.

### 6.2 Riesgo

| Nivel | Tipo de operación | Control mínimo |
|---|---|---|
| `read` | Lectura acotada | Scope de lectura y acceso al recurso |
| `write_reversible` | Cambios que pueden revertirse | Confirmación según regla y registro de antes/después |
| `write_external` | Enviar, publicar o modificar un sistema externo | Aprobación explícita con parámetros y destinatario/objeto |
| `destructive` | Borrado, revocación o cambio difícil de revertir | Aprobación reforzada, verificación de alcance y registro del resultado |
| `admin` | Cambiar configuración, permisos o conectores | Sesión administrativa reforzada; nunca disponible a agentes ordinarios |

El riesgo efectivo es el máximo entre clasificación local, regla aplicable y operación real. Una herramienta remota no puede declarar que una operación de escritura es de solo lectura.

## 7. Adaptadores REST

El adaptador REST traduce una herramienta interna a una solicitud HTTP concreta. Por herramienta se definen método, ruta fija o plantilla restringida, headers gestionados, input mapping, output mapping, timeout, política de reintentos, scopes y códigos esperados.

### 7.1 Reglas

- No aceptar URL arbitraria generada por el LLM.
- Hostnames, esquemas, puertos y rutas permitidas se registran en configuración.
- Evitar SSRF: bloquear loopback, link-local, metadata endpoints y rangos no autorizados según topología.
- No concatenar input en SQL, shell o paths.
- Usar parámetros y serializadores seguros.
- Validar tamaño y tipo MIME de la respuesta.
- No seguir redirecciones a destinos no permitidos.
- Separar credenciales por proveedor/conector.
- Aplicar rate limit y timeout.
- Normalizar paginación y cursores.

### 7.2 Autenticación

OAuth u otro mecanismo soportado se gestiona desde backend. El token se solicita con los scopes mínimos, se renueva y revoca de forma controlada, y nunca aparece en prompts ni logs. Las integraciones locales pueden usar credenciales del entorno, guardadas fuera del repositorio y con acceso restringido.

## 8. MCP Host / Client

MCP es una interfaz protocolaria para conectar aplicaciones cliente con servidores que exponen capacidades como tools y resources. NEXUS implementará el Host/Client del lado del backend; los agentes no abrirán conexiones MCP arbitrarias por su cuenta.

### 8.1 Descubrimiento y registro

1. El operador añade una definición de servidor con fuente, publisher, transporte, endpoint/command, entorno y permisos solicitados.
2. NEXUS muestra el origen, propósito y capacidades solicitadas antes de habilitarlo.
3. El servidor se inicia o conecta en sandbox.
4. El cliente negocia la versión/protocolo y descubre capabilities.
5. Solicita la lista de herramientas y recursos admitidos.
6. Valida schemas y metadata, calcula hash completo de definición y aplica revisión.
7. Registra herramientas en `Tool Registry` en estado `review`.
8. Un operador autorizado aprueba y habilita un conjunto limitado.
9. En cada invocación se vuelve a verificar definición, scopes y permisos.

No instalar un servidor MCP por una instrucción recibida en una página, documento, correo o mensaje. La instalación es una acción administrativa explícita.

### 8.2 Versión de protocolo

La documentación oficial consultada para esta especificación describe la revisión MCP `2026-07-28`. En esa revisión se detallan protocolo base JSON-RPC, negociación de versiones, patrones request/response y subscribe/notify, capacidades de servidor (tools/resources/prompts según necesidad) y autorización para transportes HTTP. NEXUS debe fijar la versión de protocolo y SDK que haya probado, registrar negociación y probar compatibilidad antes de actualizar. No debe asumir que una conexión o proceso equivale a una sesión de usuario o conversación.

### 8.3 Transportes

- **STDIO local:** adecuado para procesos MCP del homelab bajo supervisión. Los secretos se inyectan desde el entorno/vault; aislar proceso, filesystem y red.
- **HTTP remoto:** usar TLS y el perfil de autorización aplicable al transporte. Validar issuer, audience, expiración, scopes y recurso destino; no reenviar un token a otro servidor.
- **Otros transportes:** habilitar solo después de análisis de seguridad y compatibilidad.

### 8.4 Tools, resources y prompts

- **Tools:** operaciones invocables. Cada una se registra con schema, scopes, riesgo y aprobación.
- **Resources:** datos de contexto identificados por URI. La lectura se autoriza por recurso y objeto, se limita tamaño y se etiqueta como dato no confiable.
- **Prompts:** plantillas o contenido suministrado por servidor. No se consideran instrucciones de máxima autoridad y deben revisarse antes de incluirse en contexto.

La interfaz puede mostrar capacidades disponibles y sus permisos. La existencia de una herramienta descubierta no significa que esté habilitada para el Core.

### 8.5 Hash y cambios de definición

Guardar hash de tool definition completa: nombre, descripción, input schema, output schema y annotations relevantes. Si cambia, suspender o poner en revisión según política, comparar el diff y exigir nueva aprobación antes de usarla. No confiar solo en la descripción textual o en flags declarados por el servidor.

## 9. Webhooks y eventos entrantes

Los webhooks son una entrada, no una autorización para ejecutar cualquier plan. El endpoint de recepción debe verificar firma/secret, timestamp, replay protection, tamaño, tipo de evento y origen. Cada evento se deduplica con ID externo y se convierte en un `InboundEvent` tipado.

El evento puede crear una tarea o actualizar una fuente, pero pasa por clasificación, reglas y límites del Core. Un webhook malicioso no puede modificar identidad, reglas ni scopes.

## 10. Flujo de invocación de una herramienta

1. El Planner incluye `tool_id` y argumentos propuestos.
2. Plan Validator valida el schema local.
3. Policy Engine verifica el principal, agente, recurso y scope.
4. El Gateway resuelve una definición habilitada y comprueba su hash.
5. Se calcula el riesgo y se decide si requiere aprobación.
6. Si requiere aprobación, se crea un request que liga acción, destino y hash de argumentos.
7. Tras la aprobación, el backend vuelve a comprobar permisos, caducidad y que los argumentos no hayan cambiado.
8. Credential Broker obtiene el secreto del conector.
9. Invocation Runtime ejecuta con timeout, rate limit, límites de respuesta e idempotency key.
10. Output Validator valida respuesta, tipo, tamaño y campos permitidos.
11. Normalizer crea `ToolResult` con estado, datos y evidencia.
12. Audit registra la invocación sin secretos.
13. Verifier del Core evalúa el resultado antes de usarlo o presentarlo.

## 11. Aprobaciones y consentimiento

La aprobación pertenece al usuario/propietario autenticado y debe ser específica. Mostrar en la interfaz:

- herramienta y conector;
- acción exacta y recurso objetivo;
- parámetros significativos y destinatario cuando aplique;
- datos que se enviarán;
- efecto esperado y posibilidad de reversión;
- scopes concedidos;
- expiración de la aprobación.

La aprobación guarda `approval_id`, principal, task/step, tool, connector, `arguments_hash`, scope, decisión, timestamp, expiración y correlación. Si cambia cualquier parámetro, se invalida. Una aprobación antigua no autoriza una llamada diferente.

## 12. Contrato común de invocación y respuesta

### 12.1 ToolInvocation

```json
{
  "invocation_id": "inv_01J...",
  "correlation_id": "corr_01J...",
  "task_id": "task_01J...",
  "step_id": "step_1",
  "principal": {"type": "owner_session", "ref": "session_ref"},
  "agent_id": "github_agent",
  "tool_id": "github.repository.get",
  "arguments": {"repository_ref": "repo_allowed_123"},
  "idempotency_key": "idem_...",
  "deadline": "2026-11-15T13:30:00Z"
}
```

### 12.2 ToolResult

```json
{
  "invocation_id": "inv_01J...",
  "status": "succeeded",
  "data": {"repository_name": "example", "default_branch": "main"},
  "evidence": [{"source_ref": "provider-object-ref", "retrieved_at": "2026-11-15T13:25:00Z"}],
  "error": null,
  "duration_ms": 420,
  "schema_version": "1.0",
  "correlation_id": "corr_01J..."
}
```

Los ejemplos usan valores ficticios. La respuesta del Gateway debe separar `data`, `evidence`, `warnings`, `error` y `metadata`; no devolver headers de autenticación ni configuración interna.

## 13. API Backend de NEXUS relacionada con conectores

Las rutas son propuesta inicial y se consolidarán con el Documento 04. La administración del Gateway debe ir en endpoints protegidos.

| Método | Ruta | Función |
|---|---|---|
| `GET` | `/api/v1/connectors` | Listar conectores visibles para el usuario |
| `GET` | `/api/v1/connectors/{id}` | Detalle, estado y permisos resumidos |
| `POST` | `/api/v1/connectors` | Crear definición en estado draft/review |
| `POST` | `/api/v1/connectors/{id}/test` | Comprobar conexión sin ejecutar operaciones de negocio |
| `POST` | `/api/v1/connectors/{id}/enable` | Habilitar tras revisión autorizada |
| `POST` | `/api/v1/connectors/{id}/disable` | Deshabilitar conexión |
| `POST` | `/api/v1/connectors/{id}/revoke` | Revocar credenciales/scopes |
| `GET` | `/api/v1/connectors/{id}/tools` | Ver herramientas y versión/hash |
| `POST` | `/api/v1/connectors/{id}/tools/{tool_id}/review` | Aprobar/rechazar definición |
| `GET` | `/api/v1/tool-executions` | Historial filtrado por permisos |
| `GET` | `/api/v1/tool-executions/{id}` | Detalle seguro de ejecución |
| `POST` | `/api/v1/approvals/{id}/decision` | Aprobar/rechazar acción concreta |

La ruta para invocar herramientas no debe ser un endpoint abierto a cualquier usuario de frontend. Normalmente el Core llama al servicio interno del Gateway con un principal de servicio y contexto de autorización validado.

## 14. Errores normalizados

| Código | Descripción | ¿Reintentar? |
|---|---|---|
| `CONNECTOR_NOT_FOUND` | Conector no registrado | No |
| `CONNECTOR_DISABLED` | Conector desactivado | No |
| `CONNECTOR_UNAVAILABLE` | Servicio no disponible | Sí, si operación segura/idempotente |
| `AUTH_REQUIRED` | Falta autenticación | Tras reconectar |
| `AUTH_EXPIRED` | Credencial caducada | Tras renovación segura |
| `SCOPE_MISSING` | Permiso insuficiente | No, requiere concesión explícita |
| `TOOL_NOT_ALLOWED` | Herramienta fuera de allowlist | No |
| `TOOL_DEFINITION_CHANGED` | Hash o schema distinto | No, requiere revisión |
| `INPUT_INVALID` | Argumentos no válidos | No, corregir plan |
| `OUTPUT_INVALID` | Respuesta no cumple contrato | No automático; alertar |
| `APPROVAL_REQUIRED` | Falta aprobación | Tras decisión humana |
| `APPROVAL_EXPIRED` | Aprobación caducada | Nueva aprobación |
| `RATE_LIMITED` | Límite de tasa | Backoff acotado |
| `TIMEOUT` | Tiempo agotado | Según idempotencia |
| `RESOURCE_FORBIDDEN` | Recurso fuera de ámbito | No |
| `RESPONSE_TOO_LARGE` | Salida excede límite | Ajustar petición o paginar |
| `POLICY_DENIED` | Regla/política denegó la operación | No |
| `INTERNAL_ERROR` | Fallo no clasificado | Solo con diagnóstico |

Todos los errores tienen `error_id`, timestamp, correlation ID, componente y mensaje seguro. Los detalles internos se reservan para logs protegidos.

## 15. Eventos y sincronización

Eventos orientativos: `connector.created`, `connector.enabled`, `connector.disabled`, `connector.health.changed`, `tool.definition.discovered`, `tool.definition.changed`, `tool.invocation.started`, `tool.invocation.completed`, `tool.invocation.failed`, `approval.required`, `approval.decided`, `webhook.received`, `sync.started`, `sync.progress`, `sync.completed`.

Formato mínimo: `event_id`, `event_type`, `occurred_at`, `correlation_id`, `connector_id`, `entity_id`, `schema_version`, `payload`. Para eventos durables se recomienda cola/stream persistente con reintentos y dead-letter queue. Redis Pub/Sub puede servir para señales efímeras, pero no debe ser el único registro de operaciones que necesitan recuperación.

## 16. Rate limits, caché y consistencia

- Límites por conector, herramienta, usuario y agente.
- Timeout de conexión y ejecución separado.
- Caché solo para datos seguros, con TTL y estrategia de invalidación conocida.
- No cachear respuestas privadas entre usuarios/sesiones.
- Respetar paginación y cuotas de proveedor.
- Usar `ETag`/versiones cuando el proveedor lo permita.
- Mantener estado de sincronización y cursor para reanudar.
- No interpretar un webhook duplicado como dos acciones distintas.
- Para escrituras, usar idempotency key o estrategia de reconciliación.

## 17. Sandbox y seguridad de servidores MCP

Los servidores locales se ejecutarán con usuario no privilegiado, filesystem mínimo, red limitada, recursos y duración acotados. Los servidores remotos se autentican y se limitan a destinos configurados. Revisión de origen, dependencias, comando, publisher, schemas y capacidades antes de habilitar.

Tratar descripción de tool, input schema, output schema, resources, prompts y resultados como superficie potencial de inyección. Aplicar hash/pinning de definiciones y revisión de cambios. Validar entrada y salida. Evitar rutas arbitrarias, URLs arbitrarias, SSRF, SQL/command injection y respuestas de tamaño ilimitado. Las respuestas de herramienta se etiquetan como datos no confiables en el contexto del modelo.

## 18. Observabilidad y auditoría

Registrar como mínimo: connector_id, tool_id, versión/hash, actor/principal, agente, task/step, scopes relevantes (sin tokens), recurso lógico, argumentos redactados/hash, resultado, duración, error, retry count, approval_id y correlation_id.

Métricas: disponibilidad; latencia p50/p95; tasa de error; llamadas por herramienta; cuota; rechazos de política; cambios de definición; aprobaciones; fallos de autenticación; timeout; volumen de payload y retraso de sync.

No guardar access tokens, refresh tokens, claves, cookies, secretos ni headers completos. Los argumentos pueden incluir PII; aplicar redacción y retención.

## 19. Pruebas

**Contrato:** schemas válidos/ inválidos, campos extra, cambios incompatibles, tipos nulos, tamaño máximo y versionado.

**Autorización:** usuario sin scope, agente sin herramienta, recurso ajeno, credencial de conector A enviada a B, token expirado, aprobación con argumentos alterados.

**MCP:** cambio de tool definition/hash; tool desconocida; servidor caído; resources URI no autorizado; resultados malformados; capabilities no soportadas; versión incompatible.

**REST:** redirección a host no permitido, URL arbitraria, SSRF, paginación, rate limit, timeout, respuesta grande, JSON inválido y error del proveedor.

**Webhooks:** firma inválida, replay, duplicados, timestamp fuera de ventana, payload excesivo y evento no registrado.

**Operación:** deshabilitar y revocar; rotación de credencial; backup de catálogo; restaurar conectores; dead-letter y reintentos.

## 20. Fases de implementación

**G0 — Registro base:** Connector Registry y Tool Registry, definición tipada y estados.

**G1 — REST readonly:** primer adaptador para una API simple, scopes mínimos, schemas y resultados normalizados.

**G2 — MCP readonly:** MCP Host/Client, descubrimiento y revisión de tools/resources, hash de definición y sandbox. GitHub readonly se mantiene como candidato inicial de la documentación.

**G3 — Seguridad operativa:** secret store, auditoría, health, rate limits, revocación y alertas.

**G4 — Webhooks y eventos:** recepción autenticada, deduplicación, cola durable y tareas del Core.

**G5 — Acciones de escritura:** aprobación contextual, idempotencia, confirmación remota y pruebas de recuperación.

**G6 — Catálogo ampliado:** nuevos conectores (correo, calendario, YouTube u otros) conforme a casos de uso y permisos revisados.

## 21. Criterios de aceptación

1. El frontend no contiene tokens ni llama directamente a API/MCP privadas.
2. Toda herramienta invocable figura en Tool Registry.
3. Todo conector tiene origen, estado, permisos y definición versionada.
4. Una herramienta no aprobada o cuyo hash cambió no se ejecuta.
5. Inputs y outputs se validan con esquemas estrictos.
6. El LLM nunca recibe credenciales ni decide scopes.
7. Los permisos se verifican en el momento de la invocación.
8. Una aprobación queda ligada a la acción y al hash de parámetros.
9. El Gateway normaliza errores y resultados.
10. Los reintentos respetan idempotencia y riesgo.
11. Los servidores locales se ejecutan aislados y con recursos limitados.
12. Webhooks autenticados y duplicados se controlan.
13. Cada llamada puede rastrearse por correlation ID.
14. Las salidas externas no pueden ejecutar código ni modificar reglas.
15. El sistema puede deshabilitar/revocar un conector sin desplegar el frontend.

## 22. Decisiones pendientes

- Versiones de protocolo MCP y SDK exactas que se fijarán tras pruebas en Windows/Docker.
- Política de transporte por conector: STDIO local o HTTP remoto.
- Secret store elegido para homelab y procedimiento de backup de claves.
- Motor de colas: Redis Streams u opción durable alternativa.
- Modelo de permisos: scopes por herramienta y recurso; matriz de roles definitiva.
- Política de revisión de publisher y dependencias de servidores MCP.
- Catálogo MVP de herramientas y límites cuantitativos.
- Diseño de webhooks y estrategia de reconciliación por proveedor.

## 23. Referencias técnicas

- Documentación original del proyecto: `deep-research-report.md`, apartados de ingesta, agentes, reglas y MCP.
- `NEXUS_AI_Documento_04_Interfaz_y_Conectividad_v1_0.md`, apartados 8 y 9.
- Model Context Protocol, especificación 2026-07-28: https://github.com/modelcontextprotocol/modelcontextprotocol/tree/main/docs/specification/2026-07-28
- MCP, Tools: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/tools.mdx
- MCP, Authorization: https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/authorization/index.mdx
- OWASP MCP Security Cheat Sheet: https://cheatsheetseries.owasp.org/cheatsheets/MCP_Security_Cheat_Sheet.html
- OWASP MCP Security Testing Guide: https://github.com/OWASP/MCP-Security-Testing-Guide

La selección de versiones de SDK y transportes debe revisarse antes de implementar, ya que la especificación MCP evoluciona.

## 24. Resumen

El Gateway será el único camino de NEXUS hacia sistemas externos. El catálogo de conectores y herramientas definirá exactamente qué puede invocarse; los schemas controlarán datos; las políticas decidirán quién puede hacerlo; la aprobación humana cubrirá operaciones sensibles; y la auditoría permitirá conocer qué ocurrió. API REST, MCP y webhooks compartirán envelopes y controles comunes, pero mantendrán adaptadores específicos de cada protocolo.
