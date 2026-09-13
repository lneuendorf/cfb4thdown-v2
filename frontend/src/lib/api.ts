// Client for our own API (never an upstream provider). Base URL comes from VITE_API_BASE in
// production; in dev, Vite proxies /api to the FastAPI service.

import type { Envelope } from "./types";

const BASE = `${import.meta.env.VITE_API_BASE ?? ""}/api/v1`;

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function apiGet<T>(path: string, signal?: AbortSignal): Promise<Envelope<T>> {
  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, { signal, headers: { Accept: "application/json" } });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiError(0, "NETWORK", "Couldn't reach the server.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const error = body?.error;
    throw new ApiError(
      response.status,
      error?.code ?? "ERROR",
      error?.message ?? "Something went wrong loading this page.",
    );
  }
  return body as Envelope<T>;
}
