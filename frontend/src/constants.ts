import type { Resource } from "./api/client";

export const resourcePermission: Record<Resource, string> = {
  alerts: "alert.read",
  events: "event.read",
  tickets: "ticket.read",
  incidents: "incident.read",
  cases: "case.read",
  hunts: "hunt.read",
};
export const titles: Record<Resource, string> = {
  alerts: "Alert / Event",
  events: "Alert / Event",
  tickets: "Ticket",
  incidents: "Incident",
  cases: "Case",
  hunts: "Hunting",
};
export const statusNames: Record<string, string> = {
  pending: "대기",
  succeeded: "성공",
  failed: "실패",
  new: "판정 대기",
  held: "보류",
  closed: "오탐 종결",
  escalated: "L2 대기",
  linked: "Incident 연결",
  analyzing: "분석 중",
  awaiting_review: "승인 대기",
  confirmed: "승인 / 확인됨",
  human_handling: "사람 처리",
  dismissed: "위협 아님",
  open: "열림",
  in_progress: "처리 중",
  resolved: "해결됨",
  rejected: "기각",
  inconclusive: "판단 유보",
};
export const states: Record<Resource, string[]> = {
  alerts: ["pending", "succeeded", "failed"],
  events: ["pending", "succeeded", "failed"],
  tickets: ["new", "held", "closed", "escalated", "linked"],
  incidents: [
    "analyzing",
    "held",
    "awaiting_review",
    "confirmed",
    "human_handling",
    "dismissed",
  ],
  cases: ["open", "in_progress", "resolved"],
  hunts: ["pending", "confirmed", "rejected", "inconclusive", "failed"],
};
