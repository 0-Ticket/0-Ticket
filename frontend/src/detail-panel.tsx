import { useEffect, useRef, type CSSProperties } from "react";
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { PanelResizer } from "./components/panel-resizer";
import { usePanelWidth } from "./components/use-panel-width";
import { JsonViewer } from "./components/json-viewer";
import { Button } from "./components/ui/button";
import { get } from "./api/client";
import type { Resource, Detail } from "./api/client";
import { useCan } from "./auth/session";
import { Severity, Status } from "./badges";
import { resourcePermission, titles } from "./constants";
import { ErrorState } from "./error-state";
import { IncidentGraph } from "./incident-graph";

function internalLink(id: string, resource: Resource, label: string) {
  if (
    !/^(alt|evt|raw|tkt|inc|hnt)_[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(
      id,
    )
  )
    return null;
  return (
    <Button key={id} variant="outline" size="sm" asChild>
      <Link to={`/${resource}?selected=${id}`}>{label}</Link>
    </Button>
  );
}
function DetailBody({ data }: { data: Detail }) {
  const can = useCan();
  // A link to a screen the account cannot open is not offered.
  const link = (id: string, resource: Resource, label: string) =>
    can(resourcePermission[resource])
      ? internalLink(id, resource, label)
      : null;
  return (
    <>
      {"ticket" in data && (
        <>
          <Severity value={data.severity} />
          <div className="links">
            {data.ticket.alert_ids.map((id, i) =>
              link(id, "alerts", `원본 Alert ${i + 1}`),
            )}
            {data.ticket.hunt_id &&
              link(data.ticket.hunt_id, "hunts", "원본 Hunt")}
          </div>
          <h3>Ticket 판정과 근거</h3>
          <JsonViewer value={data.ticket} />
        </>
      )}
      {"artifacts" in data && ( // TicketDetail도 incident 키가 있어 IncidentDetail만 가진 키로 가른다
        <>
          <div className="links">
            {data.incident.ticket_ids.map((id, i) =>
              link(id, "tickets", `원본 Ticket ${i + 1}`),
            )}
          </div>
          <h3>Ticket 연결 그래프</h3>
          <IncidentGraph
            incident={data.incident}
            ticketGraphs={data.ticket_graphs}
          />
          <h3>Incident</h3>
          <JsonViewer value={data.incident} />
          <h3>라운드별 분석 보고서</h3>
          {data.artifacts.length ? (
            data.artifacts.map((a) => (
              <section key={a.id}>
                <h4>분석 라운드 {a.analysis_round}</h4>
                <JsonViewer value={a} />
                {data.proposals
                  .filter((p) => p.artifact_id === a.id)
                  .map((p) => (
                    <div className="proposal" key={p.id}>
                      <strong>
                        {p.kind === "response"
                          ? "대응 방안 제안"
                          : "탐지 룰 제안"}
                      </strong>
                      <pre>{p.detail}</pre>
                    </div>
                  ))}
              </section>
            ))
          ) : (
            <p>분석 보고서가 없습니다.</p>
          )}
          <div className="review-actions">
            <p>승인·반려 기능은 아직 제공하지 않습니다.</p>
            <Button disabled>승인</Button>
            <Button disabled variant="outline">
              반려
            </Button>
          </div>
        </>
      )}
      {"case" in data && (
        <>
          <div className="links">
            {link(data.case.incident_id, "incidents", "원본 Incident")}
          </div>
          <h3>승인된 Case</h3>
          <JsonViewer value={data.case} />
        </>
      )}
      {"raw_record" in data && (
        <>
          <Status value={data.normalize_status} />
          {data.error_code && <p>실패 코드: {data.error_code}</p>}
          <h3>{data.record ? "정규화 결과 · OCSF" : "정규화 결과 없음"}</h3>
          {data.record && <JsonViewer value={data.record} />}
          <h3>수집 원본</h3>
          <JsonViewer
            value={data.raw_record}
            rawText={data.raw_record.original_text}
          />
        </>
      )}
      {"hunt" in data && (
        <>
          <div className="links">
            {data.ticket_id && link(data.ticket_id, "tickets", "승격 Ticket")}
          </div>
          <h3>가설과 검증 결과</h3>
          <JsonViewer value={data.hunt} />
          <h3>검증 과정 · 실행 요약</h3>
          {data.runs.length ? (
            data.runs.map((r) => (
              <div key={r.run_id} className="proposal">
                <strong>
                  {r.task ?? "실행"} · {r.outcome}
                </strong>
                <JsonViewer value={r} />
              </div>
            ))
          ) : (
            <p>실행 기록이 없습니다.</p>
          )}
          <h3>ATT&amp;CK 기법</h3>
          <JsonViewer value={data.techniques} />
        </>
      )}
    </>
  );
}
export function DetailPanel({
  resource,
  id,
  onClose,
}: {
  resource: Resource;
  id: string;
  onClose: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const [width, setWidth] = usePanelWidth("panel-width:detail", 650);
  const query = useQuery({
    queryKey: ["detail", resource, id],
    queryFn: ({ signal }) =>
      get<Detail>(`${resource}/${encodeURIComponent(id)}`, signal),
  });
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className="detail-panel"
      style={{ "--panel-w": `${width}px` } as CSSProperties}
      aria-labelledby="detail-title"
      onCancel={onClose}
    >
      <PanelResizer width={width} initial={650} onChange={setWidth} />
      <header>
        <div>
          <span className="eyebrow">RECORD DETAIL</span>
          <h2 id="detail-title">
            {resource === "alerts"
              ? "Alert"
              : resource === "events"
                ? "Event"
                : titles[resource]}{" "}
            상세
          </h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="상세 닫기">
          ✕
        </Button>
      </header>
      <div className="detail-content">
        {query.isPending ? (
          <p role="status">불러오는 중…</p>
        ) : query.error ? (
          <ErrorState
            inline
            error={query.error}
            retry={() => void query.refetch()}
          />
        ) : (
          <DetailBody data={query.data} />
        )}
      </div>
    </dialog>
  );
}
