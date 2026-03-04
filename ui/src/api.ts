export type ApiEnvelope<T> = {
  code: number;
  message: string;
  data: T;
};

export class ApiError extends Error {
  public status: number;
  public code?: number;
  public detail?: unknown;

  constructor(message: string, status: number, code?: number, detail?: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function getToken(): string | null {
  return localStorage.getItem("admin_token");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");

  const res = await fetch(path, { ...init, headers });
  const contentType = res.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const payload = isJson ? ((await res.json()) as unknown) : await res.text();

  if (!res.ok) {
    if (typeof payload === "object" && payload !== null) {
      const maybeAny = payload as any;
      const messageFromEnvelope =
        typeof maybeAny.message === "string" && maybeAny.message ? maybeAny.message : null;
      const messageFromDetail =
        typeof maybeAny.detail === "string" && maybeAny.detail ? maybeAny.detail : null;
      const message = messageFromEnvelope ?? messageFromDetail ?? `HTTP ${res.status}`;
      const code = typeof maybeAny.code === "number" ? maybeAny.code : undefined;
      throw new ApiError(message, res.status, code, payload);
    }
    throw new ApiError(`HTTP ${res.status}`, res.status, undefined, payload);
  }

  if (typeof payload === "object" && payload !== null && "code" in payload && "data" in payload) {
    const env = payload as ApiEnvelope<T>;
    if (env.code !== 0) throw new ApiError(env.message || "Request failed", res.status, env.code, env);
    return env.data;
  }

  return payload as T;
}

export type LoginResponse = { access_token: string; expires_at: string };
export type UserPublic = { id: number; username: string; is_admin: boolean };

export async function login(username: string, password: string): Promise<void> {
  const data = await request<LoginResponse>("/v1/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password })
  });
  localStorage.setItem("admin_token", data.access_token);
}

export async function logout(): Promise<void> {
  const token = getToken();
  try {
    if (token) await request<null>("/v1/auth/logout", { method: "POST" });
  } finally {
    localStorage.removeItem("admin_token");
  }
}

export async function getMe(): Promise<UserPublic> {
  return request<UserPublic>("/v1/auth/me");
}

export type OverviewCounts = { users: number; api_keys: number; tasks: number; requests: number };
export async function getOverview(): Promise<OverviewCounts> {
  return request<OverviewCounts>("/v1/admin/overview");
}

export type ApiKeyPublic = {
  id: number;
  name: string;
  api_key: string | null;
  prefix: string;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
};

export type ApiKeyCreated = { id: number; name: string; prefix: string; api_key: string; created_at: string };

export async function listMyApiKeys(): Promise<ApiKeyPublic[]> {
  return request<ApiKeyPublic[]>("/v1/api-keys");
}

export async function createApiKey(name: string): Promise<ApiKeyCreated> {
  return request<ApiKeyCreated>("/v1/api-keys", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name })
  });
}

export async function revokeApiKey(keyId: number): Promise<void> {
  await request<null>(`/v1/api-keys/${keyId}`, { method: "DELETE" });
}

export async function activateApiKey(keyId: number): Promise<void> {
  await request<null>(`/v1/api-keys/${keyId}/activate`, { method: "POST" });
}

export async function deleteApiKey(keyId: number): Promise<void> {
  await request<null>(`/v1/api-keys/${keyId}/hard`, { method: "DELETE" });
}

export type AdminApiKey = {
  id: number;
  user_id: number;
  username: string;
  name: string;
  api_key: string | null;
  prefix: string;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
};

export async function listAllApiKeys(): Promise<AdminApiKey[]> {
  return request<AdminApiKey[]>("/v1/admin/api-keys");
}

export type AdminTask = {
  task_id: string;
  type: string;
  status: "pending" | "processing" | "completed" | "failed" | "cancelled";
  progress: number | null;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
};

export type AdminTaskDetail = AdminTask & {
  callback: string | null;
  data: Record<string, unknown> | string | null;
  config: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  error: Record<string, unknown> | null;
};

export async function listTasks(limit = 200): Promise<AdminTask[]> {
  return request<AdminTask[]>(`/v1/admin/tasks?limit=${encodeURIComponent(String(limit))}`);
}

export async function getTaskDetail(taskId: string): Promise<AdminTaskDetail> {
  return request<AdminTaskDetail>(`/v1/admin/tasks/${encodeURIComponent(taskId)}`);
}

export async function cancelTask(taskId: string): Promise<void> {
  await request(`/v1/admin/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
}

export async function deleteTask(taskId: string): Promise<void> {
  await request(`/v1/admin/tasks/${encodeURIComponent(taskId)}`, { method: "DELETE" });
}

export type AdminRequestLog = {
  id: number;
  request_id: string;
  ts: string;
  method: string;
  path: string;
  status_code: number;
  ip: string | null;
  user_agent: string | null;
  api_key_id: number | null;
  user_id: number | null;
  latency_ms: number;
  api_key_prefix: string | null;
  username: string | null;
};

export async function listRequests(limit = 200): Promise<AdminRequestLog[]> {
  return request<AdminRequestLog[]>(`/v1/admin/requests?limit=${encodeURIComponent(String(limit))}`);
}
