import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, send } from "./api/client";
import type { ReviewResult } from "./api/generated/ReviewResult";
import { useCan } from "./auth/session";
import { Button } from "./components/ui/button";
import { statusNames } from "./constants";

type Action = "approve" | "reject";

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
  const review = useMutation<ReviewResult, Error, Action>({
    mutationFn: (action) =>
      send<ReviewResult>(
        "POST",
        `incidents/${encodeURIComponent(id)}/${action}`,
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
          onClick={() => review.mutate("approve")}
        >
          승인
        </Button>
      )}
      {reject && (
        <Button
          variant="outline"
          disabled={review.isPending}
          onClick={() => review.mutate("reject")}
        >
          반려
        </Button>
      )}
    </div>
  );
}
