# Configuración de NEXUS

Guía para instalar, configurar y arrancar NEXUS en un equipo Windows, desde cero. Todo funciona en local: no hace falta ningún servicio en la nube.

## 1. Qué necesitas

| Pieza | Para qué | Obligatoria |
|---|---|---|
| Docker Desktop | Ejecuta PostgreSQL 16 con pgvector, la base de datos de NEXUS | Sí |
| Python 3.11 y `uv` (o `pip`) | Backend (FastAPI) | Sí |
| Node.js 20 o superior | Compilar la interfaz web; solo la primera vez o tras cambiarla | Sí, una vez |
| Modelo GGUF, por ejemplo Qwen2.5-7B-Instruct Q4_K_M | Que NEXUS redacte respuestas | Muy recomendable |
| GPU NVIDIA con CUDA | Ejecutar el modelo rápido. Sin GPU funciona en CPU, pero lento | No |
| Modelo de embeddings `paraphrase-multilingual-MiniLM-L12-v2` (ONNX) | Buscar por significado en tus documentos y en la IA de intención `+enc` | Recomendable |
| Tesseract OCR | Leer PDF escaneados e imágenes | No |

## 2. Instalación, solo la primera vez

```bash
cd backend
uv venv .venv
uv pip install -e ".[dev,embeddings,documents,learning]"
```

Para usar un modelo GGUF hace falta `llama-cpp-python`:

- **Sin GPU:** `uv pip install -e ".[gguf]"`
- **Con GPU NVIDIA**, compilado con CUDA (tarda; requiere CUDA Toolkit y Visual Studio Build Tools). `86` es la arquitectura de una RTX 30xx; en otro equipo, pon la suya o quita `-DCMAKE_CUDA_ARCHITECTURES`:

```bash
CMAKE_ARGS="-DGGML_CUDA=on -DCMAKE_CUDA_ARCHITECTURES=86" CMAKE_GENERATOR="Visual Studio 17 2022" uv pip install -e ".[gguf]"
```

Compila la interfaz web:

```bash
cd frontend
npm install
npm run build
```

`iniciar_nexus.bat` también la compila si falta `frontend/dist`.

## 3. El archivo `.env`

Copia `.env.example` a `.env` en la raíz del repositorio y rellénalo. El `.env` **nunca** se sube a git. Las variables definidas en el entorno del sistema tienen prioridad sobre el `.env`.

### Obligatorias

| Variable | Qué es | Ejemplo / valor por defecto |
|---|---|---|
| `NEXUS_DB_PASSWORD` | Contraseña de PostgreSQL. La usan Docker, al crear la base, y NEXUS, al conectarse | Una clave larga y aleatoria |
| `NEXUS_API_TOKEN` | La llave de NEXUS: se pide en la pantalla de entrada y en cada llamada a la API (`Authorization: Bearer …`). Quien la tenga controla NEXUS | Genera una con `python -c "import secrets; print(secrets.token_urlsafe(32))"` |

### Modelo de lenguaje

| Variable | Qué es | Por defecto |
|---|---|---|
| `NEXUS_GGUF_PATH` | Ruta a uno o varios `.gguf` separados por `;`, en orden de preferencia. Si el primero falla o no cabe en memoria se usa el siguiente, y el que falló se reintenta a los 5 min | Sin modelo: NEXUS responde que no tiene modelo configurado |
| `NEXUS_GGUF_GPU_LAYERS` | `auto` reparte capas en la GPU según la VRAM libre; un número fija cuántas | `auto` |
| `NEXUS_GGUF_CTX` | Ventana de contexto en tokens | `4096` |
| `NEXUS_MODEL` | Tu propia IA en Python (`paquete.modulo:Clase`, con `generate(messages)`). Si está definida, tiene prioridad sobre el GGUF | — |

> Con 8 GB de VRAM solo cabe **un** NEXUS con Qwen 7B. Dos instancias a la vez (por ejemplo en los puertos 8000 y 8001) hacen que la segunda responda «el modelo no está disponible».

### Documentos y búsqueda

| Variable | Qué es | Por defecto |
|---|---|---|
| `NEXUS_EMBED_MODEL_DIR` | Carpeta del modelo de embeddings (snapshot de Hugging Face con `onnx/model.onnx`). Si la cambias, ejecuta `python -m nexus.knowledge.reindex` | Sin ella, la búsqueda es solo por palabras |
| `NEXUS_RAG_MAX_DISTANCE` | Distancia máxima para que un fragmento cuente como relevante. Más bajo = más estricto | `0.6` |
| `NEXUS_FOLDER_ROOTS` | Carpetas (separadas por `;`) que NEXUS **puede** leer y sincronizar. Fuera de ellas no registra nada. Los archivos con nombre de secreto (`credenciales*`, `.env`, `id_rsa`, `.kdbx`…) se omiten siempre | Ninguna |
| `NEXUS_TESSERACT_CMD` | Ruta a `tesseract.exe` | Se busca en `C:\Program Files\Tesseract-OCR` |
| `NEXUS_TESSDATA_DIR` | Carpeta con los idiomas de Tesseract (`spa`, `eng`, `osd`) | `backend/tessdata` |
| `NEXUS_OCR_LANGUAGES` | Idiomas del OCR | `spa+eng` |

### Conectores

| Variable | Qué es | Por defecto |
|---|---|---|
| `NEXUS_GITHUB_TOKEN` | Token *fine-grained* de **solo lectura** para tus repositorios privados | Sin token: solo repositorios públicos, 60 peticiones/h |

### Avanzado

| Variable | Qué es | Por defecto |
|---|---|---|
| `NEXUS_DATABASE_URL` | URL completa de PostgreSQL. Sustituye a `NEXUS_DB_PASSWORD` | `postgresql+psycopg://nexus:<clave>@127.0.0.1:5432/nexus` |
| `NEXUS_MODELS_DIR` | Dónde se guardan los modelos de intención entrenados | `backend/artifacts` |
| `NEXUS_FRONTEND_DIST` | Carpeta de la interfaz compilada | `frontend/dist` |
| `NEXUS_NO_BROWSER` | Si existe, `iniciar_nexus.bat` no abre el navegador | — |

## 4. Arrancar

Haz doble clic en **`iniciar_nexus.bat`**. Hace lo siguiente, por orden:

1. Comprueba `.env` y el entorno de Python.
2. Abre Docker Desktop si no está en marcha.
3. Levanta PostgreSQL y espera a que acepte conexiones.
4. Aplica las migraciones.
5. Compila la interfaz si falta.
6. Arranca el servidor en <http://127.0.0.1:8000> y abre el navegador.

Para usar otro puerto: `iniciar_nexus.bat 8001`. Para pararlo: `Ctrl+C` en su ventana. Si el puerto ya está en uso, el script solo abre el navegador.

A mano:

```bash
docker compose up -d db
cd backend
.venv/Scripts/alembic.exe upgrade head
.venv/Scripts/uvicorn.exe nexus.api.app:app --host 127.0.0.1 --port 8000
```

## 5. Primer uso

1. **Entrar:** pega el valor de `NEXUS_API_TOKEN` de tu `.env`.
2. **Nombres:** con el chat vacío, NEXUS pregunta «¿Cómo me llamo? / ¿Y tú?». Se guardan aparte de la memoria y solo se cambian desde ahí («cambiar nombres»), nunca escribiéndolo en el chat.
3. **Comandos:** escribe `/` en el chat para ver el menú.

| Comando | Qué hace |
|---|---|
| `/resumir` | Resume la conversación actual |
| `/fuentes <pregunta>` | Responde **solo** con tus documentos y la memoria confirmada, citando la fuente. Si no hay nada, lo dice |
| `/recuerda <dato>` | Anota el dato como sugerencia; pasa a ser un dato cuando lo confirmas en la pestaña **memoria** |
| `/nueva` | Abre una conversación nueva |
| `/ayuda` | Lista los comandos |

El botón **solo mis fuentes** hace lo mismo que `/fuentes` en todos tus mensajes mientras está activo.

4. **Panel derecho:**

| Pestaña | Qué hay |
|---|---|
| sistema | Estado de la base de datos, de los modelos y de la GPU |
| memoria | Hechos por confirmar y contradicciones |
| conocimiento | Subir archivos y gestionar carpetas |
| conectores | Aprobar o desactivar herramientas |
| aprendizaje | IA de intención: correcciones, entrenar, promover |

## 6. La IA propia de NEXUS (clasificador de intención)

NEXUS decide qué tipo de petición es cada mensaje (conversar, consultar documentos, ejecutar una tarea, servicios externos, recordar…) con un clasificador entrenado en local:

- **Datos** (`backend/data/intent/intent_es_v1.jsonl`): ejemplos escritos para NEXUS, más frases de los tests aprobados de GALA (la IA de Primitivo).
- **Examen externo** (`backend/data/intent/eval_gala_v1.jsonl`): otras frases de los tests de GALA que **nunca** se usan para entrenar. Miden si la IA generaliza o solo memoriza.
- **Tus correcciones:** pulsa «corregir» bajo una respuesta y apruébala en la pestaña aprendizaje.

Para entrenar, en `backend` ejecuta `.venv/Scripts/python.exe -m nexus.learning.train_intent`. El resultado queda como **candidato**: muestra las métricas, el examen GALA y los fallos. Para que se use hay que **promoverlo** (pestaña aprendizaje, o `--promote`). La promoción se rechaza si no supera a las reglas o si empeora el modelo activo.

> Si el modelo activo no se puede cargar (archivo ausente o modificado), NEXUS sigue funcionando solo con reglas. Lo verás en aprendizaje como «sin modelo activo»: promueve otro candidato.

## 7. Llevar NEXUS a otro equipo

1. Copia el repositorio, crea `.env` a partir de `.env.example` y repite la instalación (§2). `llama-cpp-python` se compila **en ese equipo**, con la arquitectura de su GPU.
2. Copia los `.gguf` y el modelo de embeddings, y ajusta sus rutas en `.env`.
3. Para llevarte los datos (conversaciones, memoria, documentos): `docker compose exec db pg_dump -U nexus nexus > nexus.sql` en el origen, y restaura con `psql` en el destino antes del primer arranque.

## 8. Problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| «No he podido generar una respuesta: el modelo no está disponible» | Otra instancia de NEXUS u otro programa ocupa la VRAM | Cierra la otra instancia. NEXUS reintenta el modelo a los 5 min, o reinícialo |
| «Token no válido» al entrar | El token no coincide con `NEXUS_API_TOKEN` | Revisa el `.env` (sin espacios ni comillas) |
| `iniciar_nexus.bat` se queda en PostgreSQL | Docker no ha terminado de arrancar o `NEXUS_DB_PASSWORD` cambió después de crear la base | Espera y reintenta. Si cambiaste la clave, vuelve a la anterior |
| Las respuestas sobre tus documentos dicen «no he encontrado información» | El documento no está indexado o la carpeta no está en `NEXUS_FOLDER_ROOTS` | Súbelo en conocimiento o autoriza su carpeta |
