import { useEffect } from "react";
import {
  hashKey,
  useQuery,
  useQueryClient,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { ApiError, get } from "./api/client";
import { AUTO_REFRESH_MAX_MS, AUTO_REFRESH_MS } from "./constants";

// Screens read their data again on a timer (D-083). The timer, the "visible again" and "back online" reads, and the
// "X-Auto-Refresh" mark live here, because TanStack cannot tell a query function what started it.
// Nothing here is a hook for `me`, the policy or the users: those are not refreshed.

export type Target = { key: QueryKey; path: string };

// How long to wait after `failures` failed reads in a row: 10, 20, 40, then 60 seconds.
export function delay(failures: number) {
  return Math.min(AUTO_REFRESH_MS * 2 ** failures, AUTO_REFRESH_MAX_MS);
}

// A background read that fails keeps the old data and only sets `error`. Network errors and 5xx keep the screen as it
// is; anything else, or a failure with nothing to show, is the error screen as before.
export function failure(query: { error: Error | null; data: unknown }) {
  const { error, data } = query;
  if (!error) return null;
  const transient = !(error instanceof ApiError) || error.status >= 500;
  return data === undefined || !transient ? error : null;
}

// 401 sends the user to the login screen; 403 and 404 stay on screen until the user retries.
const final = (error: unknown) =>
  error instanceof ApiError && [401, 403, 404].includes(error.status);

// What the screen is keeping fresh right now, for the "last updated" text.
const live = new Map<object, QueryKey>();
const listeners = new Set<() => void>();
const announce = () => listeners.forEach((listener) => listener());

export function useAutoRefresh(target: Target | null) {
  const client = useQueryClient();
  const key = target?.key;
  const path = target?.path;
  const hash = key && hashKey(key);
  useEffect(() => {
    if (!key || path === undefined) return;
    const queryKey = key;
    const id = {};
    live.set(id, key);
    announce();
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let waiting = false; // after a 401/403/404: wait for the user's retry to succeed
    let closed = false;
    const hidden = () => document.visibilityState === "hidden";
    const clear = () => {
      clearTimeout(timer);
      timer = undefined;
    };
    const blocked = () => final(client.getQueryState(key)?.error);
    const schedule = () => {
      clear();
      if (closed || waiting || hidden()) return;
      if (blocked()) waiting = true;
      else timer = setTimeout(() => void run(), delay(failures));
    };
    async function run() {
      timer = undefined;
      if (closed || waiting || hidden()) return;
      try {
        await client.fetchQuery({
          queryKey,
          queryFn: ({ signal }) => get(path!, signal, true),
          staleTime: 0,
        });
        failures = 0;
      } catch {
        failures += 1;
      }
      schedule();
    }
    // Back in view or back online: read now, and start the waits over.
    const wake = () => {
      if (closed || waiting || hidden()) return;
      failures = 0;
      clear();
      void run();
    };
    const onVisibility = () => (hidden() ? clear() : wake());
    const unsubscribe = client.getQueryCache().subscribe((event) => {
      if (
        waiting &&
        event.type === "updated" &&
        event.action.type === "success" &&
        event.query.queryHash === hash
      ) {
        waiting = false;
        failures = 0;
        schedule();
      }
    });
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("online", wake);
    schedule();
    return () => {
      closed = true;
      clear();
      unsubscribe();
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("online", wake);
      live.delete(id);
      announce();
    };
  }, [client, key, path, hash]);
}

// A query that also keeps itself fresh. `refetchOnReconnect` is off because that read would carry no mark and so
// would extend the session; the hook reads again when the browser is back online.
export function useLiveQuery<T>(
  key: QueryKey,
  path: string,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const query = useQuery({
    queryKey: key,
    queryFn: ({ signal }) => get<T>(path, signal),
    enabled,
    refetchOnReconnect: false,
  });
  useAutoRefresh(enabled ? { key, path } : null);
  return query;
}

// The oldest successful read among what the screen keeps fresh, and whether any of it is failing now.
export function liveSnapshot(client: QueryClient) {
  let oldest = Infinity;
  let failing = false;
  for (const key of live.values()) {
    const state = client.getQueryState(key);
    if (state?.dataUpdatedAt) oldest = Math.min(oldest, state.dataUpdatedAt);
    if (state?.status === "error") failing = true;
  }
  return oldest === Infinity ? "" : `${oldest}|${failing ? 1 : 0}`;
}

export function subscribeLive(client: QueryClient, notify: () => void) {
  listeners.add(notify);
  const off = client.getQueryCache().subscribe(notify);
  return () => {
    listeners.delete(notify);
    off();
  };
}
