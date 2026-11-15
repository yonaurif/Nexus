# NEXUS AI — Paquete de especificaciones 02, 03 y 05

Fecha: 15 de noviembre de 2026

## Archivos

- Documento 02 — Intelligence Core: cerebro central, planificación y ejecución.
- Documento 03 — Memoria, conocimiento y almacenamiento persistente.
- Documento 05 — API, MCP y Gateway universal de conectores.

Cada documento se entrega en Markdown (fuente editable/recomendado para Git) y Word (lectura y revisión).

## Estado de las decisiones

Los tres documentos desarrollan el contenido que aparece en el ZIP Nexus.zip. Las decisiones que la documentación original ya expresa se conservan; las decisiones de implementación aún abiertas se identifican como pendientes o propuestas. Las rutas, contratos JSON, tablas y endpoints son esquemas de diseño, no un backend implementado.

## Dependencias entre documentos

1. Documento 02 depende de los servicios y contratos del Documento 03 y del Gateway del Documento 05.
2. Documento 03 entrega Memory & Knowledge API al Core y a agentes autorizados.
3. Documento 05 implementa la frontera de herramientas usada por el Core, Agent Manager y agentes.
4. Documento 04 consume estados, tareas, fuentes y resultados a través del Backend API; no accede directamente a bases de datos ni conectores.

## Convención recomendada

Mantener Markdown como fuente principal bajo Git, exportar DOCX para revisión, y registrar cambios importantes en `DECISIONES_TECNICAS.md`. Versionar schemas JSON/Pydantic y migraciones junto al código.
