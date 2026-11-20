import { useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Icon } from "./components/icons";
import { FilterChips } from "./components/filter-chips";
import { get, itemId, itemTitle, itemStatus, itemSeverity } from "./api/client";
import type { Resource, Page, Item } from "./api/client";
import type { Dashboard } from "./api/generated/Dashboard";
import { Severity, Status } from "./badges";
import { states, statusNames, titles } from "./constants";
import { DetailPanel } from "./detail-panel";
import { ErrorState } from "./error-state";
import { usePager } from "./pager";
import { severityLabel } from "./severity";

const PAGE_SIZE = 25;
// The list API has no total; derive it from dashboard counts. Origin/severity filters have no count.
function totalCount(
  resource: Resource,
  status: string,
  filtered: boolean,
  d?: Dashboard,
) {
  if (!d || filtered) return undefined;
  const raw = (n: Dashboard["normalization"][string]) => ({
    pending: n.pending,
    succeeded: n.succeeded,
    failed: n.failed,
  });
  const by: Record<string, number> =
    resource === "alerts"
      ? raw(d.normalization.alert)
      : resource === "events"
        ? raw(d.normalization.event)
        : resource === "tickets"
          ? d.ticket_status
          : resource === "incidents"
            ? d.incident_status
            : resource === "cases"
              ? d.case_status
              : d.hunting.statuses;
  return status
    ? (by[status] ?? 0)
    : Object.values(by).reduce((a, b) => a + b, 0);
}
export function ListView({
  resource,
  waiting = false,
  summary,
}: {
  resource: Resource;
  waiting?: boolean;
  summary?: Dashboard;
}) {
  const [search, setSearch] = useSearchParams();
  const status = waiting ? "awaiting_review" : (search.get("status") ?? "");
  const params = new URLSearchParams({ limit: String(PAGE_SIZE) });
  for (const key of ["cursor", "origin", "severity"])
    if (search.get(key) && (resource === "tickets" || key === "cursor"))
      params.set(key, search.get(key)!);
  if (status) params.set("status", status);
  const path = `${resource}?${params}`;
  const query = useQuery({
    queryKey: ["list", path],
    queryFn: ({ signal }) => get<Page>(path, signal),
  });
  const { current, page } = usePager(query.data?.next_cursor);
  function change(key: string, value: string) {
    const next = new URLSearchParams(search);
    next.delete("cursor");
    next.delete("trail");
    next.delete("selected");
    if (value) next.set(key, value);
    else next.delete(key);
    setSearch(next);
  }
  function select(item: Item) {
    const next = new URLSearchParams(search);
    next.set("selected", itemId(item));
    setSearch(next);
  }
  const selected = search.get("selected");
  const total = totalCount(
    resource,
    status,
    resource === "tickets" &&
      !!(search.get("severity") || search.get("origin")),
    summary,
  );
  // An old cursor link can start past the last page; never show N greater than the maximum.
  const last =
    total === undefined
      ? "-"
      : Math.max(Math.ceil(total / PAGE_SIZE), 1, current);
  return (
    <section className="card list-card">
      <div className="list-toolbar">
        <h3>
          {waiting
            ? "승인 대기 Incident"
            : resource === "alerts"
              ? "Alert"
              : resource === "events"
                ? "Event"
                : titles[resource]}{" "}
          목록
        </h3>
        <div className="filters">
          {!waiting && (
            <FilterChips
              label={
                resource === "alerts" || resource === "events"
                  ? "정규화 상태"
                  : "처리 상태"
              }
              name="상태 필터"
              value={status}
              options={states[resource].map((s) => [s, statusNames[s]])}
              onChange={(v) => change("status", v)}
            />
          )}
          {resource === "tickets" && (
            <>
              <FilterChips
                label="심각도"
                name="심각도 필터"
                value={search.get("severity") ?? ""}
                options={[6, 5, 4, 3, 2, 1, 0].map((i) => [
                  String(i),
                  severityLabel(i),
                ])}
                onChange={(v) => change("severity", v)}
              />
              <FilterChips
                label="출처"
                name="출처 필터"
                value={search.get("origin") ?? ""}
                options={["auto", "scenario", "l1", "l3"].map((v) => [v, v])}
                onChange={(v) => change("origin", v)}
              />
            </>
          )}
        </div>
      </div>
      {query.isPending ? (
        <p role="status" className="empty">
          불러오는 중…
        </p>
      ) : query.error ? (
        <ErrorState
          inline
          error={query.error}
          retry={() => void query.refetch()}
        />
      ) : query.data.items.length ? (
        <>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>제목 / ID</th>
                  <th>상태</th>
                  <th>심각도</th>
                  <th>시각</th>
                </tr>
              </thead>
              <tbody>
                {query.data.items.map((item) => (
                  <tr key={itemId(item)} onClick={() => select(item)}>
                    <td>
                      <button className="record-link">{itemTitle(item)}</button>
                      {"origin" in item && (
                        <span className="origin-label">{item.origin}</span>
                      )}
                      <small className="record-id">{itemId(item)}</small>
                    </td>
                    <td>
                      <Status value={itemStatus(item)} />
                    </td>
                    <td>
                      <Severity value={itemSeverity(item)} />
                    </td>
                    <td className="date">
                      {new Date(
                        "fetched_at" in item
                          ? item.fetched_at
                          : "confirmed_at" in item
                            ? item.confirmed_at
                            : item.updated_at,
                      ).toLocaleString("ko-KR")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : (
        <p className="empty">조건에 맞는 데이터가 없습니다.</p>
      )}
      <footer className="pagination">
        <div className="pagination-controls">
          <button
            aria-label="이전 페이지"
            disabled={!search.has("cursor") || query.isFetching}
            onClick={() => page("previous")}
          >
            <Icon name="left" />
          </button>
          <span aria-live="polite">
            {current}/{last}
          </span>
          <button
            aria-label="다음 페이지"
            disabled={
              !query.data?.next_cursor || query.isFetching || !!query.error
            }
            onClick={() => page("next")}
          >
            <Icon name="right" />
          </button>
        </div>
      </footer>
      {selected && (
        <DetailPanel
          key={`${resource}/${selected}`}
          resource={resource}
          id={selected}
          onClose={() => {
            const next = new URLSearchParams(search);
            next.delete("selected");
            setSearch(next);
          }}
        />
      )}
    </section>
  );
}
