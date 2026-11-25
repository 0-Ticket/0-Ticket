import { useState } from "react";
import type { IncidentDetail } from "../api/generated/IncidentDetail";
import { FilterChips } from "../components/filter-chips";
import { Clip, Pager, SortButton } from "./kit";
import {
  entityRows,
  nextSort,
  paginate,
  sortEntities,
  type Dir,
  type EntitySort,
  when,
} from "./model";

const PAGE_SIZE = 20;

export function EntityTable({ detail }: { detail: IncidentDetail }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [sort, setSort] = useState<{ key: EntitySort; dir: Dir }>({
    key: "tickets",
    dir: "desc",
  });
  const [page, setPage] = useState(1);
  const all = entityRows(detail);
  if (all.length === 0) return <p className="empty">엔티티가 없습니다.</p>;
  const counts = new Map<string, number>();
  for (const row of all) counts.set(row.type, (counts.get(row.type) ?? 0) + 1);
  const needle = query.trim().toLowerCase();
  const rows = sortEntities(
    all.filter(
      (r) =>
        (kind === "" || r.type === kind) &&
        (needle === "" || r.value.toLowerCase().includes(needle)),
    ),
    sort.key,
    sort.dir,
  );
  const view = paginate(rows, page, PAGE_SIZE);
  const header = (key: EntitySort, label: string) => (
    <th>
      <SortButton
        label={label}
        active={sort.key === key}
        dir={sort.dir}
        onClick={() => setSort(nextSort(sort, key))}
      />
    </th>
  );
  return (
    <section className="card incident-table-card">
      <div className="incident-table-tools">
        <input
          type="search"
          aria-label="엔티티 검색"
          placeholder="값 검색"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(1);
          }}
        />
        <FilterChips
          label="종류"
          name="종류 필터"
          value={kind}
          options={[...counts].map(([type, n]) => [type, `${type} ${n}`])}
          onChange={(v) => {
            setKind(v);
            setPage(1);
          }}
        />
        <span className="incident-count">{`${rows.length}개 엔티티`}</span>
      </div>
      <div className="table-scroll">
        <table aria-label="엔티티 표">
          <thead>
            <tr>
              {header("type", "종류")}
              <th>값</th>
              <th>role</th>
              {header("tickets", "연결")}
              {header("first", "최초 관측")}
            </tr>
          </thead>
          <tbody>
            {view.rows.map((r) => (
              <tr key={r.key}>
                <td>{r.type}</td>
                <td>
                  <Clip text={r.value} label="값" />
                </td>
                <td>{r.role ?? "—"}</td>
                <td>{`Ticket ${r.tickets} · Alert ${r.alerts}`}</td>
                <td className="date">
                  {r.first === null ? "—" : when(r.first)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && (
        <p className="empty">조건에 맞는 엔티티가 없습니다.</p>
      )}
      <Pager page={view.page} pages={view.pages} onChange={setPage} />
    </section>
  );
}
