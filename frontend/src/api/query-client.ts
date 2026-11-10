import { QueryCache, QueryClient } from "@tanstack/react-query";
import { ApiError } from "./client";

// A 401 `unauthenticated` means the session ended; clearing ["me"] makes the route guard show login.
// 403 `password_change_required` means the cached ["me"] is stale, so it is read again.
// Other 401 codes (invalid_credentials) belong to the form that sent them.
export function createQueryClient() {
  const client: QueryClient = new QueryClient({
    queryCache: new QueryCache({
      onError(error) {
        if (!(error instanceof ApiError)) return;
        if (error.code === "unauthenticated") {
          client.setQueryData(["expired"], true);
          client.setQueryData(["me"], null);
        } else if (error.code === "password_change_required")
          void client.invalidateQueries({ queryKey: ["me"] });
      },
    }),
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false, staleTime: 30_000 },
    },
  });
  return client;
}
