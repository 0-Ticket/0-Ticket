import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, send } from "./api/client";
import type { ReviewResult } from "./api/generated/ReviewResult";
import { useCan } from "./auth/session";
import { Button } from "./components/ui/button";
import { statusNames } from "./constants";

type Action = { action: "approve" } | { action: "reject"; reason?: string };

const REASON_MAX = 500; // Same limit as the API (D-082).

function message(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 409)
      return `이미 처리된 Incident예요${error.state ? `(현재 상태: ${statusNames[error.state] ?? error.state})` : ""}. 최신 상태를 다시 불러왔어요.`;
    if (error.status === 403) return "이 작업을 할 권한이 없어요.";
    if (error.status === 404) return "Incident를 찾을 수 없어요.";
  }
  return "처리하지 못했어요. 잠시 후 다시 시도해 주세요.";
}

// What the incident was like when the reject window opened; the screen refreshes itself while the window is open.
type Opened = { status: string; reviewRound: number; analysisRound: number };

// The buttons show only while the incident waits for review, and only those the account may use (D-076). The window
// and a refused request's note stay whatever the status becomes, so a refresh never takes away what the user typed.
export function ReviewActions({
  id,
  status,
  reviewRound,
  analysisRound,
  onApproved,
}: {
  id: string;
  status: string;
  reviewRound: number;
  analysisRound: number;
  onApproved?: (caseId: string) => void;
}) {
  const can = useCan();
  const client = useQueryClient();
  const [opened, setOpened] = useState<Opened | null>(null);
  const review = useMutation<ReviewResult, Error, Action>({
    mutationFn: (request) =>
      send<ReviewResult>(
        "POST",
        `incidents/${encodeURIComponent(id)}/${request.action}`,
        request.action === "reject" && request.reason
          ? { reason: request.reason }
          : undefined,
      ),
    onSuccess: (result) => {
      if (result.case_id) onApproved?.(result.case_id);
    },
    // The result may differ from what the screen showed (409), so everything is read again.
    onSettled: () => client.invalidateQueries(),
  });
  const approve = can("incident.approve");
  const reject = can("incident.reject");
  const waiting = status === "awaiting_review" && (approve || reject);
  if (!waiting && !review.isError && !opened) return null;
  return (
    <div className="review-actions">
      {review.isError && (
        <p role="alert" className="review-error">
          {message(review.error)}
        </p>
      )}
      {waiting && approve && (
        <Button
          disabled={review.isPending}
          onClick={() => review.mutate({ action: "approve" })}
        >
          승인
        </Button>
      )}
      {waiting && reject && (
        <Button
          variant="outline"
          disabled={review.isPending}
          onClick={() => {
            review.reset();
            setOpened({ status, reviewRound, analysisRound });
          }}
        >
          반려
        </Button>
      )}
      {opened && (
        <RejectDialog
          opened={opened}
          now={{ status, reviewRound, analysisRound }}
          onCancel={() => setOpened(null)}
          onConfirm={(reason) => {
            setOpened(null);
            review.mutate({ action: "reject", reason });
          }}
        />
      )}
    </div>
  );
}

// The reason is optional and is shown later as plain text. An empty box still rejects (D-082).
function RejectDialog({
  opened,
  now,
  onCancel,
  onConfirm,
}: {
  opened: Opened;
  now: Opened;
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
  // Once the incident has moved on it stays flagged, even if it comes back to the same status.
  const [moved, setMoved] = useState(false);
  const closed = now.status !== "awaiting_review";
  const differs =
    closed ||
    now.reviewRound !== opened.reviewRound ||
    now.analysisRound !== opened.analysisRound;
  if (differs && !moved) setMoved(true);
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  return (
    <dialog
      ref={dialog}
      className="review-dialog"
      aria-labelledby="reject-title"
      onCancel={onCancel}
    >
      <h2 id="reject-title">Incident 반려</h2>
      <p>반려하면 L2가 다시 분석해요. 사유는 재분석에 참고로 전달돼요.</p>
      {closed ? (
        <p role="status" className="review-error">
          {`현재 상태: ${statusNames[now.status] ?? now.status}. 반려할 수 없어요.`}
        </p>
      ) : (
        (moved || differs) && (
          <p role="status" className="review-error">
            분석·검토가 바뀌었어요. 사유를 확인하세요.
          </p>
        )
      )}
      <div className="field">
        <label htmlFor="reject-reason">반려 사유 (선택)</label>
        <textarea
          id="reject-reason"
          value={reason}
          maxLength={REASON_MAX}
          rows={4}
          onChange={(event) => setReason(event.target.value)}
        />
        <small>{`${reason.length}/${REASON_MAX}`}</small>
      </div>
      <div className="review-dialog-actions">
        <Button variant="outline" onClick={onCancel}>
          취소
        </Button>
        <Button disabled={closed} onClick={() => onConfirm(reason.trim())}>
          반려하기
        </Button>
      </div>
    </dialog>
  );
}
