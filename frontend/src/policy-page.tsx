import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, send } from "./api/client";
import type { TicketingPolicyResponse as Policy } from "./api/generated/TicketingPolicyResponse";
import { Button } from "./components/ui/button";
import { ErrorState } from "./error-state";
import { useCan } from "./auth/session";

function PolicyForm({ stored, canEdit }: { stored: Policy; canEdit: boolean }) {
  const client = useQueryClient();
  const [mode, setMode] = useState(stored.mode);
  // The API lists only chosen rules (no catalog), so rules not yet chosen exist only while editing.
  const [known, setKnown] = useState(stored.scenario_rule_ids);
  const [chosen, setChosen] = useState(new Set(stored.scenario_rule_ids));
  const [adding, setAdding] = useState("");
  const save = useMutation<Policy, Error, Policy>({
    mutationFn: (body) => send<Policy>("PUT", "ticketing-policy", body),
    onSuccess: (saved) => client.setQueryData(["policy"], saved),
  });
  function cancel() {
    setMode(stored.mode);
    setKnown(stored.scenario_rule_ids);
    setChosen(new Set(stored.scenario_rule_ids));
    setAdding("");
    save.reset();
  }
  function add() {
    const id = adding.trim();
    if (!id) return;
    if (!known.includes(id)) setKnown([...known, id]);
    setChosen(new Set(chosen).add(id));
    setAdding("");
  }
  return (
    <section className="card policy-card">
      {!canEdit && (
        <div role="status" className="banner banner-info">
          <strong>읽기 전용이에요</strong>
          <p>
            현재 정책은 볼 수만 있어요. 변경하려면 policy.update 권한이
            필요해요.
          </p>
        </div>
      )}
      {save.isSuccess && (
        <div role="status" className="banner banner-success">
          <strong>정책을 저장했어요</strong>
          <p>새 Ticket 정책이 바로 적용돼요.</p>
        </div>
      )}
      {save.isError && (
        <div role="alert" className="banner banner-error">
          <strong>정책을 저장하지 못했어요</strong>
          <p>
            서버에서 요청을 처리하지 못했어요. 입력한 내용은 그대로 남아 있어요.
            잠시 후 다시 저장해 주세요.
          </p>
        </div>
      )}
      <fieldset disabled={!canEdit}>
        <legend>Ticket 생성 방식</legend>
        <label className="perm">
          <input
            type="radio"
            name="mode"
            checked={mode === "auto"}
            onChange={() => setMode("auto")}
          />
          <span>자동 (auto)</span>
          <small>수집된 Alert에 대해 Ticket을 자동으로 만들어요.</small>
        </label>
        <label className="perm">
          <input
            type="radio"
            name="mode"
            checked={mode === "scenario"}
            onChange={() => setMode("scenario")}
          />
          <span>시나리오 (scenario)</span>
          <small>선택한 시나리오 규칙과 일치할 때만 Ticket을 만들어요.</small>
        </label>
      </fieldset>
      <fieldset disabled={!canEdit}>
        <legend>시나리오 규칙</legend>
        <p className="auth-hint">
          {mode === "scenario"
            ? "일치하면 Ticket을 만들 규칙을 선택하세요"
            : "scenario 모드에서만 사용돼요"}
        </p>
        {known.map((id) => (
          <label key={id} className="perm">
            <input
              type="checkbox"
              checked={chosen.has(id)}
              onChange={(e) => {
                const next = new Set(chosen);
                if (e.target.checked) next.add(id);
                else next.delete(id);
                setChosen(next);
              }}
            />
            <span>{id}</span>
          </label>
        ))}
        {canEdit && (
          <div className="field">
            <label htmlFor="new-rule">규칙 ID 추가</label>
            <input
              id="new-rule"
              value={adding}
              maxLength={200}
              onChange={(e) => setAdding(e.target.value)}
            />
            <Button variant="outline" size="sm" onClick={add}>
              추가
            </Button>
          </div>
        )}
      </fieldset>
      {canEdit && (
        <div className="actions">
          <Button variant="outline" onClick={cancel}>
            변경 취소
          </Button>
          <Button
            disabled={save.isPending}
            onClick={() =>
              save.mutate({
                mode,
                scenario_rule_ids: known.filter((id) => chosen.has(id)),
              })
            }
          >
            저장
          </Button>
        </div>
      )}
    </section>
  );
}

export function PolicyPage() {
  const can = useCan();
  const query = useQuery({
    queryKey: ["policy"],
    queryFn: ({ signal }) => get<Policy>("ticketing-policy", signal),
  });
  if (query.isPending) return <p role="status">불러오는 중…</p>;
  if (query.error)
    return (
      <ErrorState
        needs="policy.read"
        error={query.error}
        retry={() => void query.refetch()}
      />
    );
  const canEdit = can("policy.update");
  return (
    <>
      {canEdit && (
        <div className="policy-toolbar">
          {/* No backend yet (CSV upload): the button is shown but does nothing. */}
          <Button type="button" variant="outline" className="btn btn-secondary">
            CSV로 등록하기
          </Button>
        </div>
      )}
      <PolicyForm stored={query.data} canEdit={canEdit} />
    </>
  );
}
