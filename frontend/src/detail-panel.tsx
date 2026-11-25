import { useEffect, useRef, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { PanelResizer } from "./components/panel-resizer";
import { usePanelWidth } from "./components/use-panel-width";
import { JsonViewer } from "./components/json-viewer";
import { Button } from "./components/ui/button";
import { get } from "./api/client";
import type { Resource, Detail } from "./api/client";
import { Status } from "./badges";
import { titles } from "./constants";
import { ErrorState } from "./error-state";
import { TicketSections } from "./detail-sections";
import { useLink } from "./links";

function DetailBody({ data }: { data: Detail }) {
  const link = useLink();
  return (
    <>
      {"ticket" in data && "alerts" in data && (
        <TicketSections data={data} link={link} />
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
