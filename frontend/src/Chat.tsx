import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, FINAL, followTask, type Approval, type Identity, type Message, type Source, type TaskStatus } from "./api";
import { INTENT_LABEL, RichText, sourceLabel, STATUS_LABEL, warningLabel } from "./format";

// Etapas reales del Doc 02 §7.1 que se encienden por SSE. queued+running se muestran juntas.
const STAGES: { key: string; label: string; states: TaskStatus[] }[] = [
  { key: "cls", label: "clasificar", states: ["classifying"] },
  { key: "ctx", label: "contexto", states: ["context_building"] },
  { key: "plan", label: "planificar", states: ["planning"] },
  { key: "val", label: "validar", states: ["plan_validating", "awaiting_approval"] },
  { key: "run", label: "ejecutar", states: ["queued", "running"] },
  { key: "ver", label: "verificar", states: ["verifying"] },
];

// Como los «/» de GALA en Primitivo. Los resuelve el servidor salvo /nueva (solo interfaz).
const COMMANDS = [
  { cmd: "/resumir", desc: "Resume esta conversación", arg: false },
  { cmd: "/fuentes", desc: "Responde solo con tus documentos y la memoria confirmada", arg: true },
  { cmd: "/recuerda", desc: "Anota un dato en la memoria, como sugerencia", arg: true },
  { cmd: "/nueva", desc: "Empieza una conversación nueva", arg: false },
  { cmd: "/ayuda", desc: "Lista los comandos", arg: false },
];

/** Doc 03 §3.5: la identidad se fija aquí (API autenticada), nunca desde el chat. */
function Onboarding({ current, onDone }: { current: Identity; onDone: (i: Identity) => void }) {
  const [ai, setAi] = useState(current.assistant_name);
  const [me, setMe] = useState(current.owner_name ?? "");
  const [error, setError] = useState<string | null>(null);
  async function save(e: { preventDefault(): void }) {
    e.preventDefault();
    try { onDone(await api.putIdentity(ai.trim(), me.trim())); }
    catch (err) { setError(err instanceof ApiError ? err.code : "No se pudo guardar"); }
  }
  return (
    <form className="onboarding" onSubmit={save}>
      <label>¿Cómo me llamo?<input value={ai} maxLength={40} onChange={(e) => setAi(e.target.value)} /></label>
      <label>¿Y tú?<input value={me} maxLength={60} autoFocus onChange={(e) => setMe(e.target.value)} /></label>
      <button disabled={!ai.trim() || !me.trim()}>Guardar</button>
      {error && <p className="error" role="alert">{error}</p>}
    </form>
  );
}

type Turn = Message & { live?: TaskStatus[]; approvals?: Approval[] };

function Ribbon({ seen, status }: { seen: TaskStatus[]; status: TaskStatus | null }) {
  const reached = (s: TaskStatus[]) => s.some((x) => seen.includes(x));
  const current = status && STAGES.findIndex((st) => st.states.includes(status));
  const final = status && FINAL.includes(status) && status !== "awaiting_approval";
  return (
    <ol className="ribbon" aria-label="Progreso de la tarea">
      {STAGES.map((st, i) => (
        <li key={st.key} className={[reached(st.states) ? "lit" : "", !final && current === i ? "now" : ""].join(" ")}>
          <span>{st.label}</span>
        </li>
      ))}
      <li className={`end ${final ? `lit end-${status}` : ""}`}>
        <span>{final ? STATUS_LABEL[status!] : "resultado"}</span>
      </li>
    </ol>
  );
}

function ApprovalCard({ a, onDecide }: { a: Approval; onDecide: (id: string, d: "approve" | "reject") => void }) {
  const [busy, setBusy] = useState(false);
  const mins = Math.max(0, Math.round((new Date(a.expires_at).getTime() - Date.now()) / 60000));
  return (
    <section className={`permit risk-${a.risk_level}`} aria-label={`Aprobación pendiente para ${a.tool_id}`}>
      <header>
        <span className="permit-tag">permiso de trabajo</span>
        <span className="permit-exp">caduca en {mins} min</span>
      </header>
      <h4>{a.tool_id}</h4>
      <dl>
        <dt>riesgo</dt><dd>{a.risk_level.replace("_", " ")}{a.reversible ? " · reversible" : " · NO reversible"}</dd>
        {Object.entries(a.arguments).map(([k, v]) => (
          <div key={k} className="arg"><dt>{k}</dt><dd>{typeof v === "string" ? v : JSON.stringify(v)}</dd></div>
        ))}
      </dl>
      {a.status === "pending" ? (
        <div className="permit-actions">
          <button className="btn-approve" disabled={busy} onClick={() => { setBusy(true); onDecide(a.approval_id, "approve"); }}>
            Aprobar
          </button>
          <button className="btn-reject" disabled={busy} onClick={() => { setBusy(true); onDecide(a.approval_id, "reject"); }}>
            Rechazar
          </button>
        </div>
      ) : <p className="permit-done">decisión registrada · {a.status}</p>}
    </section>
  );
}

function Sources({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  const unique = [...new Map(sources.map((s) => [s.source_ref, s])).values()];
  return (
    <ul className="sources" aria-label="Fuentes">
      {unique.map((s) => <li key={s.source_ref} title={`${s.source_ref} · ${new Date(s.retrieved_at).toLocaleString()}`}>{sourceLabel(s.source_ref)}</li>)}
    </ul>
  );
}

/** T5: lo que entendió el clasificador y cómo corregirlo (la corrección va a revisión, no al modelo). */
function IntentTag({ taskId, label }: { taskId: string; label: string }) {
  const [open, setOpen] = useState(false);
  const [sent, setSent] = useState<string | null>(null);
  async function correct(to: string) {
    try { await api.feedback(taskId, to); setSent(`corregido a «${INTENT_LABEL[to]}» · pendiente de tu revisión`); }
    catch (e) { setSent(e instanceof ApiError ? e.code : "error"); }
    setOpen(false);
  }
  if (sent) return <span className="chip intent">{sent}</span>;
  return (
    <span className="intent-wrap">
      <span className="chip intent" title="Clase que decidió el clasificador">entendí: {INTENT_LABEL[label] ?? label}</span>
      {!open ? <button className="link small" onClick={() => setOpen(true)}>corregir</button> : (
        <select aria-label="Clase correcta" defaultValue="" onChange={(e) => e.target.value && correct(e.target.value)}>
          <option value="" disabled>¿qué era?</option>
          {Object.entries(INTENT_LABEL).filter(([k]) => k !== label && k !== "unknown").map(([k, v]) =>
            <option key={k} value={k}>{v}</option>)}
        </select>
      )}
    </span>
  );
}

function Bubble({ t, name, onDecide, onCancel }: { t: Turn; name: string; onDecide: (id: string, d: "approve" | "reject") => void;
                                                 onCancel: (taskId: string) => void }) {
  if (t.role === "user") return <article className="turn user"><RichText text={t.content} /></article>;
  const working = !t.task_status || !FINAL.includes(t.task_status);
  return (
    <article className={`turn nexus status-${t.task_status ?? "running"}`} aria-busy={working}>
      {(t.live?.length || working) && <Ribbon seen={t.live ?? []} status={t.task_status} />}
      {t.approvals?.length ? <p className="prose">Necesito tu aprobación antes de hacer esto:</p>
        : t.content ? <div className="prose"><RichText text={t.content} /></div>
        : <p className="thinking" role="status">{name} está trabajando…</p>}
      {t.approvals?.map((a) => <ApprovalCard key={a.approval_id} a={a} onDecide={onDecide} />)}
      <footer>
        {t.request_class && t.task_id && !working && <IntentTag taskId={t.task_id} label={t.request_class} />}
        {t.warnings.map((w) => <span key={w} className="chip warn" title={w}>{warningLabel(w)}</span>)}
        <Sources sources={t.sources} />
        {working && t.task_id && <button className="link" onClick={() => onCancel(t.task_id!)}>cancelar</button>}
      </footer>
    </article>
  );
}

export function Chat({ conversationId, onConversation, onNew }: { conversationId: string | null;
                                                                 onConversation: (id: string) => void; onNew: () => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lastIds = useRef<Record<string, number>>({});
  const end = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const [who, setWho] = useState<Identity | null>(null);
  const [naming, setNaming] = useState(false);
  const [sourcesOnly, setSourcesOnly] = useState(false);
  useEffect(() => { api.identity().then(setWho).catch(() => {}); }, []);
  const name = who?.assistant_name ?? "NEXUS";
  const matches = draft.startsWith("/") && !draft.includes(" ")
    ? COMMANDS.filter((c) => c.cmd.startsWith(draft.toLowerCase())) : [];
  const pick = (c: (typeof COMMANDS)[number]) => { setDraft(c.cmd + (c.arg ? " " : "")); box.current?.focus(); };

  const createdHere = useRef<string | null>(null);
  useEffect(() => {
    if (!conversationId || conversationId === createdHere.current) return;  // la recién creada ya está en pantalla
    api.conversation(conversationId).then((c) => setTurns(c.messages)).catch((e) => setError(String(e.code ?? e)));
  }, [conversationId]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [turns]);

  const patch = (taskId: string, f: (t: Turn) => Turn) =>
    setTurns((ts) => ts.map((t) => (t.role === "assistant" && t.task_id === taskId ? f(t) : t)));

  const track = useCallback(async (taskId: string, afterApproval = false) => {
    try {
      let task;
      // Se sigue escuchando hasta un estado FINAL de verdad. Visto en navegador: tras aprobar, el stream se
      // abría con la tarea aún en awaiting_approval (cierra al instante) y la tarea ya estaba en `queued` al
      // pedirla. También cubre tareas que superan el máximo del stream (120 s).
      const done = (s: TaskStatus) => FINAL.includes(s) && !(afterApproval && s === "awaiting_approval");
      for (let i = 0; i < 300; i++) {
        lastIds.current[taskId] = await followTask(taskId, (s) =>
          patch(taskId, (t) => ({ ...t, task_status: s, live: [...(t.live ?? []), s] })), lastIds.current[taskId] ?? 0);
        task = await api.task(taskId);
        if (done(task.status)) break;
        await new Promise((r) => setTimeout(r, 400));
      }
      if (!task) return;
      const approvals = task.status === "awaiting_approval"
        ? (await api.approvals()).approvals.filter((a) => a.task_id === taskId) : [];
      patch(taskId, (t) => ({ ...t, task_status: task.status, content: task.response?.text ?? "",
                              request_class: task.request_class ?? null,
                              warnings: task.response?.warnings ?? [], sources: task.response?.sources ?? [], approvals }));
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "Sin conexión con NEXUS");
    }
  }, []);

  async function send(e: { preventDefault(): void }) {
    e.preventDefault();
    const typed = draft.trim();
    if (!typed) return;
    setDraft("");
    if (typed.toLowerCase() === "/nueva") { onNew(); return; }
    // «solo mis fuentes» = /fuentes delante: un único mecanismo, visible en el historial
    const message = sourcesOnly && !typed.startsWith("/") ? `/fuentes ${typed}` : typed;
    setError(null);
    try {
      const r = await api.send(message, conversationId ?? undefined);
      const now = new Date().toISOString();
      setTurns((ts) => [...ts,
        { id: Date.now(), role: "user", content: message, task_id: r.task_id, task_status: null, warnings: [], sources: [], created_at: now },
        { id: Date.now() + 1, role: "assistant", content: "", task_id: r.task_id, task_status: "created", warnings: [], sources: [], created_at: now, live: [] }]);
      if (!conversationId) { createdHere.current = r.conversation_id; onConversation(r.conversation_id); }
      track(r.task_id);
    } catch (err) {
      setDraft(message);
      setError(err instanceof ApiError ? err.code : "Sin conexión con NEXUS");
    }
  }

  async function decide(id: string, decision: "approve" | "reject") {
    const turn = turns.find((t) => t.approvals?.some((a) => a.approval_id === id));
    try {
      await api.decide(id, decision);
      if (turn?.task_id) {
        patch(turn.task_id, (t) => ({ ...t, content: "", warnings: [], approvals: [] }));
        track(turn.task_id, true);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.code : "No se pudo registrar la decisión");
      if (turn?.task_id) track(turn.task_id);
    }
  }

  async function cancel(taskId: string) {
    try { await api.cancel(taskId); track(taskId); } catch (err) { setError(err instanceof ApiError ? err.code : "No se pudo cancelar"); }
  }

  return (
    <div className="chat">
      <div className="log" aria-live="polite">
        {!turns.length && (
          <div className="empty">
            <p className="empty-kicker">sala de control</p>
            <h2>{who?.owner_name ? `¿Qué hacemos, ${who.owner_name}?` : "¿Qué hacemos?"}</h2>
            {who && (!who.configured || naming)
              ? <Onboarding current={who} onDone={(i) => { setWho(i); setNaming(false); }} />
              : who && <p className="muted small">Soy {name}. <button className="link small" onClick={() => setNaming(true)}>cambiar nombres</button></p>}
            <ul>
              <li><button className="link" onClick={() => setDraft("¿Qué puedes hacer?")}>¿Qué puedes hacer?</button></li>
              <li><button className="link" onClick={() => setDraft("Según mis documentos, ")}>Según mis documentos, …</button></li>
              <li><button className="link" onClick={() => setDraft("Crea una nota titulada ")}>Crea una nota titulada …</button></li>
              <li><button className="link" onClick={() => { setDraft("/"); box.current?.focus(); }}>/ comandos</button></li>
            </ul>
          </div>
        )}
        {turns.map((t) => <Bubble key={`${t.id}-${t.role}`} t={t} name={name} onDecide={decide} onCancel={cancel} />)}
        <div ref={end} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      {matches.length > 0 && (
        <ul className="slash" role="listbox" aria-label="Comandos">
          {matches.map((c, i) => (
            <li key={c.cmd} role="option" aria-selected={i === 0}>
              <button type="button" onClick={() => pick(c)}><code>{c.cmd}</code><span>{c.desc}</span></button>
            </li>))}
        </ul>
      )}
      <form className="composer" onSubmit={send}>
        <button type="button" className={`mode ${sourcesOnly ? "on" : ""}`} aria-pressed={sourcesOnly}
                title="Responder solo con tus documentos y la memoria confirmada, citando la fuente"
                onClick={() => setSourcesOnly(!sourcesOnly)}>solo mis fuentes</button>
        <label htmlFor="msg" className="sr-only">Mensaje para {name}</label>
        <textarea id="msg" ref={box} value={draft} rows={2} maxLength={8000}
                  placeholder={sourcesOnly ? "Pregunta a tus documentos…" : `Escribe a ${name}…  ( / para comandos)`}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Tab" && matches.length) { e.preventDefault(); pick(matches[0]); return; }
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      // Enter con un comando a medio escribir lo completa; si ya está entero, se envía
                      if (matches.length && matches[0].cmd !== draft.toLowerCase()) { pick(matches[0]); return; }
                      e.currentTarget.form?.requestSubmit();
                    }
                  }} />
        <button type="submit" disabled={!draft.trim()}>Enviar</button>
      </form>
    </div>
  );
}
