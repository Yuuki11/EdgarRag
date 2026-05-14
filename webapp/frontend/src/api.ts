// Browser-side API contract for the FastAPI backend.
//
// Keep these types in step with `webapp/backend/schemas.py`. Components should
// call the functions in this file rather than assembling fetch requests
// directly, so cookie credentials and error handling stay consistent.

export type Company = {
  ticker: string;
  name: string;
  sector: string;
  years: number[];
};

export type Citation = {
  index: number;
  ticker: string | null;
  year: number | null;
  section: string | null;
  doc_type: string | null;
  fiscal_period: string | null;
  snippet: string | null;
};

export type XbrlEvidence = {
  concept: string | null;
  value: number | string | null;
  unit: string | null;
  period: string | null;
  accession: string | null;
  form: string | null;
};

export type ChatResponse = {
  conversation_id: string | null;
  message_id: string | null;
  answer: string;
  route: string;
  operation: string;
  ticker: string | null;
  years: number[];
  metrics: string[];
  citations: Citation[];
  xbrl_evidence: XbrlEvidence[];
  latency_ms: number;
  fallback_used: boolean;
  error: string;
};

export type User = {
  id: string;
  email: string;
  is_verified: boolean;
};

export type AuthStatus = {
  user: User | null;
};

export type ConversationSummary = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type MessageHistory = {
  id: string;
  role: "user" | "assistant";
  content: string;
  ticker: string | null;
  years: number[] | null;
  response: ChatResponse | null;
  created_at: string;
};

export type Health = {
  ollama_reachable: boolean;
  ollama_host: string;
  ollama_model: string;
  indexed_companies: number;
  xbrl_cache_warm: boolean;
  compute_mode: "cpu" | "auto";
};

export type AdminMetric = {
  label: string;
  value: number | string | boolean | null;
  status: "ok" | "warn" | "neutral";
  detail: string | null;
};

export type AdminDataArtifact = {
  name: string;
  path: string;
  present: boolean;
  files: number;
  detail: string | null;
};

export type AdminAuthEvent = {
  event_type: string;
  email: string | null;
  created_at: string;
};

export type AdminRuntime = {
  environment: string;
  release: string;
  pod_name: string | null;
  namespace: string | null;
  node_name: string | null;
  running_in_kubernetes: boolean;
};

export type AdminOverview = {
  generated_at: string;
  runtime: AdminRuntime;
  health: Health;
  metrics: AdminMetric[];
  data_artifacts: AdminDataArtifact[];
  recent_auth_events: AdminAuthEvent[];
};

async function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(path, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
}

async function readError(r: Response): Promise<string> {
  try {
    const data = await r.json();
    if (typeof data?.detail === "string") return data.detail;
  } catch {
    // Fall through to text.
  }
  return await r.text();
}

export async function fetchCompanies(): Promise<Company[]> {
  const r = await apiFetch("/api/companies");
  if (!r.ok) throw new Error(`GET /api/companies failed: ${r.status}`);
  const data = (await r.json()) as { companies: Company[] };
  return data.companies;
}

export async function fetchHealth(): Promise<Health> {
  const r = await apiFetch("/healthz");
  if (!r.ok) throw new Error(`GET /healthz failed: ${r.status}`);
  return (await r.json()) as Health;
}

export async function fetchAdminOverview(): Promise<AdminOverview> {
  const r = await apiFetch("/api/admin/overview");
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as AdminOverview;
}

export async function fetchMe(): Promise<AuthStatus> {
  const r = await apiFetch("/api/auth/me");
  if (!r.ok) throw new Error(`GET /api/auth/me failed: ${r.status}`);
  return (await r.json()) as AuthStatus;
}

export async function register(email: string, password: string): Promise<AuthStatus> {
  const r = await apiFetch("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as AuthStatus;
}

export async function verifyEmail(token: string): Promise<AuthStatus> {
  const r = await apiFetch("/api/auth/verify-email", {
    method: "POST",
    body: JSON.stringify({ token }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as AuthStatus;
}

export async function login(email: string, password: string): Promise<AuthStatus> {
  const r = await apiFetch("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as AuthStatus;
}

export async function logout(): Promise<void> {
  const r = await apiFetch("/api/auth/logout", { method: "POST" });
  if (!r.ok) throw new Error(await readError(r));
}

export async function forgotPassword(email: string): Promise<void> {
  const r = await apiFetch("/api/auth/forgot-password", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
  if (!r.ok) throw new Error(await readError(r));
}

export async function resetPassword(token: string, password: string): Promise<AuthStatus> {
  const r = await apiFetch("/api/auth/reset-password", {
    method: "POST",
    body: JSON.stringify({ token, password }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as AuthStatus;
}

export async function fetchConversations(): Promise<ConversationSummary[]> {
  const r = await apiFetch("/api/conversations");
  if (!r.ok) throw new Error(await readError(r));
  const data = (await r.json()) as { conversations: ConversationSummary[] };
  return data.conversations;
}

export async function createConversation(title = "New chat"): Promise<ConversationSummary> {
  const r = await apiFetch("/api/conversations", {
    method: "POST",
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as ConversationSummary;
}

export async function renameConversation(id: string, title: string): Promise<ConversationSummary> {
  const r = await apiFetch(`/api/conversations/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error(await readError(r));
  return (await r.json()) as ConversationSummary;
}

export async function deleteConversation(id: string): Promise<void> {
  const r = await apiFetch(`/api/conversations/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error(await readError(r));
}

export async function fetchConversationMessages(id: string): Promise<MessageHistory[]> {
  const r = await apiFetch(`/api/conversations/${id}/messages`);
  if (!r.ok) throw new Error(await readError(r));
  const data = (await r.json()) as { messages: MessageHistory[] };
  return data.messages;
}

export async function postChat(body: {
  question: string;
  ticker?: string | null;
  years?: number[] | null;
  conversation_id?: string | null;
  route_override?: string | null;
}): Promise<ChatResponse> {
  const r = await apiFetch("/api/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const detail = await readError(r);
    throw new Error(`POST /api/chat failed: ${r.status} ${detail}`);
  }
  return (await r.json()) as ChatResponse;
}
