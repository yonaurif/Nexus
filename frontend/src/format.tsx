import type { ReactNode } from "react";
import type { TaskStatus } from "./api";

// Texto del asistente -> nodos React. Nunca HTML crudo ni dangerouslySetInnerHTML (Doc 04 §5.5):
// párrafos, listas, **negrita**, `código` y bloques ``` ```. Todo lo demás se muestra escapado.
function inline(text: string, key: string): ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).filter(Boolean).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={`${key}-${i}`}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("`") && part.endsWith("`")) return <code key={`${key}-${i}`}>{part.slice(1, -1)}</code>;
    return part;
  });
}

export function RichText({ text }: { text: string }) {
  const out: ReactNode[] = [];
  const blocks = text.split(/```/);
  blocks.forEach((block, bi) => {
    if (bi % 2 === 1) {
      out.push(<pre key={`pre-${bi}`}><code>{block.replace(/^\w*\n/, "")}</code></pre>);
      return;
    }
    block.split(/\n{2,}/).forEach((para, pi) => {
      const lines = para.split("\n").filter((l) => l.trim());
      if (!lines.length) return;
      const key = `${bi}-${pi}`;
      if (lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l))) {
        const ordered = /^\s*\d/.test(lines[0]);
        const items = lines.map((l, li) => <li key={li}>{inline(l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""), `${key}-${li}`)}</li>);
        out.push(ordered ? <ol key={key}>{items}</ol> : <ul key={key}>{items}</ul>);
      } else {
        out.push(<p key={key}>{lines.flatMap((l, li) => (li ? [<br key={`br-${li}`} />, ...inline(l, `${key}-${li}`)] : inline(l, `${key}-${li}`)))}</p>);
      }
    });
  });
  return <>{out}</>;
}

// Avisos del backend -> frase legible (el código queda en el title para depurar).
const WARNINGS: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^APPROVAL_REQUIRED$/, () => "Espera tu aprobación"],
  [/^APPROVAL_REJECTED$/, () => "Rechazada por ti"],
  [/^APPROVAL_EXPIRED$/, () => "La aprobación caducó"],
  [/^CANCELLED$/, () => "Cancelada"],
  [/^MODEL_NOT_CONFIGURED$/, () => "Sin modelo configurado"],
  [/^MODEL_UNAVAILABLE$/, () => "Modelo no disponible"],
  [/^NO_EVIDENCE:knowledge$/, () => "Sin evidencia en tus documentos"],
  [/^NEEDS_INPUT$/, () => "Necesita más detalle"],
  [/^SECRET_DETECTED$/, () => "Contiene una credencial: no se guarda"],
  [/^UNKNOWN_COMMAND$/, () => "Comando desconocido"],
  [/^PLAN_REJECTED:(\w+)/, (m) => `Plan descartado · ${m[1]}`],
  [/^CAPABILITY_UNAVAILABLE:(\w+)/, (m) => `Aún no disponible · ${m[1]}`],
  [/^(\w+):(\w+)$/, (m) => `Paso ${m[1]} · ${m[2]}`],
];

export function warningLabel(w: string): string {
  for (const [re, f] of WARNINGS) {
    const m = w.match(re);
    if (m) return f(m);
  }
  return w;
}

export const STATUS_LABEL: Record<TaskStatus, string> = {
  created: "recibida", classifying: "clasificando", context_building: "reuniendo contexto", planning: "planificando",
  plan_validating: "validando plan", awaiting_approval: "espera aprobación", queued: "en cola", running: "ejecutando",
  verifying: "verificando", completed: "completada", needs_input: "necesita datos", partial: "parcial",
  failed: "fallida", cancel_requested: "cancelando", cancelled: "cancelada", expired: "caducada",
};

export const INTENT_LABEL: Record<string, string> = {
  conversation: "conversación", knowledge_query: "consulta a documentos", task_request: "tarea",
  agent_request: "servicio externo", memory_update: "recordar preferencia", feedback: "valoración",
  rule_proposal: "proponer regla", system_admin: "administración", unknown: "no entendida",
};

export function sourceLabel(ref: string): string {
  if (ref.startsWith("doc:")) return `documento ${ref.slice(4, 16)}…${ref.split("#")[1] ? ` §${ref.split("#")[1]}` : ""}`;
  if (ref.startsWith("internal:")) return ref.slice(9).replace(/_/g, " ");
  if (ref.startsWith("fact:")) return "memoria";
  return ref.replace(/^[a-z_]+:GET /, "");
}
