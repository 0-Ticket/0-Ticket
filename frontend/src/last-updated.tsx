import { useCallback, useSyncExternalStore } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { liveSnapshot, subscribeLive } from "./live";

export function LastUpdated() {
  const client = useQueryClient();
  const subscribe = useCallback(
    (notify: () => void) => subscribeLive(client, notify),
    [client],
  );
  const value = useSyncExternalStore(subscribe, () => liveSnapshot(client));
  if (!value) return null;
  const [at, failing] = value.split("|");
  const time = new Date(Number(at)).toLocaleTimeString("ko-KR");
  return (
    <small className="last-updated" data-failing={failing === "1" || undefined}>
      {failing === "1"
        ? `갱신 실패 · 마지막 성공 ${time}`
        : `마지막 갱신 ${time}`}
    </small>
  );
}
