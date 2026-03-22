import { getStoredToken } from "./auth";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

export interface ApiError {
  error: string;
  message: string;
  request_id: string;
}

export class ApiException extends Error {
  constructor(
    public status: number,
    public body: ApiError,
  ) {
    super(body.message);
    this.name = "ApiException";
  }
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  limit: number;
  total_pages: number;
}

interface ApiRequestOptions extends RequestInit {
  skipRedirectOn401?: boolean;
}

/**
 * Typed fetch wrapper with Bearer token injection from cookie.
 * 401 responses redirect to /login unless skipRedirectOn401 is true.
 */
export async function apiRequest<T>(
  path: string,
  options: ApiRequestOptions = {},
): Promise<T> {
  const { skipRedirectOn401, ...fetchOptions } = options;
  const token = getStoredToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((fetchOptions.headers as Record<string, string>) ?? {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers,
  });

  if (res.status === 401) {
    if (!skipRedirectOn401 && typeof window !== "undefined") {
      window.location.href = "/login";
    }
    let errorBody: ApiError;
    try {
      const raw = await res.json();
      errorBody = {
        error: "unauthorized",
        message: raw.message ?? raw.detail ?? "Invalid credentials",
        request_id: raw.request_id ?? "",
      };
    } catch {
      errorBody = {
        error: "unauthorized",
        message: "Invalid credentials",
        request_id: "",
      };
    }
    throw new ApiException(401, errorBody);
  }

  if (!res.ok) {
    let errorBody: ApiError;
    try {
      errorBody = await res.json();
    } catch {
      errorBody = {
        error: "unknown_error",
        message: `Request failed with status ${res.status}`,
        request_id: "",
      };
    }
    throw new ApiException(res.status, errorBody);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

/**
 * POST helper.
 * Pass `{ skipRedirectOn401: true }` in opts to suppress the automatic
 * /login redirect on 401 and let the caller handle the ApiException instead.
 */
export async function apiPost<T>(
  path: string,
  body: Record<string, unknown> | object,
  opts: { skipRedirectOn401?: boolean } = {},
): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
    skipRedirectOn401: opts.skipRedirectOn401,
  });
}

/**
 * PATCH helper.
 * Pass `{ skipRedirectOn401: true }` in opts to suppress the automatic
 * /login redirect on 401 and let the caller handle the ApiException instead.
 */
export async function apiPatch<T>(
  path: string,
  body: Record<string, unknown> | object,
  opts: { skipRedirectOn401?: boolean } = {},
): Promise<T> {
  return apiRequest<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
    skipRedirectOn401: opts.skipRedirectOn401,
  });
}

/**
 * GET helper
 */
export async function apiGet<T>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "GET" });
}

/**
 * PUT helper
 */
export async function apiPut<T>(
  path: string,
  body: Record<string, unknown> | object,
  opts: { skipRedirectOn401?: boolean } = {},
): Promise<T> {
  return apiRequest<T>(path, {
    method: "PUT",
    body: JSON.stringify(body),
    skipRedirectOn401: opts.skipRedirectOn401,
  });
}

/**
 * DELETE helper
 */
export async function apiDelete<T = void>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "DELETE" });
}
