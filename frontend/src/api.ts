// Обращение к API. Пути относительные (/api/...): в разработке их передаёт Vite (vite.config.ts).
// Вход — cookie «session» (httpOnly), её браузер отправляет сам. Перенесено из A2A Маркет.

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** Текст ошибки из ответа API: {"detail": {"code", "message"}} или ошибка схемы FastAPI (422). */
function toError(status: number, body: any): ApiError {
  const detail = body?.detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    return new ApiError(status, detail.code ?? "error", detail.message ?? "Ошибка запроса", detail.errors);
  }
  if (Array.isArray(detail)) {
    const text = detail.map((d: any) => `${(d.loc ?? []).slice(1).join(".")}: ${d.msg}`).join("; ");
    return new ApiError(status, "invalid", `Данные не прошли проверку: ${text}`, detail);
  }
  if (status === 0) return new ApiError(0, "network", "API недоступен: запущен ли docker compose?");
  return new ApiError(status, "error", typeof detail === "string" ? detail : `Ошибка ${status}`);
}

export async function api<T = any>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, {
      method: options.method ?? (options.body === undefined ? "GET" : "POST"),
      credentials: "include",
      headers: options.body === undefined ? {} : { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
    });
  } catch {
    throw toError(0, null);
  }
  if (res.status === 204) return undefined as T;
  const body = parseBody(await res.text());
  if (!res.ok) throw toError(res.status, body);
  return body as T;
}

/** Тело ответа: JSON, если это JSON; иначе сырой текст. Пустой ответ — null. */
function parseBody(text: string): any {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

/** Загрузка файла (multipart/form-data): прайс, таблица запроса, вложение письма. */
export async function apiForm<T = any>(path: string, form: FormData): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`/api${path}`, { method: "POST", credentials: "include", body: form });
  } catch {
    throw toError(0, null);
  }
  const body = parseBody(await res.text());
  if (!res.ok) throw toError(res.status, body);
  return body as T;
}

// ---------- Типы ответов (по backend/app/*/router.py) ----------

export interface Me {
  id: number;
  email: string;
  full_name: string;
  role: "initiator" | "contract_manager" | "admin";
  role_title: string;
  org_id: number;
  org_name: string;
}

export interface KtruCandidate {
  code: string;
  okpd2: string;
  name: string;
  score?: number;
}

export interface SpecItem {
  id: number;
  line_no: number;
  name: string;
  characteristics: string | null;
  quantity: string | null;
  unit: string | null;
  ktru_code: string | null;
  okpd2_code: string | null;
  ktru_candidates: KtruCandidate[];
  ktru_suggestion: { code: string | null; question: string | null; reason: string } | null;
  status: "ok" | "needs_review";
  problems: string[];
  notes: string[];
  questions: string[];
  source: string | null;
}

export interface JournalRow {
  seq: number;
  created_at: string;
  actor_kind: "human" | "agent" | "system";
  action: string;
  decision: string | null;
  model: string | null;
  prompt_version: string | null;
  tokens: number | null;
  cost_rub: string | null;
  details: Record<string, any>;
  hash: string;
}

export type ProcStatus =
  | "draft" | "spec_review" | "sourcing" | "collecting" | "analysis"
  | "justification_review" | "approved" | "closed" | "needs_human" | "cancelled";

export interface Quote {
  id: number;
  spec_item_id: number;
  channel: "site" | "email" | "eis_contract";
  source_name: string;
  region: string | null;
  offer_name: string | null;
  unit_price: string;
  vat_mode: "with" | "without" | "unknown";
  price_kind: string | null;
  url: string | null;
  captured_at: string;
  extracted_by: string;
  html_sha256: string | null;
  screenshot_sha256: string | null;
  match: { matches?: boolean; confidence?: string; differences?: string[]; reason?: string };
  status: "ok" | "rejected" | "review";
  notes: string[];
}

export interface EvidenceCheck {
  ok: boolean;
  sha256: string;
  file_sha256: string | null;
  in_journal: boolean;
  reason: string | null;
  url: string | null;
  captured_at: string;
  kind: string;
}

export interface CandidateRow {
  id: number;
  supplier_id: number;
  name: string;
  region: string | null;
  city: string | null;
  email: string | null;
  is_demo: boolean;
  source: "eis" | "demo";
  contracts_44fz_3y: number;
  item_ids: number[];
  checks: { code: string; verdict: "allow" | "warn" | "human" | "deny"; reason: string }[];
  verdict: "allow" | "warn" | "human" | "deny";
  selected: boolean;
  rank: number;
  reason: string | null;
  request_status: "none" | "queued" | "sent" | "reminded" | "replied";
}

export interface MessageRow {
  id: string;
  direction: "out" | "in";
  candidate_id: number | null;
  kind: string;
  address: string;
  subject: string;
  body: string;
  at: string | null;
  status: string;
  attachments: { filename: string | null; content_type: string; sha256: string; size: number }[];
  suspicious: string[];
  evidence_sha256: string | null;
}

export interface Procurement {
  id: number;
  number: string | null;
  title: string;
  status: ProcStatus;
  status_title: string;
  hold_reason: string | null;
  source_text: string;
  created_at: string;
  parse_meta: {
    deadline_raw?: string | null;
    possibly_missed?: string[];
    suspicious?: string[];
  };
  items: SpecItem[];
  quotes: Quote[];
  candidates: CandidateRow[];
  messages: MessageRow[];
  journal: JournalRow[];
  time_shift_hours: number;
  demo_mode: boolean;
}
