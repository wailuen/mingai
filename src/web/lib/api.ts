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

/**
 * Typed fetch wrapper with Bearer token injection from cookie.
 * 401 responses redirect to /login.
 */
export async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getStoredToken();

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((options.headers as Record<string, string>) ?? {}),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers,
  });

  if (res.status === 401) {
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new ApiException(401, {
      error: "unauthorized",
      message: "Session expired. Redirecting to login.",
      request_id: "",
    });
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
 * POST helper
 */
export async function apiPost<T>(
  path: string,
  body: Record<string, unknown> | object,
): Promise<T> {
  return apiRequest<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

/**
 * PATCH helper
 */
export async function apiPatch<T>(
  path: string,
  body: Record<string, unknown> | object,
): Promise<T> {
  return apiRequest<T>(path, {
    method: "PATCH",
    body: JSON.stringify(body),
  });
}

/**
 * DELETE helper
 */
export async function apiDelete<T = void>(path: string): Promise<T> {
  return apiRequest<T>(path, { method: "DELETE" });
}
