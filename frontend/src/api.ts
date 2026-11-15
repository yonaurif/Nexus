// Cliente de la API de NEXUS. La interfaz nunca habla con conectores ni MCP: solo con /api/v1 (Doc 04 §8.1).
// El token vive en sessionStorage (se borra al cerrar la pestaña). ponytail: auth real con sesiones en Fase 4.

const TOKEN_KEY = "nexus.token";

export const auth = {
  get: (): string | null => {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; }
  },
  set: (t: string) => { try { sessionStorage.setItem(TOKEN_KEY, t); } catch { /* modo privado */ } },
  clear: () => { try { sessionStorage.removeItem(TOKEN_KEY); } catch { /* modo privado */ } },
};

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string) {
    super(code);
    this.status = status;
    this.code = code;
  }
}

async function call<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  const token = auth.get();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const r = await fetch(`/api/v1${path}`, { ...init, headers });
  if (!r.ok) {
    let code = `HTTP_${r.status}`;
    try { const j = await r.json(); code = typeof j.detail === "string" ? j.detail : code; } catch { /* sin cuerpo */ }
    if (r.status === 401) auth.clear();
    throw new ApiError(r.status, code);
  }
  return r.json() as Promise<T>;
}

// --- Tipos (espejo de nexus/contracts.py) ---
export type Source = { source_ref: string; retrieved_at: string };
export type TaskStatus =
  | "created" | "classifying" | "context_building" | "planning" | "plan_validating" | "awaiting_approval"
  | "queued" | "running" | "verifying" | "completed" | "needs_input" | "partial" | "failed"
  | "cancel_requested" | "cancelled" | "expired";
export type Task = {
  task_id: string; status: TaskStatus; correlation_id: string;
  response: { text: string; task_status: string; warnings: string[]; sources: Source[] } | null;
};
export type Message = {
  id: number; role: "user" | "assistant"; content: string; task_id: string | null;
  task_status: TaskStatus | null; warnings: string[]; sources: Source[]; created_at: string;
};
export type Conversation = { conversation_id: string; title: string; messages: number; last_at: string | null };
export type Approval = {
  approval_id: string; task_id: string; step_id: string; tool_id: string; connector_id: string;
  risk_level: string; reversible: boolean; arguments: Record<string, unknown>; summary: string;
  status: string; expires_at: string;
};
export type Tool = {
  tool_id: string; connector_id: string; status: "review" | "enabled" | "disabled"; risk_level: string;
  description: string; approved: boolean;
};
export type Health = {
  status: string;
  components: {
    database: string;
    model: { name: string; status: string; active?: string | null;
             candidates?: { name: string; status: string; reason: string | null; gpu_layers: number | null }[] };
    embeddings: { name: string | null; status: string };
    hardware: { ram_total_gb: number; ram_free_gb: number; cpu_cores: number; cpu_percent: number;
                gpu: string | null; vram_total_gb: number; vram_free_gb: number };
  };
};
export type Folder = {
  source_id: string; display_name: string; path: string; files_indexed: number; status: string;
  sync_policy: { interval_minutes: number | null; ocr: boolean };
  last_run: { status: string; n_indexed: number; n_unchanged: number; n_skipped: number; n_failed: number;
              n_removed: number; started_at: string } | null;
};

export const api = {
  health: () => call<Health>("/system/health"),
  conversations: () => call<{ conversations: Conversation[] }>("/chat/conversations"),
  conversation: (id: string) => call<{ messages: Message[] }>(`/chat/conversations/${id}`),
  send: (message: string, conversation_id?: string) =>
    call<{ task_id: string; conversation_id: string }>("/chat/messages",
      { method: "POST", body: JSON.stringify({ message, ...(conversation_id ? { conversation_id } : {}) }) }),
  task: (id: string) => call<Task>(`/tasks/${id}`),
  cancel: (id: string) => call<{ status: string }>(`/tasks/${id}/cancel`, { method: "POST" }),
  approvals: (status = "pending") => call<{ approvals: Approval[] }>(`/approvals?status=${status}`),
  decide: (id: string, decision: "approve" | "reject") =>
    call<{ task_state: string }>(`/approvals/${id}/decision`, { method: "POST", body: JSON.stringify({ decision }) }),
  tools: () => call<{ tools: Tool[] }>("/connectors"),
  toolAction: (id: string, action: "approve" | "disable") =>
    call(`/connectors/tools/${id}/${action}`, { method: "POST" }),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return call<{ chunks: number; ocr_used: boolean; deduplicated: boolean; redactions: string[] }>(
      "/knowledge/files", { method: "POST", body: fd });
  },
  folders: () => call<{ sources: Folder[] }>("/knowledge/sources"),
  addFolder: (path: string, interval_minutes: number | null) =>
    call<{ source_id: string }>("/knowledge/sources", { method: "POST", body: JSON.stringify({ path, interval_minutes }) }),
  syncFolder: (id: string) => call(`/knowledge/sources/${id}/sync`, { method: "POST" }),
};

export const FINAL: TaskStatus[] = ["completed", "partial", "failed", "cancelled", "expired", "needs_input",
                                    "awaiting_approval"];

/** Sigue los eventos de una tarea por SSE (fetch, porque EventSource no envía cabeceras de auth).
 *  Devuelve el último id para reanudar con Last-Event-ID tras una aprobación (Doc 04 §9.2). */
export async function followTask(taskId: string, onStatus: (s: TaskStatus) => void, lastId = 0,
                                 signal?: AbortSignal): Promise<number> {
  const headers: Record<string, string> = { Authorization: `Bearer ${auth.get() ?? ""}` };
  if (lastId) headers["Last-Event-ID"] = String(lastId);
  const r = await fetch(`/api/v1/tasks/${taskId}/events`, { headers, signal });
  if (!r.ok || !r.body) throw new ApiError(r.status, "EVENTS_UNAVAILABLE");
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let i;
    while ((i = buf.indexOf("\n\n")) >= 0) {
      const block = buf.slice(0, i);
      buf = buf.slice(i + 2);
      const id = /^id: (\d+)$/m.exec(block);
      const data = /^data: (.*)$/m.exec(block);
      if (id) lastId = Number(id[1]);
      if (data) {
        try { onStatus(JSON.parse(data[1]).payload.to as TaskStatus); } catch { /* evento ajeno */ }
      }
    }
  }
  return lastId;
}
