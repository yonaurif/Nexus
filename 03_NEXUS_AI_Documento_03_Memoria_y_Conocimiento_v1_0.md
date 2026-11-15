# NEXUS AI — Documento 03
## Memoria, conocimiento y almacenamiento persistente
**Versión:** 1.0 · **Fecha:** 15 de noviembre de 2026 · **Estado:** Especificación técnica propuesta

> **Relación con la documentación existente.** Desarrolla la sección “Memoria y Grafo de Conocimiento” de `deep-research-report.md` y el capítulo “Almacenamiento del cerebro textual” de `NEXUS Text Learning v1`. Mantiene PostgreSQL + pgvector como almacenamiento inicial, las memorias episódica/semántica/procedimental y el uso de relaciones SQL antes de introducir Neo4j. Se alinea con el Core del Documento 02 y con los resultados de API/MCP del Documento 05.

---

## 1. Propósito

La memoria de NEXUS es el sistema persistente que permite conservar experiencias, recuperar información, relacionar entidades y proporcionar contexto verificable al Intelligence Core. No es una carpeta de texto ni un prompt permanente: es un conjunto de servicios y estructuras con tipos, permisos, procedencia, vigencia, estado de validación y mecanismos de recuperación y olvido.

La memoria debe permitir que NEXUS recuerde interacciones útiles, conozca los proyectos y sistemas autorizados, encuentre documentación actualizada y recupere procedimientos aprobados, manteniendo separados los datos externos, las preferencias del propietario y las reglas protegidas.

## 2. Principios y decisiones base

1. **PostgreSQL como fuente de verdad** para metadatos, relaciones, estados, memoria y auditoría.
2. **pgvector** como extensión de recuperación semántica; la dimensión y el modelo embedding se fijarán por perfil de índice.
3. **Grafo relacional inicial.** Entidades y relaciones se almacenan en tablas SQL; Neo4j solo se incorpora si consultas y volumen lo justifican.
4. **Memoria tipada.** Episódica, semántica, procedimental y de trabajo tienen ciclos y permisos distintos.
5. **RAG no es entrenamiento.** Indexar un documento no modifica los pesos del LLM.
6. **Procedencia obligatoria.** Los hechos recuperables deben enlazar con fuente, fecha y transformación.
7. **Datos externos no son autoridad.** Nunca modifican identidad, permisos ni reglas fundamentales.
8. **Persistencia independiente del LLM.** Cambiar de modelo no debe perder las memorias.
9. **Privacidad y minimización.** Solo se guarda lo necesario y accesible a los actores autorizados.
10. **Corrección y olvido.** El propietario puede corregir, rechazar o solicitar eliminación de datos, con trazabilidad adecuada.

## 3. Tipos de memoria

### 3.1 Memoria episódica — qué ocurrió

Registra eventos e interacciones concretas: mensaje recibido, tarea ejecutada, resultado de herramienta, modificación de un proyecto, feedback, sincronización o cambio relevante. La investigación original la describe como bitácora/event store y propone que sea append-only.

Cada episodio incluye `episode_id`, timestamp, actor, tipo de evento, contexto mínimo, resultado, estado, fuente, sensibilidad, ámbito de acceso y correlación. Las correcciones no reescriben silenciosamente un episodio: crean un evento de corrección/supersesión o cambian un estado administrativo con auditoría.

### 3.2 Memoria semántica — qué sabe NEXUS

Almacena hechos sobre entidades y relaciones: proyectos, repositorios, tecnologías, canales, servicios, documentos y sus conexiones. Ejemplos de relaciones descritas en la fuente: usuario gestiona GitHub; proyecto usa Python; proyecto está documentado en un portfolio; proyecto depende de un servicio.

Un hecho debe incluir sujeto, predicado, objeto/valor, fuente/evidencia, fecha de observación, vigencia, confianza, estado de confirmación y ámbito. Una inferencia desde un `requirements.txt` puede comenzar como `suggested/unconfirmed`; no debe mostrarse como hecho confirmado hasta su validación según política.

### 3.3 Memoria procedimental — cómo se hace

Conserva procedimientos aprobados, flujos de trabajo, precondiciones y referencias a implementaciones versionadas. La documentación original la plantea como rutinas o secuencias de herramientas. Para seguridad, la memoria no ejecutará scripts libres guardados como texto: almacenará la especificación del procedimiento y una referencia a código versionado, revisado y desplegado en el repositorio de la aplicación.

Un procedimiento debe declarar objetivo, versión, pasos, herramientas requeridas, parámetros, permisos, riesgos, aprobaciones, precondiciones, postcondiciones, pruebas y propietario lógico.

### 3.4 Memoria de trabajo — contexto temporal

Es el estado efímero necesario para la conversación o tarea actual: resumen de turnos, variables de plan, IDs de ejecuciones y resultados parciales. Tiene TTL, no se convierte automáticamente en recuerdo a largo plazo y debe poder reconstruirse desde los registros persistentes cuando proceda.

### 3.5 Almacenes separados que no deben confundirse con memoria

- **Identidad y perfil:** datos estables de NEXUS y del propietario autenticado.
- **Reglas y permisos:** políticas explícitas versionadas y protegidas.
- **Índices RAG:** representación recuperable de documentos y chunks; su contenido conserva el vínculo a la fuente.
- **Datasets y modelos:** ámbito del Learning Engine, con versionado y aprobaciones propias.

Estas áreas pueden residir en PostgreSQL, pero deben tener tablas, servicios y controles diferenciados. Ninguna inferencia estadística podrá cambiar identidad o reglas.

## 4. Arquitectura de almacenamiento

```text
Fuentes autorizadas (chat, archivos, API, MCP)
                 |
                 v
          Ingestion Gateway
                 |
   procedencia / permisos / clasificación
                 |
                 v
       Staging + validación + dedupe
                 |
      +----------+-----------+
      |                      |
      v                      v
 Episodios / fuentes     Documentos y chunks
      |                      |
      v                      v
 Consolidación       Embeddings + FTS index
      |                      |
      v                      |
 Hechos / entidades / relaciones
      |                      |
      +----------+-----------+
                 |
                 v
        PostgreSQL + pgvector
                 |
                 v
       Memory & Knowledge API
                 |
                 v
 Context Builder del Intelligence Core
```

### 4.1 Componentes

| Componente | Función |
|---|---|
| Ingestion Gateway | Recibe datos de conectores y servicios internos |
| Source Registry | Registra origen, autorización, tipo y política de sincronización |
| Staging | Conserva temporalmente datos antes de validación |
| Sanitizer | Detecta secretos/PII, normaliza y clasifica sensibilidad |
| Deduplicator | Hash exacto y similitud aproximada |
| Document Processor | Extrae texto y metadatos, segmenta documentos |
| Embedding Service | Genera vectores con modelo versionado |
| Episode Store | Registra eventos de forma auditable |
| Knowledge Extractor | Propone entidades, hechos y relaciones |
| Memory API | Ofrece crear, consultar, corregir y olvidar mediante permisos |
| Retrieval Service | Búsqueda híbrida y filtrada |
| Retention Service | TTL, caducidad, eliminación y limpieza de índices |

## 5. Ciclo de vida de un dato

1. **Captura:** procede de chat, fuente local autorizada o conector aprobado.
2. **Registro de fuente:** identifica propietario, endpoint/origen, permisos, licencia, fecha y método de acceso.
3. **Staging:** guarda referencia temporal para revisión, sin hacerlo recuperable como conocimiento confirmado.
4. **Clasificación:** determina tipo de dato, sensibilidad, idioma y ámbito de acceso.
5. **Sanitización:** detecta secretos y datos personales; excluye, redacta o cifra según la política.
6. **Normalización:** Unicode, codificación, formato y metadatos sin destruir el contenido original relevante.
7. **Deduplicación:** usa hashes y detección de casi duplicados con trazabilidad.
8. **Extracción:** texto, chunks, entidades y relaciones propuestas.
9. **Indexación:** texto completo y embeddings asociados a una versión de modelo.
10. **Publicación interna:** el dato pasa al estado correspondiente (`active`, `suggested`, `needs_review`, etc.).
11. **Recuperación:** solo para actores y tareas autorizados, con filtros antes del ranking.
12. **Consolidación:** episodios repetidos pueden producir una propuesta semántica, nunca autoridad automática.
13. **Mantenimiento:** sincronización, actualización, caducidad, corrección y eliminación.

## 6. Procedencia, confianza y estado

Cada elemento recuperable debe llevar como mínimo: `source_id`, `source_ref`, `source_type`, `observed_at`, `ingested_at`, `transform_version`, `owner_scope`, `sensitivity`, `trust_class`, `review_status` y `validity`.

### 6.1 Estados recomendados

| Estado | Significado | Uso en respuestas |
|---|---|---|
| `staged` | Capturado, aún no validado | No usar como hecho salvo inspección explícita |
| `active` | Validado técnicamente y permitido | Puede recuperarse respetando permisos |
| `suggested` | Inferencia pendiente de confirmación | Presentar como sugerencia, no certeza |
| `confirmed` | Confirmado por propietario o fuente autorizada | Puede afirmarse con evidencia y vigencia |
| `rejected` | El propietario rechazó la inferencia | Excluir de respuestas normales y de entrenamiento salvo uso auditado |
| `superseded` | Reemplazado por información posterior | Mantener historial si la política lo permite |
| `expired` | Superó vigencia o TTL | No usar como estado actual |
| `deleted` | Eliminación lógica/auditada | No recuperar; ejecutar eliminación física derivada según política |

La confianza es una señal cuantitativa o cualitativa, no una garantía de verdad. No debe reemplazar la procedencia ni la confirmación.

## 7. Modelo de datos lógico

Los nombres son propuestas de esquema; se deberán consolidar mediante migraciones Alembic. Las claves principales pueden ser UUID/ULID. Todas las tablas con datos de usuario incluyen `owner_id` o scope equivalente y timestamps de auditoría.

### 7.1 Fuentes y documentos

| Tabla | Campos principales | Índices/relaciones |
|---|---|---|
| `memory_sources` | id, owner_id, source_type, display_name, uri_ref, auth_ref, permission_scope, license, status, sync_policy, created_at | owner/status; no guardar secreto en `auth_ref` |
| `source_versions` | id, source_id, external_version, content_hash, observed_at, ingested_at, metadata | source_id + version/hash |
| `documents` | id, source_id, source_version_id, title, mime_type, language, sensitivity, visibility, status, content_ref, content_hash | source, hash, FTS |
| `document_chunks` | id, document_id, chunk_index, text_ref/text, token_count, offsets, metadata, status | document_id + chunk_index |
| `embedding_profiles` | id, provider, model_name, model_version, dimensions, normalization, language_scope, active | nombre/versión únicos |
| `chunk_embeddings` | chunk_id, profile_id, embedding, created_at | HNSW/IVF según benchmark; profile + chunk |

`content_ref` puede apuntar a un objeto cifrado en almacenamiento de archivos cuando el cuerpo no deba vivir directamente en una fila. No almacenar modelos grandes ni artefactos binarios de entrenamiento dentro de PostgreSQL.

### 7.2 Memoria episódica

| Tabla | Campos principales | Regla |
|---|---|---|
| `memory_episodes` | id, owner_id, conversation_id, task_id, event_type, actor_type, actor_id, occurred_at, recorded_at, summary, payload_ref, sensitivity, visibility, source_id, correlation_id, status | Registro append-only para hechos de ejecución |
| `episode_embeddings` | episode_id, profile_id, embedding | Índice vectorial para búsqueda semántica |
| `episode_links` | from_episode_id, to_episode_id, relation_type | Relaciona causas, correcciones y secuencias |

Payloads sensibles pueden guardarse cifrados o como referencia a objeto con control de acceso. Evitar duplicar contenido de correo/documento completo en episodios si basta un resumen y un `source_ref`.

### 7.3 Memoria semántica y grafo

| Tabla | Campos principales | Regla |
|---|---|---|
| `entities` | id, owner_id, entity_type, canonical_name, description, visibility, status, created_at, updated_at | Identidad semántica del nodo |
| `entity_aliases` | id, entity_id, alias, source_id, confidence | Nombre alternativo con origen |
| `facts` | id, owner_id, subject_entity_id, predicate, object_entity_id o object_value, value_type, status, confidence, valid_from, valid_to, recorded_at, supersedes_fact_id | Hecho atómico y temporal |
| `fact_evidence` | id, fact_id, source_id, document_id, chunk_id, episode_id, quote_ref, evidence_role | Enlaza hecho con evidencia |
| `relations` | id, subject_entity_id, predicate, object_entity_id, fact_id, status, confidence | Arista del grafo relacional |
| `knowledge_conflicts` | id, fact_a_id, fact_b_id, conflict_type, status, resolution_ref | Contradicciones no resueltas |

No crear una entidad por cada mención sin deduplicación. Las entidades pueden fusionarse mediante una operación auditada, conservando aliases y enlaces de evidencia. Las relaciones tienen dirección, tipo y, cuando proceda, validez temporal.

### 7.4 Memoria procedimental

`procedures`: id, name, description, version, status, owner_scope, preconditions, postconditions, steps_schema, tool_refs, required_scopes, risk_level, approval_policy, implementation_ref, test_suite_ref, created_by, reviewed_at.

El campo `implementation_ref` apunta a código firmado/versionado y desplegado por el proceso de desarrollo. La memoria no ejecuta texto de scripts. Los pasos referencian `tool_id` declarados en el Gateway.

### 7.5 Identidad, reglas y learning

`identity`, `owner_profile`, `rules`, `rule_versions`, `permissions`, `datasets`, `training_examples`, `dataset_versions`, `training_runs`, `evaluation_runs` y `model_registry` se tratan como dominios separados. El esquema exacto de aprendizaje ya está descrito en `NEXUS Text Learning v1`; este documento no duplica su modelo de entrenamiento.

## 8. Estrategia vectorial y búsqueda híbrida

### 8.1 Embeddings

El modelo de embeddings no está fijado. La documentación original menciona `all-MiniLM-L6-v2` como candidato local de 384 dimensiones y alternativas vía API, pero no debe adoptarse un proveedor externo sin decisión expresa. Se recomienda empezar probando un encoder local adecuado para español y comparar calidad, memoria, latencia y licencia.

Cada embedding se vincula a `embedding_profile`: nombre, versión, dimensión, normalización, idioma, fecha y hash del artefacto. No mezclar vectores generados por modelos/dimensiones incompatibles. Si cambia el modelo, crear perfil nuevo, reindexar de forma gradual y mantener el anterior durante migración.

### 8.2 Chunking

Segmentar por límites semánticos (títulos, párrafos, secciones, bloques de código) y respetar el tokenizador del modelo de embedding. Guardar índice, offsets y vínculo al documento. No aplicar un tamaño único a PDF, correo, README, código y conversación. Conservar metadatos suficientes para reconstruir el contexto y citar la sección original.

### 8.3 Búsqueda híbrida

El Retrieval Service combinará:
- filtros SQL previos: propietario, permisos, fuente, sensibilidad, estado y vigencia;
- búsqueda textual (PostgreSQL full-text search/BM25 compatible o componente equivalente);
- búsqueda vectorial pgvector;
- fusión de rankings (por ejemplo Reciprocal Rank Fusion) y reranking opcional;
- diversidad por fuente/documento para evitar que una sola fuente domine;
- límite de chunks y deduplicación de resultados.

La similitud vectorial no debe utilizarse como filtro de autorización. Primero se limita el universo accesible y luego se clasifica por relevancia.

### 8.4 Respuesta con evidencia

Un resultado RAG debe devolver contenido, `document_id`, `chunk_id`, fuente, versión, ubicación/página si se conoce, timestamp, estado y score de recuperación. La respuesta final puede mostrar citas o referencias. Si no existe evidencia suficiente, NEXUS debe reconocerlo.

## 9. Consultas al grafo y resolución de contradicciones

El grafo relacional inicial permitirá consultas de uno a varios saltos con límites de profundidad. Ejemplos: proyectos que usan Python; repositorios asociados a un proyecto; servicios de los que depende un proyecto; documentos que respaldan una relación.

### 9.1 Temporalidad

Distinguir:
- `observed_at`: cuándo se observó;
- `recorded_at`: cuándo NEXUS lo almacenó;
- `valid_from`/`valid_to`: período durante el que el hecho es válido según evidencia.

Esto permite decir que una dependencia existía en una versión anterior y fue reemplazada después.

### 9.2 Contradicciones

No resolver conflictos solo por “último texto visto”. Comparar autoridad de fuente, fecha, objeto, alcance y tipo de hecho. Mantener ambos registros con vínculo de conflicto hasta resolver. La política de precedencia debe ser específica por dominio (p. ej., fuente conectada oficial frente a inferencia de un documento antiguo). Los conflictos de identidad y reglas se gestionan fuera del conocimiento semántico.

## 10. Consolidación episódica a semántica

Un proceso separado puede identificar episodios repetidos y sugerir hechos o patrones, por ejemplo una dependencia observada en varios repositorios. Cada propuesta incluirá evidencia y la transformación que la generó.

El ciclo será: detectar candidatos → extraer entidades/hechos → resolver duplicados → buscar conflictos → calcular confianza → crear `suggested` → revisión automática de seguridad → confirmar por fuente o propietario según el tipo. No se convertirán preferencias, datos personales sensibles ni patrones inferidos en memoria confirmada sin una base adecuada y la aprobación requerida.

## 11. Seguridad y privacidad

- Segmentar por `owner_id`, ámbito y visibilidad.
- Aplicar autorización antes de retrieval, no solo al representar la respuesta.
- Tratar documentos, correo, páginas, repositorios y resultados MCP como datos no confiables.
- Escanear secretos y PII en captura, staging, indexado, exportación y logs.
- Cifrar en tránsito y reposo; cifrado por campo u objeto para categorías sensibles.
- Separar referencias a credenciales del contenido de memoria; no guardar tokens API en episodios.
- Limitar acceso de cada agente a colecciones/ámbitos necesarios.
- No convertir texto en scripts ejecutables.
- Guardar acceso/auditoría sin duplicar datos sensibles.
- Definir retención por tipo y por fuente, no una política universal.

## 12. Corrección, olvido y eliminación

La eliminación debe propagarse a todos los derivados identificables: registro lógico, documentos, chunks, vectores, hechos, relaciones, cachés, resúmenes derivados y objetos. Para datos ligados a una fuente externa, definir si se elimina, se marca como no vigente o se conserva un registro mínimo de auditoría conforme a la política.

Un borrado criptográfico puede ayudar cuando los datos se cifran con claves por ámbito/objeto, pero no sustituye por sí solo la comprobación de todos los índices y copias. El proceso debe registrar solicitud, alcance, resultado y excepciones por backups/retención. Tras borrar, reconstruir o depurar índices vectoriales y full-text afectados.

La interfaz debe permitir: inspeccionar elemento; ver fuente y derivados; corregir; rechazar; olvidar; consultar estado de solicitud. El olvido no debe ser solo un botón que oculte el registro.

## 13. Retención, backups y recuperación

- Política distinta para conversación, episodio, documentos externos, memoria semántica, auditoría y datasets.
- TTL para memoria de trabajo y cachés.
- Historial de versiones para documentos cuando el origen lo soporte.
- Backups cifrados de PostgreSQL y objetos con retención definida.
- Pruebas periódicas de restauración en entorno aislado.
- Migraciones versionadas y reversibles cuando sea posible.
- Reindexación vectorial reproducible desde documentos/chunks y perfil embedding.
- Plan para coherencia entre DB y object storage (subidas temporales, confirmación y limpieza de huérfanos).

## 14. API interna de Memory & Knowledge

El Core y los agentes no deben construir SQL sobre tablas de memoria. Usarán servicios tipados. Endpoints internos orientativos:

| Operación | Ruta conceptual | Propósito |
|---|---|---|
| Registrar episodio | `POST /internal/memory/episodes` | Añadir evento validado |
| Obtener episodio | `GET /internal/memory/episodes/{id}` | Inspección con permisos |
| Buscar episodios | `POST /internal/memory/episodes/search` | Consulta semántica/temporal |
| Ingerir documento | `POST /internal/knowledge/documents` | Crear registro de ingesta |
| Buscar documentos | `POST /internal/knowledge/search` | Búsqueda híbrida RAG |
| Consultar grafo | `POST /internal/knowledge/graph/query` | Query limitada y tipada |
| Proponer hecho | `POST /internal/knowledge/facts/proposals` | Crear propuesta semántica |
| Confirmar/corregir | `POST /internal/knowledge/facts/{id}/review` | Revisión autorizada |
| Consultar proced. | `GET /internal/memory/procedures/{id}` | Recuperar rutina aprobada |
| Solicitar olvido | `POST /internal/memory/forget-requests` | Iniciar borrado trazable |

Los contratos deben incluir `owner_scope`, `actor`, `correlation_id`, paginación y esquema versionado. No aceptar `owner_id` arbitrario del cuerpo sin comprobarlo contra la sesión/principal autenticado.

## 15. Rendimiento y dimensionamiento

El documento fuente estima el coste vectorial como dimensión × bytes por elemento, pero el tamaño real incluye índices y overhead. Por ello, no dimensionar con una sola cifra teórica. Medir: número de documentos/chunks; dimensión y tipo de vector; tamaño de índices; velocidad de inserción; latencia p50/p95; recall de recuperación; uso de RAM y disco; coste de reindexación; y concurrencia.

Comenzar con PostgreSQL + pgvector y tablas relacionales. Añadir Redis o colas si la ingesta/eventos lo requieren. Evaluar Neo4j solo si las consultas de grafo exceden las capacidades medidas del modelo relacional o hay necesidades operativas claras.

## 16. Pruebas y calidad

- Procedencia obligatoria y validación de esquemas.
- Permisos negativos: agente sin acceso no recupera datos privados.
- RAG: Recall@k, MRR/nDCG y evaluación humana de relevancia y citas.
- Hechos: precisión de extracción, resolución de entidades y tasa de contradicción.
- Dedupe: falsos positivos/negativos y mantenimiento de IDs.
- Embeddings: comparación de perfiles en español y datasets reales.
- Olvido: prueba de eliminación en DB, índices, objetos, cachés y derivados.
- Backups: restauración funcional y reconstrucción de índices.
- Carga: p50/p95 de consultas y escrituras con concurrencia esperada.
- Privacidad: escaneo de secretos/PII y pruebas de aislamiento entre scopes.

## 17. Fases de implementación

**M0 — Fuente de verdad:** PostgreSQL, migraciones, IDs, owner scope, source registry y auditoría.

**M1 — Episodios:** almacenar eventos de chat/tareas y buscarlos por tiempo/filtros.

**M2 — Documentos y RAG:** ingesta, chunking, embeddings locales de prueba, FTS y resultados con referencias.

**M3 — Semántica relacional:** entidades, aliases, hechos, relaciones y evidencia.

**M4 — Procedimientos y revisión:** procedimientos declarativos versionados, confirmación/corrección y estado.

**M5 — Consolidación y mantenimiento:** sugerencias de hechos, conflictos, expiración, borrado completo y métricas.

## 18. Criterios de aceptación

1. Cada fuente tiene propietario, permisos, tipo y procedencia.
2. Los episodios se registran con timestamps y correlación.
3. Los datos externos se marcan como no confiables.
4. La memoria episódica, semántica y procedimental tienen modelos y servicios diferenciados.
5. Un hecho semántico puede rastrearse hasta su evidencia.
6. Un hecho no confirmado se presenta como sugerencia.
7. La búsqueda RAG filtra permisos antes de ranking y devuelve citas internas.
8. Los embeddings registran su perfil/modelo/dimensión.
9. Cambiar modelo embedding permite reindexar sin perder documentos originales.
10. No se ejecuta código almacenado en memoria.
11. Las reglas e identidad no se modifican mediante consolidación o RAG.
12. El olvido alcanza chunks, vectores, relaciones y derivados identificados.
13. Existen backups cifrados y una restauración probada.
14. No se exponen secretos en respuestas, logs o resultados de búsqueda.
15. El sistema puede cambiar de LLM sin migrar el conocimiento persistente.

## 19. Decisiones pendientes

- Modelo de embeddings local y dimensión definitiva, tras benchmark en español.
- Motor/forma de full-text ranking y política de fusión.
- Política de retención por categoría y calendario de sincronización.
- Umbrales de confirmación de hechos por dominio.
- Formato y cifrado de payloads sensibles.
- Almacenamiento de objetos local vs compatible con S3.
- Política legal/licencias de cada fuente conectada.
- Cuándo un volumen o consulta justifica un grafo dedicado.

## 20. Resumen

La memoria de NEXUS será un sistema de conocimiento persistente, rastreable y gobernado. PostgreSQL conservará la fuente de verdad; pgvector permitirá recuperación semántica; las tablas relacionales representarán el grafo inicial; y los servicios internos expondrán episodios, hechos, documentos y procedimientos de forma controlada. La clave no es “recordar todo”, sino recuperar lo correcto, para el actor adecuado, con evidencia, vigencia y posibilidad real de corregirlo o eliminarlo.
