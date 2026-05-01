export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
    message?: string,
  ) {
    super(message ?? `Request failed: ${status}`);
    this.name = "ApiError";
  }
}

async function parseBody(response: Response): Promise<unknown> {
  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("application/json")) {
    try {
      return await response.json();
    } catch {
      return null;
    }
  }
  try {
    return await response.text();
  } catch {
    return null;
  }
}

export interface RequestOptions {
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

export async function apiFetch(
  path: string,
  opts: RequestOptions = {},
): Promise<Response> {
  const url = path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
  const headers: Record<string, string> = { ...(opts.headers ?? {}) };
  let body: BodyInit | undefined;
  if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  const response = await fetch(url, {
    method: opts.method ?? "GET",
    headers,
    body,
    credentials: "include",
    signal: opts.signal,
  });
  if (!response.ok) {
    const parsed = await parseBody(response);
    throw new ApiError(response.status, parsed);
  }
  return response;
}

export async function apiJson<T>(
  path: string,
  opts: RequestOptions = {},
): Promise<T> {
  const response = await apiFetch(path, opts);
  return (await response.json()) as T;
}
