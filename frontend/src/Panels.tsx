import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Fact, type Feedback, type Folder, type Health, type ModelEntry, type Tool } from "./api";
import { INTENT_LABEL } from "./format";

function useLoad<T>(load: () => Promise<T>, everyMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => {
    load().then((d) => { setData(d); setError(null); }).catch((e) => setError(e instanceof ApiError ? e.code : "sin conexión"));
  }, [load]);
  useEffect(() => {
    reload();
    if (!everyMs) return;
    const t = setInterval(reload, everyMs);
    return () => clearInterval(t);
  }, [reload, everyMs]);
  return { data, error, reload };
}

function Gauge({ label, used, total, unit = "GB" }: { label: string; used: number; total: number; unit?: string }) {
  const pct = total ? Math.min(100, Math.round((used / total) * 100)) : 0;
  return (
    <div className="gauge">
      <div className="gauge-head"><span>{label}</span><span>{total ? `${used.toFixed(1)} / ${total.toFixed(1)} ${unit}` : "no disponible"}</span></div>
      <div className="gauge-bar" role="meter" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label={label}>
        <i style={{ width: `${pct}%` }} className={pct > 85 ? "hot" : ""} />
      </div>
    </div>
  );
}

const loadHealth = () => api.health();

export function SystemPanel() {
  const { data: h, error } = useLoad<Health>(loadHealth, 10000);
  if (error) return <p className="error">{error}</p>;
  if (!h) return <p className="muted">leyendo telemetría…</p>;
  const hw = h.components.hardware;
  const m = h.components.model;
  return (
    <div className="panel">
      <p className={`led led-${h.status}`}>sistema {h.status === "ok" ? "operativo" : "degradado"}</p>
      <dl className="kv">
        <dt>base de datos</dt><dd>{h.components.database}</dd>
        <dt>modelo</dt><dd>{m.active ?? m.name.replace("gguf:", "")} · {m.status}</dd>
        <dt>embeddings</dt><dd>{h.components.embeddings.name?.split("/").pop() ?? "solo texto completo"}</dd>
        <dt>CPU</dt><dd>{hw.cpu_cores} hilos</dd>
        <dt>GPU</dt><dd>{hw.gpu ?? "sin GPU dedicada"}</dd>
      </dl>
      <Gauge label="RAM" used={hw.ram_total_gb - hw.ram_free_gb} total={hw.ram_total_gb} />
      <Gauge label="VRAM" used={hw.vram_total_gb - hw.vram_free_gb} total={hw.vram_total_gb} />
      {m.candidates && (
        <>
          <h3>cadena de modelos</h3>
          <ol className="chain">
            {m.candidates.map((c) => (
              <li key={c.name} className={`chain-${c.status}`} title={c.reason ?? ""}>
                <span>{c.name.replace("gguf:", "")}</span>
                <span>{c.status}{c.gpu_layers !== null ? ` · ${c.gpu_layers === -1 ? "todas" : c.gpu_layers} capas GPU` : ""}</span>
              </li>
            ))}
          </ol>
        </>
      )}
    </div>
  );
}

const loadTools = () => api.tools();

export function ConnectorsPanel() {
  const { data, error, reload } = useLoad(loadTools);
  const act = async (id: string, a: "approve" | "disable") => { await api.toolAction(id, a); reload(); };
  if (error) return <p className="error">{error}</p>;
  return (
    <div className="panel">
      <p className="muted">Los conectores externos empiezan en revisión: nada se usa hasta que lo apruebas.</p>
      <ul className="tools">
        {data?.tools.map((t: Tool) => (
          <li key={t.tool_id} className={`tool tool-${t.status}`}>
            <div><strong>{t.tool_id}</strong><span className="chip">{t.risk_level}</span><span className={`chip st-${t.status}`}>{t.status}</span></div>
            <p>{t.description}</p>
            {t.connector_id !== "internal" && (
              <div className="row">
                {t.status !== "enabled" && <button onClick={() => act(t.tool_id, "approve")}>Aprobar</button>}
                {t.status === "enabled" && <button className="ghost" onClick={() => act(t.tool_id, "disable")}>Desactivar</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const loadFolders = () => api.folders();

export function KnowledgePanel() {
  const { data, error, reload } = useLoad(loadFolders, 15000);
  const [note, setNote] = useState<string | null>(null);
  const [path, setPath] = useState("");
  const [interval, setIntervalMin] = useState("60");

  async function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    setNote(`indexando ${file.name}…`);
    try {
      const r = await api.upload(file);
      setNote(`${file.name}: ${r.chunks} fragmentos${r.ocr_used ? " · OCR" : ""}${r.deduplicated ? " · ya estaba" : ""}` +
              `${r.redactions.length ? ` · secretos redactados: ${r.redactions.join(", ")}` : ""}`);
    } catch (err) { setNote(`${file.name}: ${err instanceof ApiError ? err.code : "error"}`); }
  }

  async function addFolder(e: { preventDefault(): void }) {
    e.preventDefault();
    try {
      await api.addFolder(path.trim(), interval ? Number(interval) : null);
      setPath("");
      setNote("carpeta registrada");
      reload();
    } catch (err) { setNote(err instanceof ApiError ? `carpeta: ${err.code}` : "error"); }
  }

  return (
    <div className="panel">
      <label className="drop">
        <input type="file" onChange={upload} accept=".pdf,.docx,.xlsx,.csv,.txt,.md,.html,.json,.png,.jpg,.jpeg,.tiff,.bmp,.webp" />
        <span>Subir documento</span><small>PDF, Word, Excel, imágenes con OCR…</small>
      </label>
      {note && <p className="note" role="status">{note}</p>}
      <h3>carpetas vigiladas</h3>
      <form className="folder-form" onSubmit={addFolder}>
        <label htmlFor="folder" className="sr-only">Ruta de carpeta</label>
        <input id="folder" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:/ruta/autorizada" />
        <label htmlFor="every" className="sr-only">Intervalo en minutos</label>
        <select id="every" value={interval} onChange={(e) => setIntervalMin(e.target.value)}>
          <option value="">manual</option><option value="15">15 min</option><option value="60">1 h</option><option value="1440">1 día</option>
        </select>
        <button disabled={!path.trim()}>Añadir</button>
      </form>
      {error && <p className="error">{error}</p>}
      <ul className="folders">
        {data?.sources.map((f: Folder) => (
          <li key={f.source_id}>
            <div><strong>{f.display_name}</strong>{f.status !== "active" && <span className="chip st-disabled">inactiva</span>}
              <span className="chip">{f.files_indexed} archivos</span></div>
            <code>{f.path}</code>
            <p className="muted">
              {f.last_run ? `${f.last_run.status} · +${f.last_run.n_indexed} =${f.last_run.n_unchanged} ⊘${f.last_run.n_skipped} ✕${f.last_run.n_failed} −${f.last_run.n_removed}` : "sin sincronizar"}
              {" · "}{f.sync_policy.interval_minutes ? `cada ${f.sync_policy.interval_minutes} min` : "manual"}
            </p>
            {f.status === "active" && (
              <button className="ghost" onClick={async () => { await api.syncFolder(f.source_id); setTimeout(reload, 1500); }}>Sincronizar</button>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

const loadFeedback = () => api.feedbackList("pending");
const loadModels = () => api.models();

/** Learning Center mínimo (Doc 04 §10, TL §8): revisar correcciones, reentrenar, comparar y promover. */
export function LearningPanel() {
  const fb = useLoad(loadFeedback);
  const models = useLoad(loadModels, 8000);
  const [note, setNote] = useState<string | null>(null);

  const review = async (f: Feedback, d: "approve" | "reject") => { await api.reviewFeedback(f.feedback_id, d); fb.reload(); };
  async function train() {
    setNote("entrenando… (aparecerá como candidato)");
    try { await api.train(); setTimeout(models.reload, 3000); } catch (e) { setNote(e instanceof ApiError ? e.code : "error"); }
  }
  async function promote(m: ModelEntry) {
    try { await api.promote(m.id); setNote(`${m.version} activo`); models.reload(); }
    catch (e) { setNote(e instanceof ApiError ? `no promovido: ${e.code}` : "error"); }
  }
  const f1 = (x?: number) => (x === undefined ? "—" : x.toFixed(3));

  return (
    <div className="panel">
      <p className="muted">Tus correcciones no cambian el modelo: las revisas, se reentrena aparte y solo promueves si mejora.</p>
      <h3>correcciones pendientes</h3>
      {fb.error && <p className="error">{fb.error}</p>}
      {!fb.data?.feedback.length && <p className="muted">ninguna</p>}
      <ul className="tools">
        {fb.data?.feedback.map((f) => (
          <li key={f.feedback_id} className="tool">
            <p>«{f.text}»</p>
            <div><span className="chip">{INTENT_LABEL[f.predicted_label ?? ""] ?? "—"}</span>→<span className="chip st-enabled">{INTENT_LABEL[f.corrected_label]}</span></div>
            <div className="row">
              <button onClick={() => review(f, "approve")}>Usar para entrenar</button>
              <button className="ghost" onClick={() => review(f, "reject")}>Descartar</button>
            </div>
          </li>
        ))}
      </ul>
      <h3>modelos de intención</h3>
      <button className="ghost" onClick={train}>Reentrenar con mis correcciones</button>
      {note && <p className="note" role="status">{note}</p>}
      {models.data && !models.data.active_intent && models.data.models.some((m) => m.status === "active") && (
        <p className="error" role="alert">El modelo activo no se puede cargar (archivo ausente o modificado): NEXUS está usando solo reglas. Promueve otro candidato.</p>
      )}
      <ul className="tools">
        {models.data?.models.filter((m) => m.status !== "retired").map((m) => (
          <li key={m.id} className={`tool tool-${m.status === "active" ? "enabled" : "review"}`}>
            <div><strong>{m.version}</strong><span className={`chip ${m.status === "active" ? "st-enabled" : "st-review"}`}>{m.status}</span></div>
            <dl className="kv">
              <dt>híbrido</dt><dd>{f1(m.metrics.test.hybrid_macro_f1)} F1 · reglas {f1(m.metrics.test.baseline_rules_macro_f1)}</dd>
              <dt>validación</dt><dd>{m.metrics.cross_validation ? `${f1(m.metrics.cross_validation.macro_f1_mean)} ± ${f1(m.metrics.cross_validation.macro_f1_std)}` : "—"}</dd>
              {m.metrics.external_eval && <><dt>examen GALA</dt><dd>{Math.round(m.metrics.external_eval.hybrid_accuracy * 100)} % de {m.metrics.external_eval.examples} frases nunca vistas · reglas {Math.round(m.metrics.external_eval.rules_accuracy * 100)} %</dd></>}
              <dt>datos</dt><dd>{m.metrics.dataset.examples} ejemplos · {m.metrics.dataset.feedback_examples ?? 0} tuyos</dd>
            </dl>
            {m.status === "candidate" && <div className="row"><button onClick={() => promote(m)}>Promover</button></div>}
          </li>
        ))}
      </ul>
    </div>
  );
}

const loadSuggested = () => api.facts("suggested");
const loadConfirmed = () => api.facts("confirmed");

/** M3 (Doc 03 §6.1, §9.2, §12): lo que NEXUS cree saber. Solo lo confirmado se usa como dato. */
export function MemoryPanel() {
  const pending = useLoad(loadSuggested, 8000);
  const known = useLoad(loadConfirmed);
  const [note, setNote] = useState<string | null>(null);
  async function review(f: Fact, decision: "confirm" | "reject", replace = false) {
    try { await api.reviewFact(f.fact_id, decision, replace); pending.reload(); known.reload(); setNote(null); }
    catch (e) { setNote(e instanceof ApiError ? e.code : "error"); }
  }
  const triple = (f: Fact) => <p className="triple"><strong>{f.subject}</strong> <span>{f.predicate.replace(/_/g, " ")}</span> {f.object}</p>;
  return (
    <div className="panel">
      <p className="muted">Lo que me dices con «recuerda que…» queda aquí. Solo uso como dato lo que confirmas.</p>
      {note && <p className="error" role="alert">{note}</p>}
      <h3>por confirmar</h3>
      {pending.error && <p className="error">{pending.error}</p>}
      {!pending.data?.facts.length && <p className="muted">nada pendiente</p>}
      <ul className="tools">
        {pending.data?.facts.map((f) => (
          <li key={f.fact_id} className="tool tool-review">
            {triple(f)}
            {f.evidence[0]?.quote && <p className="muted quote">«{f.evidence[0].quote}»</p>}
            {f.conflicts.map((c) => <p key={c} className="conflict">contradice: {c}</p>)}
            <div className="row">
              {f.conflicts.length ? (<>
                <button onClick={() => review(f, "confirm", true)}>Reemplazar</button>
                <button className="ghost" onClick={() => review(f, "confirm")}>Mantener ambos</button>
              </>) : <button onClick={() => review(f, "confirm")}>Confirmar</button>}
              <button className="ghost" onClick={() => review(f, "reject")}>Descartar</button>
            </div>
          </li>
        ))}
      </ul>
      <h3>confirmado</h3>
      {!known.data?.facts.length && <p className="muted">todavía nada</p>}
      <ul className="tools">
        {known.data?.facts.map((f) => <li key={f.fact_id} className="tool tool-enabled">{triple(f)}</li>)}
      </ul>
    </div>
  );
}
