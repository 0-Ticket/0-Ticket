import type { RawPage } from "./generated/RawPage";
import type { TicketPage } from "./generated/TicketPage";
import type { IncidentPage } from "./generated/IncidentPage";
import type { CasePage } from "./generated/CasePage";
import type { HuntPage } from "./generated/HuntPage";
import type { RawDetail } from "./generated/RawDetail";
import type { TicketDetail } from "./generated/TicketDetail";
import type { IncidentDetail } from "./generated/IncidentDetail";
import type { CaseDetail } from "./generated/CaseDetail";
import type { HuntDetail } from "./generated/HuntDetail";
export type Resource =
  "alerts" | "events" | "tickets" | "incidents" | "cases" | "hunts";
export type Page = RawPage | TicketPage | IncidentPage | CasePage | HuntPage;
export type Item = Page["items"][number];
export type Detail =
  RawDetail | TicketDetail | IncidentDetail | CaseDetail | HuntDetail;
export async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(
    new URL(`/api/${path}`, window.location.origin),
    { signal },
  );
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "대상을 찾을 수 없습니다."
        : "데이터를 불러오지 못했습니다. 잠시 후 다시 시도하세요.",
    );
  return response.json() as Promise<T>;
}
export function itemId(item: Item) {
  return "raw_id" in item ? item.raw_id : item.id;
}
export function itemTitle(item: Item) {
  return "title" in item && item.title
    ? item.title
    : "hypothesis" in item
      ? item.hypothesis
      : "raw_id" in item
        ? "원본 " + item.raw_id
        : item.id;
}
export function itemStatus(item: Item) {
  return "normalize_status" in item ? item.normalize_status : item.status;
}
export function itemSeverity(item: Item) {
  return "display_severity" in item
    ? item.display_severity
    : "severity" in item
      ? item.severity
      : null;
}
