// Обращение к API площадки. Все пути — относительные (/api/...): в разработке их передаёт Vite (vite.config.ts),
// на стенде — Caddy. Вход — cookie «session» (httpOnly), её браузер отправляет сам.

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
  role: string;
  company_id: number | null;
  company_name: string | null;
  sandbox: string;
}

export interface Company {
  id: number;
  name: string;
  roles: string[];
  on_platform: boolean;
}

export interface Deal {
  id: number;
  number: string;
  title: string;
  kind: string;
  state: string;
  buyer_company_id: number;
  supplier_company_ids: number[];
  email_supplier_company_ids: number[];
  created_at: string;
  // Только в списке сделок (GET /deals)
  lines?: number | null;
  total?: string | null; // поставщику — его последнее КП; покупателю — сумма заказов
  channel?: "platform" | "email" | null; // поставщику — как пришёл запрос
  updated_at?: string | null;
}

export interface ExchangeObject {
  id: number;
  type: string;
  deal_id: number;
  version: number;
  reply_to: number | null;
  from_company_id: number;
  to_company_id: number | null;
  author_kind: string;
  author_user_id: number | null;
  mandate_id: number | null;
  ai_prepared: boolean;
  delivery_status: string;
  delivery: { status: string; checks: { code: string; result: string }[] };
  content: any;
  internal: any | null;
  created_at: string;
  sent_at?: string | null;
  expires_at: string | null;
}

export interface DealDetail extends Deal {
  feed: ExchangeObject[];
  preparing_supplier_ids?: number[]; // покупателю: чей ответ ждёт человека поставщика — «поставщик готовит ответ»
  awaiting_offer_approval_supplier_ids?: number[];
}

export interface Escalation {
  id: number;
  deal_id: number;
  to_role: string;
  object_id: number | null;
  rule_code: string;
  reason: string;
  prepared_decision: string | null;
  status: string;
  created_at: string;
  kind: string | null;
  blocked: boolean;
  comment?: string | null;
  revised_object_id?: number | null;
  revisable?: boolean;
  items?: { request_line_no: number; product_id: number; quantity: string; unit: string; analog_of?: number | null }[] | null;
  proposed_limit?: string | null;
  deferral_days?: number | null;
  dossier?: {
    name: string;
    inn: string | null;
    inn_valid: boolean;
    check_status: string | null;
    registered: string | null;
    activity: string | null;
    flags: string[];
  } | null;
  // ПК-1: расчёт выбора для утверждающего (считает код сравнения, не модель)
  choice?: ApprovalChoice | null;
}

export interface ApprovalChoice {
  summary: string;
  chosen: { offer_ids: number[]; cost: string; lines: number; of: number };
  is_best: boolean;
  cheaper: { offer_id: number; supplier_id: number; total: string; reasons: string[] }[];
  others: { offer_id: number; supplier_id: number; total: string; reasons: string[] }[];
}

export interface RequestItem {
  line_no: number;
  source_text?: string | null;
  name: string;
  characteristics?: string | null;
  quantity: string;
  unit: string;
  recognized?: boolean;
  allow_analogs?: boolean;
  must_have?: { attribute: string; value: string }[];
  nice_to_have?: { attribute: string; value: string }[];
}

export interface RequestContent {
  items: RequestItem[];
  kind?: "order" | "budget";
  allow_analogs?: boolean;
  respond_by?: string | null;
  delivery?: { region?: string | null; due_date?: string | null } | null;
  payment?: { kind: "prepay" | "deferral"; days?: number | null } | null;
  must_have?: { attribute: string; value: string }[];
  budget?: string | null;
  [key: string]: unknown;
}

export interface RequestDraft {
  id: number;
  title: string;
  text: string;
  status: "parsing" | "parsed" | "needs_manual" | "confirmed" | string;
  content: RequestContent | null;
  agent_notes: string[];
  suggested_suppliers: { company_id: number; name: string; channel: "platform" | "email"; lines: number[] }[];
  deal_id: number | null;
  created_at: string;
}

export interface DocumentOut {
  id: number;
  deal_id: number;
  order_object_id: number;
  doc_type: string;
  title: string;
  number: string;
  total: string;
  vat: string;
  edo_status: string;
  edo_status_text: string;
  supplier_company_id: number;
  buyer_company_id: number;
  pdf_url: string;
  created_at: string;
}

export interface Letter {
  id: number;
  deal_id: number;
  company_id: number;
  direction: "in" | "out";
  address: string | null;
  subject: string | null;
  body: string;
  status: string;
  offer_object_id: number | null;
  suspicious: boolean;
  attachment: { filename: string; rows_total: number } | null;
  created_at: string;
  // Черновик разбора агентом (или правилами без модели): строки КП по номерам строк запроса
  parsed?: {
    lines?: EmailOfferLine[];
    valid_days?: number | null;
    delivery_price?: string | null;
    delivery_days?: number | null;
    confidence?: number;
    notes?: string[];
    unit_problems?: { request_line_no: number; reason: string }[];
  } | null;
}

export interface EmailOfferLine {
  request_line_no: number;
  name?: string | null;
  sku?: string | null;
  quantity: string;
  unit: string;
  price: string;
  pack_size?: string | null;
  availability?: string;
  delivery_days?: number | null;
  is_analog?: boolean;
}

export interface JournalEntry {
  seq: number;
  created_at: string;
  deal_id: number | null;
  actor_kind: string;
  actor_company_id: number | null;
  action: string;
  decision: string | null;
  rule_code: string | null;
  op_code: string | null;
  model: string | null;
  tokens: number | null;
  cost_rub: string | null;
  details: any;
  hash: string;
  prev_hash?: string;
  mandate_id?: number | null;
  input_ref?: string | null;
  prompt_version?: string | null;
  actor_user_id?: number | null;
  confirmed_by_user_id?: number | null;
}
