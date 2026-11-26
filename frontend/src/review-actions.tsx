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

// Shown only while the incident waits for review, and only the buttons the account may use (D-076).
export function ReviewActions({
  id,
  status,
  onApproved,
}: {
  id: string;
  status: string;
  onApproved?: (caseId: string) => void;
}) {
  const can = useCan();
  const client = useQueryClient();
  const [asking, setAsking] = useState(false);
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
  if (status !== "awaiting_review" || (!approve && !reject)) return null;
  return (
    <div className="review-actions">
      {review.isError && (
        <p role="alert" className="review-error">
          {message(review.error)}
        </p>
      )}
      {approve && (
        <Button
          disabled={review.isPending}
          onClick={() => review.mutate({ action: "approve" })}
        >
          승인
        </Button>
      )}
      {reject && (
        <Button
          variant="outline"
          disabled={review.isPending}
          onClick={() => setAsking(true)}
        >
          반려
        </Button>
      )}
      {asking && (
        <RejectDialog
          onCancel={() => setAsking(false)}
          onConfirm={(reason) => {
            setAsking(false);
            review.mutate({ action: "reject", reason });
          }}
        />
      )}
    </div>
  );
}

// The reason is optional and is shown later as plain text. An empty box still rejects (D-082).
function RejectDialog({
  onCancel,
  onConfirm,
}: {
  onCancel: () => void;
  onConfirm: (reason: string) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");
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
        <Button onClick={() => onConfirm(reason.trim())}>반려하기</Button>
      </div>
    </dialog>
  );
}
