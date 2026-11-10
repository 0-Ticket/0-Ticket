import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocation } from "react-router";
import { ApiError, get, send } from "../api/client";
import type { Me } from "../api/generated/Me";

// Opened once per app load; a 401 means "not logged in", so the query resolves to null instead of failing.
// Never refetch it on a timer: the server extends the idle timeout on every request.
export function useMe() {
  return useQuery({
    queryKey: ["me"],
    staleTime: Infinity,
    queryFn: ({ signal }) =>
      get<Me>("auth/me", signal).catch((error: unknown) => {
        if (error instanceof ApiError && error.code === "unauthenticated")
          return null;
        throw error;
      }),
  });
}
export function useCan() {
  const permissions = useMe().data?.permissions ?? [];
  return (...names: string[]) => names.some((n) => permissions.includes(n));
}
// Drops everything the previous user could see, keeping only the session query itself.
export function useSessionReset() {
  const client = useQueryClient();
  return (me: Me | null) => {
    client.setQueryData(["me"], me);
    client.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
  };
}
export function useLogout() {
  const reset = useSessionReset();
  return useMutation({
    mutationFn: () => send("POST", "auth/logout"),
    onSettled: () => reset(null),
  });
}
// Where to go after login: the path saved in router state, never from the URL (no open redirect).
export function useLoginTarget() {
  const state = useLocation().state as { from?: unknown } | null;
  const from = state?.from;
  return typeof from === "string" &&
    from.startsWith("/") &&
    !from.startsWith("//")
    ? from
    : "/";
}
