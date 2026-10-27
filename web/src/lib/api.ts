// Same-origin API client. Writes carry the per-process session token.
let token: string | null = null;

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public errors?: Record<string, string>,
  ) {
    super(message);
  }
}

async function session(): Promise<string> {
  if (token) return token;
  const response = await fetch("/api/session", { cache: "no-store" });
  if (!response.ok) throw new ApiError(response.status, "session", "Dashboard server unavailable");
  token = (await response.json()).token as string;
  return token;
}

async function parse(response: Response) {
  let body: Record<string, unknown> = {};
  try {
    body = await response.json();
  } catch {
    body = {};
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      String(body.error ?? "error"),
      String(body.message ?? body.error ?? `Request failed (${response.status})`),
      body.errors as Record<string, string> | undefined,
    );
  }
  return body;
}

export async function get<T = Record<string, unknown>>(path: string): Promise<T> {
  return (await parse(await fetch(path, { cache: "no-store" }))) as T;
}

export async function post<T = Record<string, unknown>>(path: string, payload: unknown = {}): Promise<T> {
  const send = async () =>
    fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": await session() },
      body: JSON.stringify(payload),
    });
  let response = await send();
  if (response.status === 403) {
    token = null; // The server restarted; fetch a fresh session once.
    response = await send();
  }
  return (await parse(response)) as T;
}

export const setup = <T = Record<string, unknown>>(action: string, payload: unknown = {}) =>
  post<T>(`/api/setup/${action}`, payload);
