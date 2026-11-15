import { useCallback, useEffect, useState } from "react";
import { api, ApiError, auth, type Conversation } from "./api";
import { Chat } from "./Chat";
import { ConnectorsPanel, KnowledgePanel, LearningPanel, SystemPanel } from "./Panels";

type Tab = "sistema" | "conocimiento" | "conectores" | "aprendizaje";

function Login({ onReady }: { onReady: () => void }) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  async function submit(e: { preventDefault(): void }) {
    e.preventDefault();
    auth.set(token.trim());
    try { await api.conversations(); onReady(); }
    catch (err) { auth.clear(); setError(err instanceof ApiError && err.status === 401 ? "Token no válido" : "NEXUS no responde"); }
  }
  return (
    <main className="login">
      <form onSubmit={submit}>
        <p className="brand"><span>N</span>EXUS</p>
        <p className="muted">Introduce el token de esta instancia (<code>NEXUS_API_TOKEN</code> en el .env del servidor).</p>
        <label htmlFor="tok" className="sr-only">Token</label>
        <input id="tok" type="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />
        <button disabled={!token.trim()}>Entrar</button>
        {error && <p className="error" role="alert">{error}</p>}
      </form>
    </main>
  );
}

export default function App() {
  const [ready, setReady] = useState(!!auth.get());
  const [convs, setConvs] = useState<Conversation[]>([]);
  const [active, setActive] = useState<string | null>(null);
  // Solo cambia al ELEGIR otra conversación: crear una nueva desde el chat no debe remontarlo
  // (perdería el seguimiento SSE de la tarea en curso — visto en la primera prueba en navegador).
  const [chatKey, setChatKey] = useState("new");
  const open = (id: string | null) => { setActive(id); setChatKey(id ?? `new-${Date.now()}`); };
  const [tab, setTab] = useState<Tab>("sistema");
  // En pantallas estrechas el panel es una capa encima del chat: empieza plegado.
  const [railOpen, setRailOpen] = useState(() => window.matchMedia("(min-width: 1101px)").matches);

  const refresh = useCallback(() => {
    api.conversations().then((r) => setConvs(r.conversations))
      .catch((e) => { if (e instanceof ApiError && e.status === 401) setReady(false); });
  }, []);
  useEffect(() => { if (ready) refresh(); }, [ready, refresh]);

  if (!ready) return <Login onReady={() => setReady(true)} />;

  return (
    <div className={`shell ${railOpen ? "" : "rail-closed"}`}>
      <nav className="side" aria-label="Conversaciones">
        <p className="brand"><span>N</span>EXUS</p>
        <button className="new" onClick={() => open(null)}>+ nueva conversación</button>
        <ol className="convs">
          {convs.map((c) => (
            <li key={c.conversation_id}>
              <button className={c.conversation_id === active ? "on" : ""} onClick={() => open(c.conversation_id)}
                      title={c.title}>
                <span>{c.title || "sin título"}</span>
                <small>{c.last_at ? new Date(c.last_at).toLocaleDateString() : ""} · {c.messages}</small>
              </button>
            </li>
          ))}
        </ol>
        <button className="link logout" onClick={() => { auth.clear(); setReady(false); }}>cerrar sesión</button>
      </nav>

      <main className="center">
        <Chat key={chatKey} conversationId={active} onConversation={(id) => { setActive(id); refresh(); }} />
      </main>

      <aside className="rail" aria-label="Panel de control">
        <div className="tabs" role="tablist">
          {(["sistema", "conocimiento", "conectores", "aprendizaje"] as Tab[]).map((t) => (
            <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => setTab(t)}>{t}</button>
          ))}
          <button className="rail-toggle" aria-label={railOpen ? "Ocultar panel" : "Mostrar panel"} onClick={() => setRailOpen(!railOpen)}>
            {railOpen ? "›" : "‹"}
          </button>
        </div>
        {railOpen && (tab === "sistema" ? <SystemPanel /> : tab === "conocimiento" ? <KnowledgePanel />
          : tab === "conectores" ? <ConnectorsPanel /> : <LearningPanel />)}
      </aside>
    </div>
  );
}
