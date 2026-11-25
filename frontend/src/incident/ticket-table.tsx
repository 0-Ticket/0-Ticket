import { useState } from "react";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { Severity } from "../badges";
import { FilterChips } from "../components/filter-chips";
import { useLink } from "../links";
import { Clip, Pager, SortButton } from "./kit";
import {
  nextSort,
  paginate,
  searchTickets,
  sortTickets,
  statusText,
  when,
  type Dir,
  type TicketSort,
} from "./model";

const PAGE_SIZE = 10;

export function TicketTable({ detail }: { detail: IncidentDetail }) {
  const link = useLink();
  const [query, setQuery] = useState("");
  const [decision, setDecision] = useState("");
  const [sort, setSort] = useState<{ key: TicketSort; dir: Dir }>({
    key: "created_at",
    dir: "desc",
  });
  const [page, setPage] = useState(1);
  const graphs = new Map(
    (detail.ticket_graphs ?? []).map((g) => [g.ticket_id, g]),
  );
  const rows = sortTickets(
    searchTickets(detail.tickets, query).filter((t) =>
      decision === ""
        ? true
        : decision === "pending"
          ? !t.decision
          : t.decision === decision,
    ),
    sort.key,
    sort.dir,
  );
  const view = paginate(rows, page, PAGE_SIZE);
  const header = (key: TicketSort, label: string) => (
    <th>
      <SortButton
        label={label}
        active={sort.key === key}
        dir={sort.dir}
        onClick={() => setSort(nextSort(sort, key))}
      />
    </th>
  );
  if (detail.tickets.length === 0) return null;
  return (
    <section className="card incident-table-card">
      <div className="incident-table-tools">
        <input
          type="search"
          aria-label="Ticket 검색"
          placeholder="제목 또는 ID 검색"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
        <FilterChips
          label="판정"
          name="판정 필터"
          value={decision}
          options={[
            ["malicious", "malicious"],
            ["undetermined", "undetermined"],
            ["benign", "benign"],
            ["pending", "판정 전"],
          ]}
          onChange={(v) => {
            setDecision(v);
            setPage(1);
          }}
        />
        <span className="incident-count">{`${rows.length}개 Ticket`}</span>
      </div>
      <div className="table-scroll">
        <table aria-label="Ticket 표">
          <thead>
            <tr>
              <th>제목 / ID</th>
              {header("decision", "판정")}
              {header("severity", "위험도")}
              {header("created_at", "시각")}
              {header("evidence_count", "근거 수")}
              <th>분류 탐색</th>
            </tr>
          </thead>
          <tbody>
            {view.rows.map((t) => (
              <tr key={t.id}>
                <td>
                  <strong className="incident-cell-title">{t.title}</strong>
                  <Clip text={t.id} label="Ticket ID" />
                  {link(t.id, "tickets", "상세 보기", `${t.title} Ticket 상세`)}
                </td>
                <td>{t.decision ?? "—"}</td>
                <td>
                  <Severity value={t.severity} />
                </td>
                <td className="date">{when(t.created_at)}</td>
                <td>{`${t.evidence_count}개`}</td>
                <td>{statusText(graphs.get(t.id))}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p className="empty">조건에 맞는 Ticket이 없습니다.</p>
      )}
      <Pager page={view.page} pages={view.pages} onChange={setPage} />
    </section>
  );
}
