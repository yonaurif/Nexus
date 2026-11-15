import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Desarrollo: la API corre en uvicorn (127.0.0.1:8000) y Vite la sirve por proxy, mismo origen sin CORS.
// Producción: `npm run build` -> dist/, que el propio backend sirve (nexus/api/app.py::_serve_frontend).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": { target: "http://127.0.0.1:8000", changeOrigin: false } },
  },
  build: { outDir: "dist", sourcemap: false },
});
