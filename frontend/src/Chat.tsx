import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, FINAL, followTask, type Approval, type Message, type Source, type TaskStatus } from "./api";
import { RichText, sourceLabel, STATUS_LABEL, warningLabel } from "./format";

// Etapas reales del Doc 02 §7.1 que se encienden por SSE. queued+running se muestran juntas.
const STAGES: { key: string; label: string; states: TaskStatus[] }[] = [
  { key: "cls", label: "clasificar", states: ["classifying"] },
  { key: "ctx", label: "contexto", states: ["context_building"] },
  { key: "plan", label: "planificar", states: ["planning"] },
  { key: "val", label: "validar", states: ["plan_validating", "awaiting_approval"] },
  { key: "run", label: "ejecutar", states: ["queued", "running"] },
  { key: "ver", label: "verificar", states: ["verifying"] },
];

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

function Bubble({ t, onDecide, onCancel }: { t: Turn; onDecide: (id: string, d: "approve" | "reject") => void;
                                           onCancel: (taskId: string) => void }) {
  if (t.role === "user") return <article className="turn user"><RichText text={t.content} /></article>;
  const working = !t.task_status || !FINAL.includes(t.task_status);
  return (
    <article className={`turn nexus status-${t.task_status ?? "running"}`} aria-busy={working}>
      {(t.live?.length || working) && <Ribbon seen={t.live ?? []} status={t.task_status} />}
      {t.approvals?.length ? <p className="prose">Necesito tu aprobación antes de hacer esto:</p>
        : t.content ? <div className="prose"><RichText text={t.content} /></div>
        : <p className="thinking" role="status">NEXUS está trabajando…</p>}
      {t.approvals?.map((a) => <ApprovalCard key={a.approval_id} a={a} onDecide={onDecide} />)}
      <footer>
        {t.warnings.map((w) => <span key={w} className="chip warn" title={w}>{warningLabel(w)}</span>)}
        <Sources sources={t.sources} />
        {working && t.task_id && <button className="link" onClick={() => onCancel(t.task_id!)}>cancelar</button>}
      </footer>
    </article>
  );
}

export function Chat({ conversationId, onConversation }: { conversationId: string | null;
                                                          onConversation: (id: string) => void }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const lastIds = useRef<Record<string, number>>({});
  const end = useRef<HTMLDivElement>(null);

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
                              warnings: task.response?.warnings ?? [], sources: task.response?.sources ?? [], approvals }));
    } catch (e) {
      setError(e instanceof ApiError ? e.code : "Sin conexión con NEXUS");
    }
  }, []);

  async function send(e: { preventDefault(): void }) {
    e.preventDefault();
    const message = draft.trim();
    if (!message) return;
    setDraft("");
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
            <h2>¿Qué hacemos?</h2>
            <ul>
              <li><button className="link" onClick={() => setDraft("¿Qué puedes hacer?")}>¿Qué puedes hacer?</button></li>
              <li><button className="link" onClick={() => setDraft("Según mis documentos, ")}>Según mis documentos, …</button></li>
              <li><button className="link" onClick={() => setDraft("Crea una nota titulada ")}>Crea una nota titulada …</button></li>
            </ul>
          </div>
        )}
        {turns.map((t) => <Bubble key={`${t.id}-${t.role}`} t={t} onDecide={decide} onCancel={cancel} />)}
        <div ref={end} />
      </div>
      {error && <p className="error" role="alert">{error}</p>}
      <form className="composer" onSubmit={send}>
        <label htmlFor="msg" className="sr-only">Mensaje para NEXUS</label>
        <textarea id="msg" value={draft} rows={2} maxLength={8000} placeholder="Escribe a NEXUS…"
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }} />
        <button type="submit" disabled={!draft.trim()}>Enviar</button>
      </form>
    </div>
  );
}
