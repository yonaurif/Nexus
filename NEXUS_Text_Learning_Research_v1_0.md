# NEXUS AI — Investigación del aprendizaje de texto

**Documento independiente de investigación y diseño**  
**Versión:** 1.0  
**Fecha:** 15 de noviembre de 2026  
**Ámbito:** primer subsistema de aprendizaje de NEXUS AI: lenguaje y texto  
**Fuente solicitada:** Instagram `@graduate_ml` (GraduateML) y materiales públicos relacionados

---

## 1. Resumen ejecutivo

NEXUS no debe intentar aprender todo el lenguaje modificando continuamente los pesos de su modelo principal. Para la primera versión conviene construir un **Text Learning System** que separe cinco capacidades:

1. **Comprender y clasificar texto:** identificar intención, tema, entidades, prioridad y tipo de petición.
2. **Recuperar conocimiento:** localizar documentos, mensajes y fragmentos relevantes mediante búsqueda léxica y semántica (RAG).
3. **Aprender de ejemplos etiquetados:** entrenar clasificadores y, más adelante, ajustar un modelo de lenguaje preentrenado.
4. **Recordar preferencias y correcciones:** guardar memoria estructurada sin confundirla con entrenamiento de pesos.
5. **Medir si mejora:** comparar cada versión con conjuntos de evaluación reservados antes de ponerla en producción.

La recomendación inicial para el homelab de 32 GB RAM es comenzar con una canalización reproducible de Python, TF-IDF + Logistic Regression como línea base, extracción de entidades/reglas y recuperación documental. Después se puede probar un encoder multilingüe pequeño para clasificación. Solo cuando existan datos curados y una evaluación estable se debería intentar LoRA/QLoRA sobre un modelo local. El hardware disponible no está completamente identificado: CPU, GPU, VRAM y almacenamiento siguen pendientes; por tanto, no se fija todavía un modelo ni una receta de entrenamiento GPU.

**Principio de diseño:** recuperar información actualizada con RAG; aprender comportamientos repetibles con clasificadores; adaptar el estilo o formato con SFT/LoRA; no usar fine-tuning como sustituto de una base de conocimiento.

## 2. Auditoría de la fuente `@graduate_ml`

### 2.1 Qué se pudo verificar

- La búsqueda pública identifica una cuenta llamada **GraduateML | Machine Learning Education**, usuario `@graduate_ml`.
- Un espejo público de perfil identifica la cuenta y muestra una biografía centrada en Machine Learning, Data Science y Robotics. Sin embargo, la página de perfil consultada no cargó la cuadrícula de publicaciones (mostraba 0 elementos cargados).
- Se pudieron abrir dos páginas individuales de publicaciones reflejadas:
  - Una publicación fechada el **18 de septiembre de 2026**, cuyo texto visible plantea una pregunta de selección relacionada con NVIDIA; el contenido visual que contiene el enunciado y las opciones no se pudo verificar completamente.
  - Una publicación fechada el **10 de octubre de 2026** que presenta una explicación de **Model Predictive Control (MPC)**. MPC es más relevante para el futuro motor de planificación/control de NEXUS que para el primer clasificador de texto.
- El acceso directo a `instagram.com/graduate_ml/` fue limitado por la plataforma durante la consulta web. El perfil espejo tampoco permitió recorrer las publicaciones históricas.

### 2.2 Qué no se puede afirmar

El número **184 publicaciones** procede de la información facilitada por el usuario; no se pudo verificar independientemente durante esta investigación. Tampoco se ha podido leer o analizar el conjunto completo de 184 publicaciones. No sería correcto afirmar que el sistema ya ha aprovechado todas ellas.

### 2.3 Material público relacionado que sí se pudo estudiar

El sitio de GRADuateML se describe como una plataforma de aprendizaje práctico: conceptos acompañados de ejercicios Python y comprobaciones automáticas. Su currículo público indica **325 problemas en 49 temas**, desde fundamentos Python y matemáticas hasta Machine Learning clásico, redes neuronales, atención/Transformers, transfer learning, aprendizaje por refuerzo y Data Engineering.

Los materiales más directamente útiles para el primer sistema de texto son:

- **Support Ticket Triage With Text:** vectorización de texto, clasificación multiclase, macro-F1, desbalance de clases, fuga de variables (*target leakage*), predicción selectiva y umbrales de confianza. La lección destaca que ciertos textos son demasiado vagos y que un clasificador debe poder abstenerse de enrutar una petición cuando no tiene suficiente señal.
- **Dataset Splitting & Sampling:** cómo separar datos y evitar que fuga de información o desorden temporal produzcan métricas artificialmente altas.
- **Data Validation, Drift & Debugging:** validación de esquemas, comprobación de rangos, detección de cambios de distribución y monitorización del modelo una vez desplegado.
- **Transfer Learning & Fine-Tuning:** extracción de características frente a ajuste fino, congelación selectiva de capas y conceptos LoRA.
- **Attention & Transformers:** atención escalada, consultas/claves/valores, softmax, codificación posicional, máscara causal y multi-head attention.
- **The Pipeline That Broke in Production:** ejemplo de fallos de datos que no se solucionan automáticamente reentrenando; primero hay que identificar si hay deriva real, valores en unidades incorrectas, categorías nuevas o valores ausentes.

### 2.4 Cómo utilizar esta fuente de forma responsable

Para NEXUS, el contenido de `@graduate_ml` debe servir primero como **referencia educativa y mapa de estudio**, no como un corpus masivo copiado para entrenar pesos. Una cuenta pública no implica por sí sola autorización para descargar y reutilizar a escala todas sus publicaciones con fines de entrenamiento. El diseño debe guardar título/fecha/enlace, una nota propia resumida, conceptos y atribución. Para incorporar texto o imágenes originales completos a un dataset de entrenamiento se debe comprobar que existe permiso o licencia aplicable.

Para analizar las 184 publicaciones de manera fiel, será necesario disponer de enlaces individuales o de un material exportado/compartido legítimamente que permita leerlas. Mientras tanto, la cobertura de Instagram queda marcada como **parcial**.

## 3. Cómo aprende texto una IA

### 3.1 Tokenización

Un modelo de lenguaje no procesa directamente palabras como lo hace una persona. El texto se transforma en unidades llamadas *tokens* y estas se convierten en identificadores numéricos. El tokenizador depende del modelo base y debe mantenerse compatible con él. No se debe crear un tokenizador propio para ajustar un modelo existente sin una razón técnica y un plan de entrenamiento específico.

### 3.2 Preentrenamiento

En el preentrenamiento causal, el modelo aprende a predecir el siguiente token a partir del contexto anterior. Este objetivo permite aprovechar texto sin tener que etiquetar manualmente cada palabra. El preentrenamiento desde cero exige grandes cantidades de datos, cómputo, limpieza, evaluación y almacenamiento; no es el primer objetivo realista para el homelab actual.

### 3.3 Ajuste fino supervisado (SFT)

El SFT continúa el entrenamiento de un modelo ya preentrenado con ejemplos de entrada y salida deseada. Sirve para enseñar formatos, tareas, dominio o comportamiento consistente. Necesita ejemplos de calidad, etiquetas o respuestas deseadas, evaluación separada y control de retención de capacidades anteriores.

### 3.4 PEFT y LoRA

Los métodos PEFT entrenan una fracción pequeña de parámetros adicionales en lugar de actualizar todos los pesos. LoRA es una técnica popular de esta familia. Reduce memoria y almacenamiento del entrenamiento en comparación con el fine-tuning completo, aunque no garantiza el mismo rendimiento en todos los modelos o tareas. Cada adaptador debe asociarse a una versión de modelo base, tokenizador, dataset, parámetros y evaluación.

### 3.5 RAG, memoria y entrenamiento no son lo mismo

| Mecanismo | Qué cambia | Cuándo utilizarlo |
|---|---|---|
| Prompt/contexto | La entrada temporal del modelo | Instrucciones y contexto de una conversación |
| Memoria | Datos persistentes recuperables | Nombre, preferencias, decisiones, rutinas aprobadas |
| RAG | Índice de documentos recuperables | GitHub, documentación, portfolio, manuales y conocimiento actualizado |
| Clasificador | Pesos de un modelo pequeño de tarea | Clasificar intención, correo, prioridad y tipo de documento |
| SFT/LoRA | Adaptador o pesos del modelo de lenguaje | Formato de respuesta, comportamiento o dominio con ejemplos de calidad |
| Preentrenamiento | Pesos iniciales del modelo | Solo si hay una necesidad excepcional, datos enormes y recursos suficientes |

NEXUS debe usar la opción menos costosa que resuelva el problema. Para que recuerde que un proyecto cambió ayer, RAG y sincronización son mejores que volver a entrenar el LLM.

## 4. Diseño del primer subsistema: NEXUS Text Learning v1

### 4.1 Objetivo

Crear una capa que convierta texto entrante en señales estructuradas y fiables para el núcleo de NEXUS. La primera versión trabajará en español y conservará el texto original junto a sus metadatos y procedencia.

### 4.2 Tareas iniciales

1. **Clasificación de intención:** pregunta, consulta de conocimiento, solicitud de tarea, propuesta de regla, corrección/feedback, actualización de memoria o petición de agente.
2. **Clasificación temática:** proyectos, GitHub, correo, calendario, YouTube, homelab, aprendizaje, seguridad u otros.
3. **Extracción de entidades:** nombres de proyecto, servicio, fecha, persona, repositorio, archivo y prioridad cuando estén presentes.
4. **Detección de sensibilidad:** posibles contraseñas, tokens, datos personales y contenido que no deba entrar en el dataset.
5. **Predicción selectiva:** si la confianza es insuficiente o la petición es ambigua, preguntar o derivar al LLM; no adivinar.

La clasificación no autoriza acciones. El Rule Engine y el Policy Engine deben comprobar permisos antes de llamar a una herramienta o agente.

### 4.3 Línea base recomendada

- Preprocesamiento conservador que preserve acentos, negaciones, nombres propios y puntuación relevante.
- TF-IDF con n-gramas de palabra y carácter para una línea base rápida.
- Logistic Regression como clasificador inicial; comparar con Linear SVM y Naive Bayes si procede.
- Umbral de confianza por clase y opción `unknown/abstain`.
- Un encoder multilingüe compacto como segundo experimento si la línea base no alcanza la calidad necesaria.

La ventaja de TF-IDF + Logistic Regression es que ofrece una referencia interpretable, rápida y económica. No se debe asumir que será suficiente para todas las frases o conversaciones; su función es proporcionar una línea base medible.

### 4.4 Ejemplos de datos

Formato JSONL sugerido:

```json
{
  "example_id": "intent-000001",
  "task": "intent_es_v1",
  "text": "Recuérdame revisar el repositorio mañana",
  "label": "task_request",
  "language": "es",
  "source_type": "owner_feedback",
  "source_ref": "conversation-local-id",
  "license_or_permission": "owner-provided",
  "split": "train",
  "review_status": "approved",
  "schema_version": 1
}
```

No incluir secretos, credenciales, tokens, datos privados de terceros ni contenido externo sin permiso. El `source_ref` permite rastrear el origen sin duplicar información sensible.

## 5. Pipeline de datos de texto

1. **Captura:** recibir texto del chat, usuario, documentos autorizados o conectores.
2. **Procedencia:** registrar origen, fecha, propietario, permisos y licencia.
3. **Normalización:** normalizar Unicode, espacios y formatos sin destruir significado.
4. **Detección de idioma:** conservar el idioma original y dirigir a un modelo compatible.
5. **Filtrado de secretos y datos sensibles:** detectar y excluir o redactar credenciales y PII antes de indexar o entrenar.
6. **Deduplicación:** eliminar duplicados exactos y revisar casi duplicados para evitar sobrepeso y fuga entre particiones.
7. **Control de calidad:** validar esquema, texto vacío, longitud, idioma, etiqueta válida y contaminación.
8. **Etiquetado:** etiquetas humanas, revisión de ambigüedades y registro del desacuerdo.
9. **Versionado:** crear una versión inmutable del dataset con manifiesto y hashes.
10. **Particionado:** separar entrenamiento, validación y prueba antes de ajustar hiperparámetros.
11. **Tokenización/vectorización:** usar el tokenizador del modelo base o el vectorizador correspondiente.
12. **Entrenamiento:** ejecutar experimento reproducible con parámetros registrados.
13. **Evaluación:** comparar con baseline, métricas por clase y conjunto de regresión.
14. **Registro:** guardar artefactos, métricas, entorno y decisión de aprobación.
15. **Despliegue:** promover solo una versión aprobada y mantener rollback.
16. **Monitorización:** medir deriva, tasa de abstención, errores y latencia.

## 6. Etiquetado y estrategia de datos

### 6.1 Fuentes permitidas y recomendadas

- Ejemplos escritos y corregidos por el propietario.
- Documentación propia y proyectos del homelab, con permisos locales definidos.
- Datasets públicos cuya licencia permita el uso previsto.
- Ejemplos sintéticos generados para ampliar cobertura, claramente marcados y revisados.
- Material educativo resumido y citado, respetando los derechos del autor.

### 6.2 Política de etiquetas

- Definiciones de clase escritas antes de etiquetar.
- Guía con ejemplos positivos, negativos y casos límite.
- Etiquetas ambiguas marcadas como `needs_review`, no forzadas.
- Muestreo de doble revisión para medir consistencia.
- Historial de cada cambio de etiqueta.

### 6.3 Evitar sesgo y fuga de datos

- Dividir por conversación, usuario o fuente cuando haya ejemplos relacionados, no solo por filas aleatorias.
- Usar división temporal para tareas donde el futuro no debe filtrarse al pasado.
- No utilizar columnas o metadatos que solo se conocen después del evento.
- Mantener un test final bloqueado que no se consulta durante el desarrollo.
- Comprobar near-duplicates entre train, validation y test.

## 7. Evaluación: cuándo puede aprender algo nuevo

No basta con que baje la pérdida (*loss*). Cada tarea necesita métricas apropiadas.

| Tarea | Métricas y controles |
|---|---|
| Intención multiclase | Macro-F1, precision/recall por clase, matriz de confusión |
| Detección de sensibilidad | Recall alto para categorías críticas, revisión humana de falsos negativos |
| Extracción de entidades | Precision, recall y F1 por tipo de entidad |
| Recuperación RAG | Recall@k, MRR/nDCG y evaluación de citas/fuentes |
| Generación | Evaluación humana, exactitud factual, seguimiento de instrucciones y regresión |
| Operación | Latencia, memoria, tasa de error, tasa de abstención y disponibilidad |

Para clases desbalanceadas no se debe utilizar accuracy como única métrica. La documentación de Evaluate explica la necesidad de separar train/validation/test y advierte sobre la distorsión de accuracy en datasets desbalanceados.

**Criterio inicial de promoción:** superar el baseline en la métrica principal acordada, no empeorar de forma material las clases críticas, mantener la tasa de abstención dentro del umbral definido, pasar pruebas de regresión y cumplir límites de latencia y memoria. Los umbrales numéricos se fijarán después de crear y etiquetar el primer dataset real; no se inventarán ahora.

## 8. Aprendizaje continuo sin auto-modificación peligrosa

NEXUS no actualizará sus pesos en producción cada vez que el usuario corrija una respuesta.

El flujo seguro será:

1. Guardar la corrección como evento de feedback.
2. Pedir confirmación cuando la corrección se convierta en una etiqueta permanente.
3. Enviar el ejemplo a un conjunto de datos de staging.
4. Revisar PII, duplicados, etiqueta y procedencia.
5. Ejecutar entrenamiento offline en un entorno aislado.
6. Evaluar contra el test bloqueado y la suite de regresión.
7. Comparar calidad, latencia, memoria y retención de capacidades previas.
8. Publicar el modelo candidato para una prueba limitada.
9. Promover con autorización del propietario o revertir.

Este flujo reduce el riesgo de envenenamiento de datos, olvido catastrófico y degradación silenciosa. Los métodos PEFT también deben comprobar la retención del conocimiento anterior después de cada ajuste.

## 9. Cómo aprovechar los materiales de GraduateML en el aprendizaje de texto

### 9.1 Mapa de conceptos aplicables

| Material | Concepto | Aplicación en NEXUS |
|---|---|---|
| Support Ticket Triage With Text | Vectorización, multiclase, macro-F1, predicción selectiva | Clasificar peticiones y enrutar a agentes sin forzar decisiones inciertas |
| Dataset Splitting & Sampling | Stratification, K-fold, walk-forward | Crear train/validation/test sin fuga |
| Data Validation & Drift | Rangos, chi-cuadrado, PSI y leakage temporal | Vigilar calidad de datos y degradación |
| Transfer Learning & Fine-Tuning | Feature extraction, congelación de capas, LoRA | Planificar adaptación futura de modelos locales |
| Attention & Transformers | Q/K/V, softmax, máscara causal, multi-head | Entender el motor de lenguaje, no reimplementar desde cero en v1 |
| MPC explainer (Instagram) | Predicción y planificación de control | Referencia futura para planificación de tareas; no es material central de NLP |

### 9.2 Plan para estudiar las 184 publicaciones

La lectura completa queda pendiente porque no se logró recuperar la cuadrícula ni todas las publicaciones mediante las páginas públicas consultadas. Para hacerlo correctamente:

- crear un inventario con URL, fecha, tema, formato y disponibilidad;
- revisar cada publicación de forma individual cuando el contenido sea accesible;
- resumir cada idea en notas propias, sin copiar carruseles o captions completos;
- clasificarla por área: datos, ML clásico, deep learning, NLP, Transformers, fine-tuning, evaluación, MLOps o robótica;
- verificar las afirmaciones técnicas con documentación primaria o artículos originales;
- guardar el enlace y la atribución en el Knowledge Graph;
- convertir las notas verificadas en lecturas, ejercicios y preguntas de comprensión para el sistema educativo de NEXUS.

No se debe generar un dataset de entrenamiento a partir de descargas masivas o contenido protegido sin autorización. Si se obtiene permiso o una licencia compatible, se documentará el alcance permitido.

## 10. Arquitectura de software propuesta

```text
NEXUS-AI/
├── text_learning/
│   ├── ingestion/
│   │   ├── sources.py
│   │   ├── normalize.py
│   │   ├── language.py
│   │   ├── pii_filter.py
│   │   └── deduplicate.py
│   ├── labeling/
│   │   ├── taxonomy.py
│   │   ├── guidelines.py
│   │   └── review_queue.py
│   ├── datasets/
│   │   ├── schema.py
│   │   ├── versioning.py
│   │   ├── splitting.py
│   │   └── manifests.py
│   ├── features/
│   │   ├── tfidf.py
│   │   └── embeddings.py
│   ├── models/
│   │   ├── intent_classifier.py
│   │   ├── entity_extractor.py
│   │   └── registry.py
│   ├── training/
│   │   ├── train_baseline.py
│   │   ├── train_transformer.py
│   │   ├── train_lora.py
│   │   └── experiment_config.py
│   ├── evaluation/
│   │   ├── metrics.py
│   │   ├── regression.py
│   │   └── reports.py
│   ├── feedback/
│   │   ├── capture.py
│   │   └── staging.py
│   └── monitoring/
│       ├── drift.py
│       └── performance.py
├── knowledge/
├── memory/
├── agents/
└── security/
```

### 10.1 Dependencias iniciales

- `scikit-learn`: baseline TF-IDF y modelos clásicos.
- `datasets`: gestión y transformación de datasets.
- `transformers`: tokenización y modelos Transformer cuando proceda.
- `evaluate`: evaluación reproducible.
- `torch`: entrenamiento de redes neuronales.
- `peft`: adapters y LoRA en fase posterior.
- `pydantic`: validación de esquemas y contratos.
- PostgreSQL: metadatos, etiquetas, ejecuciones y relaciones.

Las versiones concretas se fijarán en `requirements.lock` después de comprobar compatibilidad entre Python, PyTorch, CUDA/CPU y el hardware real.

## 11. Almacenamiento del cerebro textual

El subsistema necesita guardar tanto datos como procedencia y resultados de experimentos.

Tablas sugeridas:

- `text_sources`: origen, URL, propietario, licencia, fecha y estado.
- `documents`: documento original o referencia segura, hash, idioma y clasificación.
- `text_chunks`: fragmentos indexables con posición y enlace al documento.
- `labels`: taxonomía, definición y versión.
- `training_examples`: texto, etiqueta, tarea, origen y estado de revisión.
- `dataset_versions`: manifiesto, hashes, particiones y versión.
- `training_runs`: modelo base, configuración, recursos y logs.
- `evaluation_runs`: métricas, conjunto y resultado.
- `model_registry`: adaptador/modelo, versión base, artefactos y estado.
- `feedback_events`: corrección del propietario y decisión de inclusión.

Guardar los pesos de modelos y adaptadores como artefactos versionados en almacenamiento de archivos, no como grandes blobs dentro de las tablas. Mantener copias de seguridad cifradas y un procedimiento de restauración probado.

## 12. Fases y criterios de aceptación

### Fase T0 — Fundamentos de datos

**Entrega:** esquema JSONL, taxonomía de intenciones, pipeline de normalización, detección de secretos y versionado.  
**Aceptación:** todos los ejemplos tienen fuente, idioma, tarea, etiqueta o estado de revisión y permiso de uso; ningún secreto conocido entra en el corpus.

### Fase T1 — Clasificador de intención en español

**Entrega:** baseline TF-IDF + Logistic Regression, matriz de confusión y abstención.  
**Aceptación:** resultados reproducibles en train/validation/test; informe por clase; preguntas ambiguas no se enrutan de forma automática.

### Fase T2 — Recuperación de conocimiento textual

**Entrega:** índice léxico y semántico, fragmentación con referencias y respuestas con citas internas.  
**Aceptación:** cada afirmación documental se puede vincular a una fuente y versión; si no hay evidencia, NEXUS declara que no encuentra información.

### Fase T3 — Clasificador Transformer compacto

**Entrega:** comparación controlada con el baseline clásico.  
**Aceptación:** mejora demostrada en el test bloqueado sin degradar clases críticas y dentro de recursos.

### Fase T4 — Adaptación de un LLM con LoRA

**Entrega:** un adapter de comportamiento/tarea, sin sustituir la base.  
**Aceptación:** dataset aprobado, evaluación de retención, benchmark, checkpoint y rollback. Depende de CPU/GPU/VRAM disponibles.

### Fase T5 — Aprendizaje continuo gobernado

**Entrega:** captura de feedback, staging, reentrenamiento offline y promoción versionada.  
**Aceptación:** ninguna corrección altera el modelo de producción automáticamente; cada versión tiene un informe y posibilidad de rollback.

## 13. Hardware y límites de la primera versión

Con 32 GB de RAM se puede comenzar por la limpieza de datos, TF-IDF, regresión logística, indexación y posiblemente inferencia de un modelo compacto, según CPU y configuración. El entrenamiento Transformer/LoRA depende de forma decisiva de la GPU, su VRAM, el tamaño y precisión del modelo, longitud de secuencia, batch size y técnica de ahorro de memoria.

Antes de fijar la receta de entrenamiento se deben recoger:

- CPU, número de núcleos e instrucciones soportadas;
- GPU, fabricante, modelo y VRAM;
- RAM disponible para WSL2/Docker;
- espacio y tipo de SSD;
- versiones de Windows, WSL2, Docker, Python, PyTorch y drivers.

No se recomienda entrenar un LLM desde cero en esta máquina con la información actual. El objetivo de la primera versión es crear un sistema útil y verificable de aprendizaje de texto, no construir un modelo fundacional completo.

## 14. Riesgos y controles

| Riesgo | Control |
|---|---|
| Datos duplicados | Hashes y deduplicación aproximada |
| Datos contaminados | Procedencia, permisos y revisión |
| Fuga de datos | Particiones por fuente/conversación y test bloqueado |
| Etiquetas inconsistentes | Taxonomía, guía y revisión |
| Sesgo de clases | Macro-F1 y métricas por clase |
| Prompt injection en documentos | Contenido externo como dato, nunca como instrucción de sistema |
| Olvido del modelo | Benchmark de retención antes y después de LoRA |
| Deriva de datos | Estadísticas y monitorización periódica |
| Fuga de información personal | Filtro PII/secretos, cifrado y control de acceso |
| Reutilización sin derechos | Control de licencia y uso limitado a notas permitidas |

## 15. Decisiones recomendadas

1. Aceptar `NEXUS Text Learning v1` como primer proyecto de aprendizaje.
2. Usar el currículo de GraduateML como mapa de estudio, no como dataset copiado.
3. Marcar la auditoría de las 184 publicaciones de Instagram como parcial hasta disponer de enlaces o contenido accesible y permiso de uso cuando corresponda.
4. Empezar con un clasificador de intención en español y un motor de recuperación de conocimiento.
5. Guardar ejemplos, etiquetas, versiones y métricas de forma local y auditable.
6. No modificar el modelo principal hasta que exista una línea base y un conjunto de evaluación estable.
7. Evaluar LoRA como etapa posterior, según hardware y calidad de los datos.

---

## 16. Fuentes y referencias

### GRADuateML / GraduateML

1. About GRADuateML — https://www.graduateml.com/about
2. Curriculum: 325 Python problems across 49 topics — https://www.graduateml.com/learn
3. Projects — https://www.graduateml.com/learn/projects
4. Support Ticket Triage With Text — https://www.graduateml.com/learn/project/ticket-triage
5. Dataset Splitting & Sampling — https://www.graduateml.com/learn/dataset-splitting
6. Data Validation, Drift & Debugging — https://www.graduateml.com/learn/data-validation-drift
7. Transfer Learning & Fine-Tuning — https://www.graduateml.com/learn/transfer-learning
8. Attention & Transformers — https://www.graduateml.com/learn/attention-mechanism
9. Instagram profile mirror — https://imginn.com/graduate_ml/
10. Instagram post mirror, MPC explainer, 10 October 2026 — https://imginn.com/p/DeUpZj4JWzF/
11. Instagram post mirror, NVIDIA question, 18 September 2026 — https://imginn.com/p/DdcCE0YJcdf/

### Documentación técnica primaria

12. Hugging Face Course, How do Transformers work? — https://huggingface.co/docs/course/chapter1/4
13. Hugging Face LLM Course, Introduction to NLP/LLMs — https://huggingface.co/docs/course/chapter1/1
14. Hugging Face Transformers, Fine-tuning — https://huggingface.co/docs/transformers/main/training
15. Hugging Face LLM Course, Mastering LLMs — https://huggingface.co/learn/llm-course/en/chapter7/8
16. Hugging Face PEFT, overview — https://huggingface.co/docs/peft/main/methods/overview
17. Hugging Face PEFT, LoRA — https://huggingface.co/docs/peft/en/package_reference/lora
18. Hugging Face Evaluate, Considerations for model evaluation — https://huggingface.co/docs/evaluate/considerations
19. Hugging Face Evaluate, Choosing a metric — https://huggingface.co/docs/evaluate/choosing_a_metric
20. scikit-learn, TfidfVectorizer — https://scikit-learn.org/stable/modules/generated/sklearn.feature_extraction.text.TfidfVectorizer.html
21. Hugging Face Datasets, Process — https://huggingface.co/docs/datasets/process

**Fecha de consulta de fuentes web:** 15 de noviembre de 2026.  
**Nota:** Los contenidos de Instagram se consultaron mediante páginas públicas de espejo/indexación porque el acceso directo al perfil estaba limitado. La investigación no representa una revisión exhaustiva de todas las publicaciones de la cuenta.
