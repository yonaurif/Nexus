# NEXUS — interfaz web

React 19 + TypeScript + Vite. Habla solo con la API de NEXUS (`/api/v1`), nunca con conectores ni modelos.

```bash
npm install
npm run dev     # http://localhost:5173, con proxy de /api a http://127.0.0.1:8000 (uvicorn)
npm run build   # genera dist/, que sirve el backend en su mismo puerto
```

- `src/api.ts` — cliente tipado y seguimiento de tareas por SSE (fetch con `Authorization` y `Last-Event-ID`).
- `src/Chat.tsx` — conversación, cinta de estados (Doc 02 §7.1), permiso de trabajo (aprobaciones) y fuentes.
- `src/Panels.tsx` — Sistema (hardware y modelos), Conocimiento (documentos y carpetas), Conectores.
- `src/format.tsx` — texto del asistente sin HTML crudo (Doc 04 §5.5) y etiquetas legibles de avisos.

Acceso: token de la instancia (`NEXUS_API_TOKEN` del `.env` del servidor), guardado en `sessionStorage`.
