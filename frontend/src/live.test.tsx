import type { ReactNode } from "react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { act, render, renderHook, screen } from "@testing-library/react";
import { QueryClientProvider } from "@tanstack/react-query";
import { ApiError, get } from "./api/client";
import { createQueryClient } from "./api/query-client";
import { LastUpdated } from "./last-updated";
import { delay, failure, useAutoRefresh } from "./live";

vi.mock("./api/client", async (original) => ({
  ...(await original<typeof import("./api/client")>()),
  get: vi.fn(),
}));
const read = vi.mocked(get);
const target = { key: ["detail", "tickets", "tkt_1"], path: "tickets/tkt_1" };

let client = createQueryClient();
const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={client}>{children}</QueryClientProvider>
);
function visible(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => state,
  });
  document.dispatchEvent(new Event("visibilitychange"));
}
const tick = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

beforeEach(() => {
  vi.useFakeTimers();
  client = createQueryClient();
  read.mockReset().mockResolvedValue({ ok: true });
  visible("visible");
});
afterEach(() => vi.useRealTimers());

test("the wait doubles with each failure in a row and stops at a minute", () => {
  expect([0, 1, 2, 3, 4, 9].map(delay)).toEqual([
    10_000, 20_000, 40_000, 60_000, 60_000, 60_000,
  ]);
});

test("a failed read keeps the screen only for network errors and 5xx that come with data", () => {
  const network = new TypeError("Failed to fetch");
  expect(failure({ error: null, data: 1 })).toBeNull();
  expect(failure({ error: network, data: 1 })).toBeNull();
  expect(
    failure({ error: new ApiError(503, "db_unavailable"), data: 1 }),
  ).toBeNull();
  for (const status of [400, 401, 403, 404])
    expect(
      failure({ error: new ApiError(status, "x"), data: 1 }),
    ).not.toBeNull();
  expect(failure({ error: network, data: undefined })).toBe(network);
});

test("it reads again every 10 seconds and marks each read as automatic", async () => {
  renderHook(() => useAutoRefresh(target), { wrapper });
  await tick(9_999);
  expect(read).not.toHaveBeenCalled();
  await tick(1);
  expect(read).toHaveBeenCalledTimes(1);
  expect(read).toHaveBeenLastCalledWith(target.path, expect.anything(), true);
  await tick(10_000);
  expect(read).toHaveBeenCalledTimes(2);
});

test("failures stretch the wait to 20, 40 and 60 seconds, and a success brings it back to 10", async () => {
  read.mockRejectedValue(new TypeError("Failed to fetch"));
  renderHook(() => useAutoRefresh(target), { wrapper });
  for (const wait of [10_000, 20_000, 40_000, 60_000, 60_000]) {
    const before = read.mock.calls.length;
    await tick(wait - 1);
    expect(read).toHaveBeenCalledTimes(before);
    await tick(1);
    expect(read).toHaveBeenCalledTimes(before + 1);
  }
  read.mockResolvedValue({ ok: true });
  await tick(60_000);
  const before = read.mock.calls.length;
  await tick(10_000);
  expect(read).toHaveBeenCalledTimes(before + 1);
});

test("a hidden tab sends nothing and coming back reads once at once", async () => {
  renderHook(() => useAutoRefresh(target), { wrapper });
  visible("hidden");
  await tick(120_000);
  expect(read).not.toHaveBeenCalled();
  visible("visible");
  await tick(0);
  expect(read).toHaveBeenCalledTimes(1);
  await tick(10_000);
  expect(read).toHaveBeenCalledTimes(2);
});

test("coming back online reads at once, as an automatic read", async () => {
  read.mockRejectedValue(new TypeError("Failed to fetch"));
  renderHook(() => useAutoRefresh(target), { wrapper });
  await tick(10_000); // one failure: the next wait is 20 s
  read.mockResolvedValue({ ok: true });
  window.dispatchEvent(new Event("online"));
  await tick(0);
  expect(read).toHaveBeenCalledTimes(2);
  expect(read).toHaveBeenLastCalledWith(target.path, expect.anything(), true);
  await tick(10_000); // the wait is back to 10 s
  expect(read).toHaveBeenCalledTimes(3);
});

test("leaving the screen, or no target, sends nothing more", async () => {
  const { unmount } = renderHook(() => useAutoRefresh(target), { wrapper });
  await tick(10_000);
  unmount();
  window.dispatchEvent(new Event("online"));
  await tick(120_000);
  expect(read).toHaveBeenCalledTimes(1);
  read.mockClear();
  renderHook(() => useAutoRefresh(null), { wrapper });
  await tick(120_000);
  expect(read).not.toHaveBeenCalled();
});

test("a 403 stops it until the user's own retry succeeds", async () => {
  read.mockRejectedValue(new ApiError(403, "permission_denied"));
  renderHook(() => useAutoRefresh(target), { wrapper });
  await tick(10_000);
  expect(read).toHaveBeenCalledTimes(1);
  await tick(300_000);
  expect(read).toHaveBeenCalledTimes(1);
  await act(() =>
    client.fetchQuery({
      queryKey: target.key,
      queryFn: () => ({ ok: true }),
      staleTime: 0,
    }),
  );
  await tick(10_000);
  expect(read).toHaveBeenCalledTimes(2);
});

test("an error already on screen from the first load (404) means no automatic read at all", async () => {
  await client
    .fetchQuery({
      queryKey: target.key,
      queryFn: () => Promise.reject(new ApiError(404, "not_found")),
    })
    .catch(() => undefined);
  renderHook(() => useAutoRefresh(target), { wrapper });
  await tick(120_000);
  expect(read).not.toHaveBeenCalled();
});

test("the last updated text shows the oldest success, and says so when a read fails", async () => {
  client.setQueryData(["a"], 1, { updatedAt: Date.UTC(2026, 10, 27, 1, 0, 0) });
  client.setQueryData(["b"], 2, {
    updatedAt: Date.UTC(2026, 10, 27, 1, 0, 30),
  });
  const time = (ms: number) => new Date(ms).toLocaleTimeString("ko-KR");
  function Both() {
    useAutoRefresh({ key: ["a"], path: "a" });
    useAutoRefresh({ key: ["b"], path: "b" });
    return <LastUpdated />;
  }
  render(
    <QueryClientProvider client={client}>
      <Both />
    </QueryClientProvider>,
  );
  expect(
    screen.getByText(`마지막 갱신 ${time(Date.UTC(2026, 10, 27, 1, 0, 0))}`),
  ).toBeInTheDocument();
  read.mockRejectedValue(new TypeError("Failed to fetch"));
  await tick(10_000);
  expect(screen.getByText(/^갱신 실패 · 마지막 성공/)).toBeInTheDocument();
});
