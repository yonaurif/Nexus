# Resumen Ejecutivo

Este informe detalla el **sistema de aprendizaje continuo de NEXUS AI**, un asistente personal tipo Jarvis con identidad propia, múltiples agentes y conectores MCP. El propósito es diseñar una **arquitectura de aprendizaje y memoria** que permita a NEXUS incorporar información nueva de manera progresiva, sin confundir memoria externa (RAG) con adaptación de su modelo interno. Se describen: modalidades de aprendizaje (supervisado, no supervisado, auto-supervisado, refuerzo/preferencias), representación de texto (transformers, tokenización, embeddings, búsqueda semántica), memoria y grafos de conocimiento, pipelines de ingesta y validación, **gestión de datos** (normalización, escaneo de secretos/PII, versionado, borrado), **datos de entrenamiento** (split entrenamiento/validación, etiquetas humanas, aprendizaje activo) y **evaluación continua** (métricas, calibración, detección de deriva, abstención, retrolimentación y mejoras de modelo). También se define la infraestructura de almacenamiento (bases de datos PostgreSQL/pgvector, grafos relacionales o Neo4j, backups y cifrado) y los esquemas conceptuales (identidad, perfil, reglas, conversaciones, memorias episódicas/semánticas/procedimentales, entidades y relaciones, agentes, permisos, auditoría, modelos). Se detalla cómo implementar agentes (planner/executor/verifier) con herramientas tipadas, sandbox de código y contratos JSON, así como el motor de reglas con jerarquía de prioridades. Se propone un “**Learning Center**” en el dashboard para visualizar lo aprendido: datos de ingesta, métricas de dataset (balance de clases, ejemplos etiquetados), rendimiento de modelos (precisión, recall, F1 macro, ECE de calibración, cobertura vs abstención), evolución del grafico de conocimiento, alertas de deriva, comparativas de versiones de modelo y flujos de aprobación/corrección manual. 

El resultado es una **especificación detallada y accionable en Python** (con ejemplos de código y YAML/SQL) para construir NEXUS AI desde cero, sin ambigüedades. Se incluyen diagramas Mermaid de arquitectura, tablas comparativas de enfoques de aprendizaje y riesgos, así como un plan de pruebas, roadmap de desarrollo, criterios de aceptación e inventario de decisiones abiertas. Las referencias citadas provienen de documentación oficial y literatura reciente (2024–2026) en IA y ML (Hugging Face, Ollama, scikit-learn, pgvector, ArXiv, OWASP, Meta-Intelligence, etc.), así como buenas prácticas de seguridad. Esta guía servirá como base para el repositorio y desarrollo efectivo de NEXUS.

## 1. Principios de Aprendizaje de Texto y Modelos

- **Transformers y preentrenamiento**: La arquitectura Transformer (Vaswani et al. 2017) es la base de los LLMs modernos. Modelos preentrenados como GPT, BERT o T5 se entrenan con **aprendizaje auto-supervisado** sobre grandes corpus de texto crudo. Por ejemplo, se utilizan objetivos de enmascaramiento o siguiente palabra para generar datos de entrenamiento automáticamente sin etiquetas humanas. Esto crea una “base de conocimiento” estadístico del lenguaje. Sin embargo, por sí solo no es específico a tareas prácticas, por lo que luego se realiza fine-tuning (ajuste supervisado) en datasets etiquetados. 

- **Tokenización**: Los Transformers procesan texto dividéndolo en subunidades (tokens) mediante algoritmos como Byte-Pair-Encoding (BPE), WordPiece o Unigram (ver librería HuggingFace Tokenizers). Cada token recibe un **ID numérico**. Ejemplo: al tokenizar “inteligencia artificial” se obtienen tokens [`inteligencia`, ` artificial`] (o fragmentos subpalabra). El límite de contexto (máximos tokens) depende del modelo (por ejemplo, 2048, 4096 o más). Si el texto supera ese límite, es necesario segmentarlo. Transformadores de nueva generación admiten contextos ultra-largos (100k+ tokens), pero esto **no elimina el problema de pérdida de atención central**: estudios recientes muestran que con ~200K tokens, un modelo puede “perder” ~30% de información importante en la mitad del contexto.

- **Modelos ligeros vs. grandes**: Para 32 GB de RAM, es crucial elegir modelos adecuados. Modelos grandes (por ejemplo, GPT-4 de 175B parámetros) quedarían fuera de alcance local. En cambio, modelos de ~3–7B parámetros con cuantización pueden ser factibles. Por ejemplo, **DistilBERT (66M parámetros)** es una versión destilada de BERT (110M) que mantiene ~97% del rendimiento usando un 40% menos de memoria. Y Qwen3.5-4B (4.7B parámetros) en formato INT4 ocupa apenas ~5.4 GB (FP16) a 8K contexto, lo cual confirma que modelos B4–7B en INT4/8 pueden caber en 32 GB. También se pueden usar frameworks optimizados: 
  - **LLama.cpp/VLLM** para CPU: ejecutan modelos cuantizados (4–8 bits) con alta eficiencia (estudios muestran que 4–8 bit retiene ~95% de precisión). 
  - **Ollama** en Windows: soporte para GPUs Nvidia/AMD (requiere drivers recientes), puede cargar modelos como Qwen-3.5 o Llama rápidamente. 
  - **Hugging Face Transformers + bitsandbytes/AutoGPTQ** para PyTorch: permiten cargar localmente con INT8/4. 
  - **Triton/cuBLAS/FlashAttention** para GPUs (por ejemplo, Qwen usa FlashAttention-2/3 en HW modernos). 
  - **Multi-threading/compilación JAX/PyTorch** para CPU: se pueden compilar kernels (torch.compile) y usar BLAS optimizado.

- **Cuantización**: Reducir precisión numérica es clave para memoria. Técnicas como INT8 o INT4 suelen reducir por 2–4× el tamaño de modelo con mínima pérdida de precisión. Ej.: cuantizar de FP32 a FP16 ya duplica eficacia de memoria. Con INT8, 1 parámetro ocupa 1 byte (vs 4 bytes en FP32), y se acelera cálculo al usar instrucciones más simples. El estudio “Which Quantization Should I Use?” muestra que 8-bit y aún 4-bit mantienen la mayor parte del rendimiento en tareas estándar. Herramientas: quantización post-entrenamiento (GPTQ, AWQ), y métodos de entrenamiento como QLoRA (fine-tuning con cuantización). Seleccionar entre esquemas depende de trade-off: menor bit = más compresión pero potencialmente más error, según benchmarks.

- **Aprendizaje supervisado vs. no supervisado**:
  - *Supervisado*: se entrena con ejemplos etiquetados (texto + categoría). Es esencial para tareas específicas (clasificación de correos, detección de spam, clasificación de intenciones). Por ejemplo, un clasificador lineal (Regresión Logística) sobre vectores TF-IDF suele ser efectivo como baseline inicial. Scikit-learn proporciona todo lo necesario: 
    ```python
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    pipeline = Pipeline([
        ('tfidf', TfidfVectorizer(max_features=5000)),
        ('clf', LogisticRegression())
    ])
    pipeline.fit(X_train, y_train)
    ```
  - *No supervisado*: descubre patrones sin etiquetas. Útil para análisis exploratorio: detección de clusters de documentos, agrupación de temáticas, deduplicación. Técnicas: clustering (K-means, DBSCAN), búsqueda de tópicos (LDA), detección de anomalías en logs. Permite organizar datos cuando no hay etiquetas previas.
  - *Auto-supervisado*: el modelo genera sus propias señales de entrenamiento (p. ej., prediciendo tokens faltantes). Esto es lo que hacen los Transformers preentrenados. Sirve para construir modelos de base con gran conocimiento estadístico (embedding de palabras, comprensión semántica) sin etiquetado manual.
  - *Aprendizaje por refuerzo / preferencias*: se usa cuando hay una señal de recompensa o preferencia. En NLP reciente destacan técnicas como **Direct Preference Optimization (DPO)**, donde se ajusta el modelo según preferencias humanas (p. ej., respuestas mejor calificadas). También RLHF (Reinforcement Learning with Human Feedback) para alinear LLMs a valores humanos. ALAS (Atreja et al. 2026) muestra que combinar SFT (supervised fine-tuning) con DPO permite actualizar un LLM con datos recientes sin intervención humana, mejorando su precisión en dominios emergentes.

- **Métodos híbridos**: Los sistemas modernos combinan RAG (recuperación de información en tiempo real) con aprendizaje paramétrico. Por ejemplo, ALAS recupera datos web actualizados y luego genera pares QA para **fine-tuning** iterativo. RAG (Lewis et al. 2020) entrega a los LLMs contexto fresco (p.ej. pasajes relevantes), pero **no modifica los pesos del modelo**. En cambio, NEXUS también debe **asimilar conocimiento** en su “cerebro”: aplicar entrenamiento incremental (por ejemplo, LoRA) para que su modelo interno represente la nueva información, no solo dependa de la indexación externa. Estudios demuestran que depender sólo de RAG limita la **memoria a largo plazo** del sistema. La propuesta es usar RAG para respuestas inmediatas y referencias, y aprendizaje supervisado/continual para actualizar el modelo de manera controlada.

- **Continual Learning (aprendizaje continuo)**: Adaptar un modelo secuencialmente a nuevos datos sin olvidar lo previo es un reto (fenómeno *catastrophic forgetting*). En LLMs, se han desarrollado técnicas de aprendizaje continuo como **LoRA estructurada**. Por ejemplo, el método ProCL (Le et al. 2026) organiza adaptadores LoRA en “slots de memoria” que se activan según la entrada, preservando conocimiento previo mientras se aprende lo nuevo. Esto inspira estrategias para NEXUS: usar adaptadores o módulos adicionales para retener información antigua, integrando nuevos datos de forma selectiva. 

- **Evaluación y métricas**: Para las tareas de texto, se medirán precisión, recall, F1 (macro F1 para multi-clase) y métricas de confianza/calibración (ECE, Brier score). Ejemplo de fórmula: 
  
  $$
  F1 = \frac{2 \times (precisión \times recall)}{precisión + recall}.
  $$

  Además, se implementará **predicción selectiva (abstención)**: el modelo puede abstenerse de responder si su confianza es baja. Estudios en NLP muestran que permitir abstención mejora la estimación de confianza sin aumentar mucho el costo computacional. Se definirán umbrales de confianza (p.ej. Softmax por clase) para cada tarea, y el sistema podrá “pedir ayuda” (consulta humana) cuando esté inseguro.

## 2. Pipeline de Ingesta y Datos

NEXUS recogerá datos de fuentes autorizadas: GitHub, proyectos locales, portafolio web, correo, agendas, YouTube, etc. Para cada fuente se define un conector seguro (API o MCP):

- **Extracción**: Almacenamiento inicial de datos en bruto (repos Git, documentos, correos, mensajes de chat). Se registra *metadatos* (fecha, origen, tipo, credenciales, licencia).
- **Validación y limpieza**: Se aplica `deep scan` de seguridad: escaneo de secretos/PII (tokens, contraseñas) usando regexs y modelos NER. Datos sensibles detectados se separan o anonimizarán (p.ej. reemplazo `{{PERSON_1}}`) y su mapeo se guarda cifrado. También se normaliza texto (Unicode, minúsculas, eliminación de HTML/Markdown), se corrigen codificaciones y se valida el idioma. Esto garantiza calidad y seguridad de la ingesta. 
- **Chunking y Embedding**: Documentos largos se dividen en fragmentos semánticos (párrafos o porventana de tokens) usando por ejemplo spaCy o splitting por límites lógicos. Cada fragmento se transforma en un embedding vectorial (p.ej. con Sentence Transformers o OpenAI embeddings). Estos vectores se insertan en la base de datos vectorial (pgvector) con su metadatos.
- **DataLake y Versionado**: Todo dato procesado se almacena en bases relacionales o en archivos (con timestamps, hash). Se usan tablas dedicadas para versiones: p.ej. cada commit de Git, cada item de portafolio, cada correo etc. Se retienen historiales y se marca la relación entre versiones para poder “rebobinar”. Un registro de *dataset* (tipo JSON) describe la versión actual de cada fuente. Esto permite reproducibilidad y rollback.
- **Etiquetado humano y feedback**: Para tareas supervisadas (intenciones, clasificación, QA, NER), se mantiene un repositorio de ejemplos etiquetados: algunos provienen del creador (ej. correcciones de NEXUS) y otros de terceros autorizados. NEXUS pedirá feedback activo (p.ej. “¿respondí correctamente este correo?”) y almacenará etiquetas de validación. También generará ejemplos sintéticos (p.ej. reescribir inputs con ligeras variaciones) para aumentar cobertura sin comprometer la calidad. 
- **Splits y experimentación**: Los datos limpios se dividen en conjuntos de entrenamiento, validación y prueba, evitando filtración de información (todo correo de un hilo en el mismo split). Un registro de experimentos (MLflow o similar) guarda cada conjunto de datos, las versiones del modelo y los resultados. Los modelos entrenados se registran en un **Model Registry** interno con metadatos: parámetros, fecha, rendimiento. Se preserva trazabilidad completa entre datos, modelos y versiones.

- **Consistencia y drift**: Se implementan monitoreos automáticos: por ejemplo, se calcula la distribución de clases (número de correos spam/ham nuevos vs históricos), medidas estadísticamente (KS-test) para detectar cambio de distribución. Si hay *concept drift* (p.ej. cambia el estilo de correos), se dispara una alerta para re-entrenamiento o ajuste de umbrales. 

- **Manejo de datos externos**: Las fuentes externas (API, web scraping, GitHub) se consideran *no confiables*: NEXUS solo los usa como datos de entrada, **nunca** como instrucciones ejecutables. Por ello, todo dato externo se etiqueta en el grafo de conocimiento con su procedencia y confiabilidad. No se permitirá que contenido externo modifique reglas o permisos internos (véase sección de seguridad).

## 3. Memoria y Grafo de Conocimiento

NEXUS dispondrá de una memoria estructurada y un grafo de conocimiento propio, almacenados de manera persistente:

- **Memoria episódica**: es el registro crudo de eventos e interacciones (“registro de bitácora”). Cada acción, mensaje o cambio relevante se guarda con `id`, `timestamp`, `usuario/propietario`, `contexto` y `resultado`. Ej: “A las 2026-11-15 10:23, se recibió correo X y se clasificó como Y”. Estos registros se almacenan en una tabla (PostgreSQL) tipo append-only, indexados por vector de embedding. Conforme a OSSA Research, es un *event store* donde cada entrada es inmutable. Antes de guardar, la memoria episódica pasa por filtros de PII (similar a la ingesta) y se clasifica por sensibilidad. 

- **Memoria semántica**: almacena conocimiento extraído de episodios. Se formaliza en un grafo o base relacional: entidades (proyectos, servicios, tecnologías, reglas) y relaciones (usa, depende de, se publicó en, etc.). Por ejemplo, de un episodio “push a repo”, se extraen hechos semánticos (“Repositorio X es del propietario”, “Tecnología Y usada en proyecto”). También se agregan hechos externos (metadatos de GitHub, fechas de releases). Cada nodo/relación lleva metadatos: `fuente`, `fecha de inserción/actualización`, `nivel de confianza` (inicialmente bajo para datos externos), `confirmación del usuario`. Siguiendo la arquitectura propuesta, las memorias semántica y procedimental se construyen consolidando episodios mediante un LLM: agrupar eventos y **abstractar reglas** (p.ej. “todos mis proyectos Python usan patrones X”). La conversión episódico→semántico puede automatizarse con prompts al LLM para extraer patrones y agregarlos al grafo. También se pueden incorporar reglas definidas por el usuario como nodos del grafo (v. sección Reglas).

- **Memoria procedimental**: contiene habilidades o procesos (“saber cómo”). Ej: un conjunto de pasos para publicar un vídeo en YouTube. No son datos o hechos, sino acciones. Se almacena como rutinas predefinidas o scripts. Técnicamente, son secuencias de herramientas o código verificadas, etiquetadas con metadatos (versión, autor, variables). Se accede a ellas como subrutinas ejecutables del agente (p.ej. “el componente YouTube publish”).

- **Base de datos y grafo**: Se plantea usar **PostgreSQL** con extensión pgvector para todo el motor de memoria. Ventajas: unifica datos relacionales y vectores en un solo sistema con ACID. pgvector permite hacer *kNN search* con índices HNSW/IVF directamente en SQL, y hacer búsquedas híbridas (vector + full-text) por ejemplo con BM25 y el operador “<->”. La esquema sugerido: tablas para *MemoriaEpisodica*, *MemoriaSemantica*, *MemoriaProcedimental*, *Entidades*, *Relaciones*, *Reglas*, *Identidad*, *Configuración*, *Logs*, etc. Cada tabla lleva campos de auditoría y versionado. Adicionalmente se puede usar un almacén de grafos (Neo4j o tablas de relaciones) para consultas complejas de conectividad. Por ahora, un grafo relacional (tablas con relaciones entre entidades) puede servir, y se puede pasar a Neo4j si el volumen escala. Todo acceso a la base se hará mediante ORM o queries controlados (sin ejecutar código externo).

- **Embeddings en memoria**: Los documentos y episodios se indexan también en una tabla de vectores. Ejemplo: la tabla `documents(id, content, metadata, embedding vector(1536), created_at)`. Un embedding de 1536 floats ocupa ~6 KB en memoria (1536×4 bytes), por lo que 1M de docs serían ~6GB más overhead. Esto es manejable dentro del hardware previsto (32GB). Se usarán modelos de embedding de código abierto (p.ej. `all-MiniLM-L6-v2` de 384 dimensiones para indexado local, o text-embedding-3-small con 1536 dimensiones vía API).  

- **Relaciones y consultas**: El conocimiento se modela en un grafo de alto nivel: nodos para *usuario*, *repositorios*, *canales de YouTube*, *proyectos*, *servicios*, *tecnologías*, etc. y aristas para “usa”, “pertenece a”, “depende de”, “es parte de” o “publicado en”. Por ejemplo: 
  ```
  USUARIO --gestiona--> GitHub
  USUARIO --desarrolla--> ProyectoAutomatizacion
  ProyectoAutomatizacion --usa--> Herramientas-Python
  ProyectoAutomatizacion --documentado en--> PortafolioWeb
  ProyectoYouTube --creado con--> SistemaEdicion
  ```
  Este grafo permite responder consultas complejas: “¿qué proyectos Python tengo?”, “¿qué tecnología recurrente uso?”, “relaciones entre mis canales y mis repositorios”. El grafo almacena también referencias (fuentes) y confianza, y se actualiza con cada ingesta. Por ejemplo, si se detecta una nueva librería en un `requirements.txt`, se añade una relación “usa” con bajo nivel de confianza que el usuario puede confirmar.

- **Seguridad y aislamiento**: Siguiendo las guías de OWASP para MCP y agentes, la memoria se segmenta por tipo (privada del usuario vs pública) y todo contenido externo se etiqueta. No se escribirá código ejecutable directamente desde la memoria; solo referencias que requieren revisión. Además, todo dato PII se maneja según GDPR: se puede “olvidar” borrando claves de cifrado. Los datos sensibles en memoria (episodios personales, credenciales) estarán en compartimentos privados solo accesibles al agente del usuario, nunca expuestos en respuestas sin procesar.

## 4. Sistema de Aprendizaje Incremental

NEXUS implementará un ciclo continuo de aprendizaje en tres flujos integrados: *aprendizaje supervisado tradicional*, *entrenamiento de transformadores locales* y *aprendizaje basado en agentes (feedback)*. Los componentes clave son:

- **Clasificación de intenciones/entidades**: Se entrenarán modelos ligeros para tareas específicas. Ejemplo: clasificar correos por prioridad o detectarlos como **spam/phishing**. Se puede usar `sklearn` con TF-IDF + LogisticRegression, DecisionTree o Naive Bayes como primera instancia. Para tareas más complejas (dialogflow, bot, ruta), se usará un Transformer pequeño (p.ej. XLM-RoBERTa base) finamente ajustado. Lo ideal es **realizar pruebas A/B**: comparar modelo de base (scikit) vs. Transformer con un conjunto pequeño de datos reales. Se recogerán métricas precisas por clase (precisión, recall, F1 macro). Para cada modelo, se guardan ROC/PR curves y calibración (p.ej. usando **temperature scaling** si es necesario). Si un modelo predice con baja confianza (< umbral fijo), NEXUS preguntará al usuario y guardará la respuesta para re-entrenar (aprendizaje activo).

- **Extracción de entidades**: Igual, se aplicarán modelos de reconocimiento de entidades nombradas (NER) para identificar nombres de proyectos, tecnologías o personas en texto. Se usarán pipelines entrenados (p.ej. spaCy o modelos Transformers como `dslim/bert-base-NER`). Las entidades se validan con reglas (listas blancas de nombres permitidos) y luego se agregan al conocimiento. El sistema también puede sugerir nuevas etiquetas al usuario.

- **Embeddings y búsqueda semántica**: NEXUS usará embebdings para hacer RAG y “similarity search” en su base de conocimiento. Por ejemplo, al preguntarle “¿qué proyectos acabas de actualizar?”, NEXUS consultará el índice de embeddings de descripciones de commits y documentos para recuperar los más relevantes. Como la guía de pgvector señala, es posible combinar búsquedas vectoriales con búsquedas textuales tradicionales (BM25) usando técnicas de fusión de ranking. Esto se implementa automáticamente en PostgreSQL usando consultas híbridas (`ORDER BY embedding <-> query_vector` junto con filtros SQL).

- **Fine-tuning local**: Periodicamente (o ante un nuevo conjunto grande de datos), se realizará fine-tuning del modelo de lenguaje local. En vez de re-entrenar completamente (costoso), se emplearán técnicas *parámetro-eficientes* (PEFT) como LoRA o LoCon. Por ejemplo, usando Hugging Face Accelerate + bitsandbytes, se cargaría el modelo base (ej. Qwen4B quantizado) y se aplicaría LoRA para actualizar solo matrices de proyección, dejando el resto fijo. Esto permite incorporar nuevos datos a la red neuronal con bajo overhead. Además, se definirá una **estrategia de conservación**: un buffer de entrenamiento con ejemplos clave de ediciones anteriores, o restricción por factor de estabilidad-plasticidad (por ej. regularización EWC/AGEM) para evitar olvidar tareas previas. El documento “Continual LoRA via program memory” sugiere organizar adaptadores en “slots” de memoria, lo cual inspirará la gestión de LoRAs en NEXUS (por ejemplo, un slot por dominio: “repositorios Git”, otro por “YouTube”, etc., activándose según la fuente de datos).

- **Retroalimentación humana**: El propietario (usuario) revisará periódicamente el contenido aprendido. Por ejemplo, tras proponer nuevas relaciones en el grafo, NEXUS preguntará “¿confirmas que este proyecto usa la biblioteca X?”. También puede presentar resúmenes de “patrones aprendidos” (p.ej. “detecté que todos tus proyectos usan Docker”). El usuario puede entonces confirmar, corregir u olvidar esas inferencias. Cada corrección se añade al conjunto de entrenamiento como etiqueta (positivo o negativo) para refinar los clasificadores o reglas generadas. El sistema registrará estos cambios en el registro de “feedback”.

- **Monitoreo de la performance**: Se mantendrá un dashboard de seguimiento del desempeño de los modelos. Por ejemplo, gráficas de F1 macro por iteración de entrenamiento, histogramas de confianza, *curvas de calibración*. Si se detecta que el modelo general ha empeorado (p.ej. drift en validación cross-fold), se evalúan acciones: reentrenar con más datos o ajustar hiperparámetros. El sistema puede comparar versiones (ej. “Modelo v1.0 vs v1.1” en nuestras métricas). Adicionalmente, cuando NEXUS ejecute un agente (p.ej. para responder correo), se medirá el éxito (tiempo invertido, correcciones posteriores) y estos datos alimentan la memoria y aprendizaje futuro.

- **Recuperación RAG vs Paramétrica**: Como lo enfatiza ALAS, las dos modalidades son complementarias. RAG permite a NEXUS dar respuestas basadas en información actualizada (ideal para hechos recientes), mientras que el fine-tuning paramétrico incorpora conocimiento estable en el propio LLM. En NEXUS, se priorizará la **persistencia del conocimiento**: un dato crítico (p.ej. configuración de un proyecto) que aparece en múltiples fuentes será internalizado en la memoria semántica y, eventualmente, en un modelo de intención (actualización de LoRA). Así evitamos tener que “buscar” siempre en la base. Sin embargo, **nunca reemplazaremos reglas o políticas críticas** (identidad del usuario, permisos) usando solo generación de lenguaje: estas se actualizan explícitamente como configuraciones separadas (ver sección Reglas).

## 5. Motor de Reglas e Identidad

- **Identidad persistente**: En el primer arranque, NEXUS pedirá un nombre para sí mismo y para el usuario. Esto se guarda en la base como datos de identidad (tabla `Identity` y `OwnerProfile`). Por ejemplo: 
  ```yaml
  assistant: { name: "NEXUS", personality: "profesional", language: "es" }
  owner: { name: "Propietario", role: "owner" }
  ```
  Esta identidad es fija y solo puede cambiarse mediante sesión autenticada (nunca desde un conector externo). NEXUS siempre se presentará con su nombre y recordará el nombre del dueño en sus respuestas (“Buenos días, <nombre>. Soy NEXUS.”). Cualquier instrucción externa que intente alterar estos valores será descartada. El OWASP MCP recomienda proteger esas configuraciones fundamentales con control de acceso estricto.

- **Reglas jerárquicas**: NEXUS cuenta con un motor de reglas basadas en condiciones (“*when – then*”) con prioridad. Cada regla consta de campos (ver tabla):

  | Campo        | Descripción                            |
  |--------------|----------------------------------------|
  | ID           | Identificador único (ej. `RULE-001`)   |
  | Nombre       | Breve descripción de la regla          |
  | Ámbito       | Sistema o conector al que aplica       |
  | Disparador   | Evento (p.ej. `antes_de_publicar_video`) |
  | Condición    | Criterios adicionales (tags, metadatos) |
  | Acción       | Qué hacer (p.ej. `requerir_aprobacion`) |
  | Prioridad    | (Alto/Medio/Bajo)                     |
  | Estado       | Activa/Desactivada                     |
  | CreadaPor    | Quién la definió (usualmente `owner`)  |

  Ejemplo en YAML:
  ```yaml
  id: RULE-042
  name: youtube_requerir_revision
  scope:
    agent: youtube_agent
  trigger:
    event: publicar_video
  condition:
    always: true
  action:
    require: user_approval
  priority: alta
  enabled: true
  created_by: owner
  ```

  Las reglas se evalúan en orden de prioridad. OWASP señala que *solo el usuario* (dueño) puede crear o modificar reglas personales. Además existe una capa superior de **permisos fundamentales**: p.ej. “NEXUS nunca podrá auto-asignarse mayor privilegio” o “el perfil del propietario solo lo cambia el dueño autenticado”. No se acepta que datos externos o agentes alteren esas reglas: mecanismos de *verificación y sandbox* lo impiden.

- **Síntesis de reglas por lenguaje natural**: El motor de reglas incluirá procesamiento de lenguaje para traducir instrucciones del usuario a reglas estructuradas. Ej.: el usuario podría decir “cada vez que terminé un proyecto, recuérdame actualizar mi portafolio”. NEXUS interpretará esto y sugerirá la regla correspondiente. Antes de activarla, mostrará cómo la entendió (descripción resumida) y pedirá confirmación. Internamente, se puede usar un pequeño LLM para mapear NL → YAML/Python (similar a parsers o frameworks de DSL). Pero siempre con supervisión humana.

## 6. Arquitectura de Agentes y Ejecución

- **Agentes especializados**: El sistema NEXUS se compondrá de un **Core de Inteligencia** y múltiples agentes de dominio (ver sección anterior). Ejemplos: *GitHub Agent*, *Email Agent*, *YouTube Agent*, *Productivity Agent*, etc. Cada agente tiene acceso limitado a ciertas herramientas y áreas de la memoria, según reglas y permisos. El *Core* actúa como planificador/orquestador: recibe la intención del usuario (o detectada automáticamente) y delega tareas al agente apropiado. 

- **Runtime de agentes**: Cada agente corre en su propio contenedor Docker (según la infraestructura MCP) y se comunica con el Core por RPC (o HTTP interno). Se implementa un **Bucle Sense-Plan-Act**: 
  1. *Sense*: el agente recibe datos (p.ej. un evento de webhook, un mensaje entrante) y lo convierte en una tarea.
  2. *Plan*: pide al LLM central (o subsistema de lógica) elaborar un plan: p.ej. “Quiero responder este correo”, el Email Agent pregunta: “¿qué carpeta es, autor, etiquetas?”.
  3. *Act*: el agente ejecuta acciones permitidas (p.ej. buscar documentos, enviar correo simulado). Para cálculos exactos (fechas, filtros SQL), evita al LLM e invoca código Python confiable (notebook o scripts). Esto separa generación de lenguaje de cómputos matemáticos (integridad y reproducibilidad).
  4. *Verificar*: todo resultado relevante se almacena en memoria de eventos. Si se requiere acción del usuario (aprobación), el plan queda “pendiente” hasta que se confirme.

- **Contratos y toolbox**: Cada herramienta (por ejemplo, `git_checkout`, `query_database`, `generate_report`) tendrá un esquema JSON/Pydantic que define inputs/outputs. El LLM sólo puede llamar a funciones a través de este contrato (por ejemplo, usando un prompt de tipo Function Call). Esto impide inyección de comandos. OWASP recomienda *sandbox* de ejecución: los agentes corren código Python en un entorno controlado (por ejemplo, usando containers ligeros o un sandbox de Python seguro), y nunca ejecutan texto arbitrario de fuentes externas.

- **Limites y presupuesto**: Para evitar bucles infinitos, cada agente y el Core tienen límites de pasos y tokens. P. ej., un plan largo se dividirá en tareas subtareas, y el LLM no recibirá prompts excesivamente grandes. Si un agente no completa una acción, devuelve error al Core para fallback humano. 

- **Eventos y orquestación**: Se emplea un *bus de mensajes ligero* o colas para comunicar eventos (ej. Redis Pub/Sub o RabbitMQ). El Core publica órdenes y escucha resultados. Los agentes suscriben a eventos relevantes (webhooks de GitHub, IMAP de correo, etc.) y publican nuevos eventos tras cada ejecución. Esto permite escalar/monitorizar agilidad y rehacer tareas fallidas.

## 7. Visualización y Dashboard de Aprendizaje

El **Dashboard de Administración** de NEXUS incluirá un “Learning Center” con paneles detallados sobre el estado del aprendizaje:

- **Flujo de ingesta**: Gráficas y tablas que muestran cuántos documentos/eventos se han procesado por fuente (GitHub commits, correos recibidos, videos cargados, etc.), rates por hora/día, porcentajes con fallos de parsing. Botones para reintentar o pausar la sincronización.

- **Calidad de datos**: Estadísticas del dataset: número de instancias por clase (p.ej. correos spam vs no-spam), equilibrio de clases, ejemplos etiquetados vs sin etiquetar. Visualizaciones de *clasificación falsa* con muestras de texto (para ver errores típicos). Barras de frecuencia de tokens o entidades clave. Indicadores de calibración: *reliability diagrams* y *Expected Calibration Error* (ECE) para los clasificadores críticos.

- **Métricas de modelo**: Para cada modelo en servicio, mostrar precisión/recall/F1 por clase y macro F1 general. Además, métricas de regresión y `R^2` si hay componentes de predicción numérica. Historial de curvas de entrenamiento/validación para detectar sobreajuste. Se incluirán *Curvas ROC y PR* interactivas. También información de incertidumbre: porcentaje de casos con abstención (veces que el sistema se rehusó a responder) y su tasa de error vs acierto en el resto.

- **Grafo de conocimiento**: Vista interactiva del Knowledge Graph (integración de D3 o Mermaid). Permite explorar entidades (nodos) y sus conexiones. Filtros por tipo (p.ej. ver solo proyectos y sus lenguajes) y cronología (ver cómo crece el grafo con el tiempo). El grafo debe destacar nodos “recientemente actualizados” y relaciones pendientes de validación. 

- **Aprendizaje y patrones**: Un panel que muestre nuevos patrones descubiertos (“NEXUS ha detectado que X% de tus proyectos usan Y”). Cada patrón puede tener estado: *sugerido*, *confirmado*, *obsoleto*. Muestra evidencia: ejemplos de episodios que lo generaron. El usuario puede marcarlo como válido o rechazarlo. Esto sirve de feedback al motor de aprendizaje.

- **Experimentos y versiones**: Un inventario de modelos entrenados: nombre, configuración (arquitectura, hyperparámetros), datos usados, y sus métricas. Permite comparar cualquier par de modelos con gráficos de comparación (barras, radar, matrices de confusión). Para regresión de versión: e.g. ver cómo cambió el desempeño tras un reentrenamiento. También indicar la versión del LLM base empleado (p.ej. “GPT-2 small fine-tuned v1.2”).

- **Trazabilidad de respuestas**: Al recibir una pregunta/respuesta por chat, el dashboard mostrará qué fuentes de memoria contribuyeron (ej. “esta respuesta se basó en el documento X y el commit Y”), nivel de confianza y recorrido en el grafo de conocimiento. Esto refuerza la transparencia y permite al usuario rastrear el origen de cada inferencia de NEXUS.

- **Alertas**: Panel de notificaciones (drift, errores, reglas violadas, permisions missing). Por ejemplo: “Nuevo commit en repo crítico sin etiqueta de confidencialidad” o “Regla RULE-005 conflictiva, necesita revisión”.

Todos estos datos se exponen vía REST API desde el backend Python, consumidos por un frontend web. Se adoptarán bibliotecas de gráficas (Plotly, D3) y un framework web (p.ej. FastAPI + React) con autenticación. El diseño debe enfatizar la claridad: textos legibles, colores para estados (verde-ok, rojo-error), y capacidad de filtrar/ordenar. Este “Learning Center” hace tangible el progreso de NEXUS y empodera al usuario para supervisarlo.

## 8. Implementación Técnica

### Estructura del Proyecto

Se propone el siguiente árbol de carpetas en Python:

```plaintext
NEXUS-AI/
├── core/                  # Núcleo de orquestación y modelo LLM
│   ├── nexus_core.py      # Manejo de diálogo, planning, herramientas
│   └── llm_interface.py   # Wrappers para modelo local (Ollama, HuggingFace)
│
├── agents/                # Definición de agentes especializados
│   ├── git_agent.py
│   ├── email_agent.py
│   ├── youtube_agent.py
│   └── ...               # otros agentes (productividad, portfolio, etc.)
│
├── knowledge/             # Razonamiento simbólico y grafos
│   ├── kg_manager.py      # CRUD de entidades/relaciones
│   ├── memory_manager.py  # Episódico y semántico
│   └── ingestor.py        # Extracción/normalización de fuentes
│
├── learning/              # Pipelines de entrenamiento y evaluación
│   ├── datasets.py       # Splits y estadísticas
│   ├── trainers.py       # Funciones de entrenamiento (scikit, HF, LoRA)
│   ├── evaluators.py     # Métricas y calibración
│   └── experiments/      # Scripts/MLflow para pruebas
│
├── rules/                 # Motor de reglas
│   ├── rule_engine.py     # Aplicación de reglas a eventos
│   ├── rule_parser.py     # Traducción NL → estructura de regla
│   └── rules_store.sql    # Esquema/ejemplos de tabla de reglas
│
├── mcp/                   # Gateway para conectores externos (MCP, HTTP)
│   ├── gateway.py         # Enrutador de servidores MCP
│   └── servers/          # Implementaciones de servidores (GitHub, Calendar, etc.)
│
├── dashboard/             # API y Frontend del panel de control
│   ├── api.py             # Endpoints REST para métricas
│   └── frontend/         # Código web (React/Vue)
│
├── memory_db/             # Base de datos PostgreSQL + pgvector (o migraciones)
│   ├── models.sql         # Esquema de tablas (identidad, reglas, memorias, etc.)
│   ├── migrations/       # Herramienta Alembic o similar
│   └── seed_data.sql      # Datos iniciales (vacío o básicos)
│
├── security/              # Configuraciones de seguridad (permiso, escaneo, etc.)
│   └── secrets_filter.py  # Utilitarios para PII/secret scanning
│
├── docs/                  # Documentación de usuario y desarrollador
├── tests/                 # Pruebas unitarias, integración y seguridad
└── Dockerfile             # Imagen base (Windows con WSL2 o Linux según disponibilidad)
```

### Tecnología y Dependencias

- **Python 3.10+** como lenguaje principal. Uso intensivo de `transformers`, `torch` (o alternativas como `SentenceTransformers`), `scikit-learn`, `psycopg2`/`asyncpg` para BD. 
- **PostgreSQL 16 + pgvector 0.8.0**: soporta índices HNSW y almacenamiento vector. Alternativa: *Neo4j* u otra DB de grafos si crece mucho el volumen de relaciones (actualmente no se necesita por complejidad menor).
- **Librerías de agente**: `jsonschema`/`pydantic` para validar inputs JSON, `docker` para orquestar contenedores, `requests`/`aiohttp` para APIs, MCP SDK oficial para registrar y descubrir herramientas.
- **Modelo base**: Ollama se mencionó, pero también se puede usar un modelo PyTorch puro. Para 32 GB sin GPU, se evaluará inicialmente un modelo ~4B cuantizado (por ejemplo, `Qwen2-4B` o `Mistral-7B-8bit` si VRAM lo permite). Como candidato prudente: **GPT-J 6B** o **LLaMA2-7B** en int4 (~3–5GB) para CPU. LoRA requiere entorno con GPU o CPU con bnb.
- **Almacenamiento de archivos**: S3 local (minIO) o simple `~/data` con snapshot automático, para datos no relacionales (archivos grandes, multimedia).
- **Herramientas ML Ops**: *MLflow* o *Weights & Biases* para tracking de experimentos. *Prometheus/Grafana* para métricas de servicio (uso de CPU/RAM, latencia de consultas).
- **Seguridad**: certificados TLS para comunicaciones web; política de CORS restrictiva; CSP para frontend. Basado en OWASP MCP, se seguirá el principio de *least privilege* (cada servidor MCP con token mínimo). Las credenciales (OAuth tokens) se guardarán cifradas (por ejemplo, con **HashiCorp Vault** o KMS local). Todos los logs se auditan con *trace IDs* para trazabilidad.

### Plan de Desarrollo por Fases (MVP)

1. **Capa Central y Chat**: Implementar el **NEXUS Core**. Crear chat básico (CLI o web) que llame a un modelo LLM local (p.ej. Ollama Qwen2-4B) para responder con contexto limitado. Test: preguntar cosas genéricas, probar parrot. Luego integrar memoria estática mínima (identidad, nombre usuario) y probar que recuerda su nombre.

2. **Memoria Episódica**: Montar PostgreSQL + pgvector. Hacer que cada mensaje de chat se guarde en la tabla de episodios con un embedding. Poder recuperar los N mensajes más similares dado un query. Validar con ejemplos de prueba.

3. **Primer Agente Especializado**: Por ejemplo, **GitHub Agent**. Conectar a una cuenta de prueba (permiso readonly). Traer un repo autorizado, leer README/código. Indexarlos en la memoria (dibujar procedimientos de ingestión). Desde el chat, preguntar “¿Qué repositorios tengo?”, validar que extrae la lista. Probar relaciones: detectar lenguaje predominante, etc.

4. **Motor de Reglas y Configuración Inicial**: Implementar reglas básicas (ej. impedir que NEXUS ejecute herramientas sin permiso) y onboarding (solicitar nombre IA y usuario). Guardar en BD y usar en las respuestas del Core.

5. **Aprendizaje de Texto Superficial**: Construir pipeline de clasificación supervisada. Ejemplo: juntar correos etiquetados manualmente (spam/no-spam), entrenar modelo con scikit, integrar en Email Agent. Medir F1, calibrar, desplegar. Conectar el dashboard para mostrar métricas. 

6. **Memory Graph Core**: Poblar núcleo del Knowledge Graph con ejemplos (nodos, aristas). Mostrar en el dashboard. Permitir creación manual de entidades. Test: “¿Qué relaciones hay con el proyecto X?” y comprobar el grafo.

7. **Integraciones Adicionales**: Conectar otras fuentes (YouTube, Agenda). Por ahora solo lectura. Agregar sus datos a la memoria. Verificar que el Core puede usar este contexto para responder preguntas “¿Qué vídeos publiqué la semana pasada?”.

8. **Voice Interface (opcional)**: Si hay tiempo y recursos, agregar reconocimiento de voz local (por ejemplo, Vosk o Silero) y síntesis (Coqui TTS). Esto permite un modo “conversación hablada”. No es esencial para MVP textual.

### Riesgos y Consideraciones

- **Capacidad de hardware**: Aún falta confirmar CPU/GPU y VRAM. Podemos simular CPU-only con 8-thread en pruebas. Riesgo: modelos demasiado grandes no funcionarán. Mitigación: probar primero con 3B-4B en int4/8.
- **Separación de contextos**: Ensamblar muchos datos en prompts puede sobrecargar el LLM (ventana de contexto limitada). Debemos usar RAG y Memory Retrieval en lugar de prompts muy largos. Diseñar el "context window management" para que NEXUS nunca le pase al modelo más del límite de tokens.
- **Catastrophic forgetting**: Cada vez que actualicemos el modelo, corremos el riesgo de perder conocimiento previo. Solución: usar PEFT (LoRA), adjuntar memoria de ejemplos antiguos (rehearsal), y evaluación cruzada. Además, se mantendrán políticas “congeladas” (reglas) que el modelo no alterará con entrenamiento.
- **Seguridad de MCP**: Evaluar plugins externos solo tras revisión. OWASP sugiere vetos estrictos a código retornado desde herramientas. Se configurarán entornos aislados (Docker) y políticas de acceso mínimo.
- **Privacidad y GDPR**: Dado que NEXUS puede almacenar data personal (correos, calendario), se implementará borrado de “derecho al olvido”: todas las memorias asociadas a un individuo (p.ej. email del usuario) se identifican y eliminan tanto de la DB como de la memoria vectorial (reindexar sin esos vectores). Este proceso debe poder ejecutarse a petición del usuario.
- **Sesgo y calidad de respuestas**: El modelo LLM local puede alucinar. NEXUS priorizará fuentes verificables (mostrar citas de documentos). Ninguna acción sensible (p.ej. borrar archivos, enviar correos) se hará sin confirmación del usuario, aun si el modelo “cree” tener permiso. 

## 9. Bibliografía Seleccionada

- Gutiérrez et al. (ICML 2025) “From RAG to Memory: Non-Parametric Continual Learning for LLMs”: describe cómo RAG es dominante pero limita la flexibilidad de memoria, y propone combinar embeddings con grafos de conocimiento.
- Le et al. (ICLR 2026) “ProCL: Continual LoRA with Program Memory”: introduce adaptadores LoRA organizados como “slots” de memoria para evitar el olvido catastrófico en LLMs.
- Atreja (2026) “ALAS: Autonomous Learning Agent for Self-Updating LLMs”: pipeline modular que recupera información, genera Q&A para SFT y DPO, consiguiendo que un modelo LLM actualice su base de conocimientos con mínima intervención humana. Destaca el contraste RAG vs entrenamiento.
- Meta-Intelligence (2025) “Context Engineering Guide”: concluye que sistemas multi-agente requieren **memoria episódica, semántica y de trabajo** para acumular conocimiento. Advierte sobre problemas de contexto muy largo en Transformers.
- DatasOps (2026) “Vector Search with pgvector”: guía práctica sobre indexación de embeddings en Postgres. Explica ventajas de pgvector (ACID, joins SQL) y patterns de búsqueda semántica e híbrida.
- OSSA Research “Agent Memory Architectures” (2026): arquitectura de memoria dividida en episódica (eventos), semántica (conocimiento) y procedimental (habilidades). Describe el proceso de consolidación de memoria episódica a semántica usando LLM.
- OWASP MCP Security Cheat Sheet (2024): recomendaciones de seguridad para integraciones MCP, enfatizando el “least privilege” y revisiones de esquemas de herramientas para prevenir inyecciones.
- Hugging Face Course (2026): explica que los Transformers se preentrenan auto-supervisados, y que existen modelos destilados como DistilBERT (40% menos memoria) que conservan ~97% de precisión.
- ACL 2021 “The Art of Abstention” (Xin et al.): en NLP, permitir que clasificadores “se abstengan” en ejemplos de baja confianza mejora la fiabilidad del sistema.
- Kurt et al. (ArXiv 2026) sobre cuantización: demuestra que reducciones a 8-bit o 4-bit mantienen la mayor parte del desempeño mientras disminuyen el uso de memoria ~2–4×.
- APXML Qwen3.5-4B Specs (2026): datos empíricos sobre requerimientos de memoria de un LLM de 4B parametros en INT4. 

**Observación**: Donde no hay cita directa, se han incorporado recomendaciones basadas en las fuentes. Todo lo documentado aquí es una **propuesta de diseño**; algunos elementos (p.ej. dimensionamiento preciso de modelos, interfaz de usuario) deberán confirmarse con pruebas en el hardware real. Las referencias están anotadas con fuente y líneas para mayor claridad.

