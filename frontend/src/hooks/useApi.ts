import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet } from "../lib/api";
import type { Meta } from "../lib/types";

export interface ApiState<T> {
  state: "loading" | "error" | "ready";
  data: T | undefined;
  meta: Meta | undefined;
  error: ApiError | undefined;
}

/**
 * Fetch one API path. Keeps the last good data while refreshing, so a poll never blanks the
 * page. `pollMs` (or a function of the latest data) re-fetches on an interval; null stops.
 */
export function useApi<T>(
  path: string | null,
  pollMs: number | null | ((data: T | undefined) => number | null) = null,
): ApiState<T> & { reload: () => void } {
  const [result, setResult] = useState<ApiState<T>>({
    state: "loading",
    data: undefined,
    meta: undefined,
    error: undefined,
  });
  const [tick, setTick] = useState(0);
  const dataRef = useRef<T | undefined>(undefined);

  useEffect(() => {
    dataRef.current = undefined;
    setResult({ state: "loading", data: undefined, meta: undefined, error: undefined });
  }, [path]);

  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    apiGet<T>(path, controller.signal)
      .then((envelope) => {
        dataRef.current = envelope.data;
        setResult({ state: "ready", data: envelope.data, meta: envelope.meta, error: undefined });
      })
      .catch((err: unknown) => {
        if (err instanceof DOMException && err.name === "AbortError") return;
        const error = err instanceof ApiError ? err : new ApiError(0, "ERROR", String(err));
        // A failed refresh keeps showing the last good data.
        setResult((prev) => ({ ...prev, state: prev.data ? "ready" : "error", error }));
      });
    return () => controller.abort();
  }, [path, tick]);

  const interval = typeof pollMs === "function" ? pollMs(result.data) : pollMs;
  useEffect(() => {
    if (!path || interval == null) return;
    const id = setInterval(() => setTick((t) => t + 1), interval);
    return () => clearInterval(id);
  }, [path, interval]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { ...result, reload };
}
