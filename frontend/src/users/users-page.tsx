import { useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, get, send } from "../api/client";
import type { PermissionList } from "../api/generated/PermissionList";
import type { UserItem } from "../api/generated/UserItem";
import type { UserList } from "../api/generated/UserList";
import { Icon } from "../components/icons";
import { Banner } from "../components/banner";
import { LineIcon } from "../components/line-icon";
import { Button } from "../components/ui/button";
import { usePager } from "../pager";
import { useMe } from "../auth/session";
import { ErrorState } from "../error-state";

const PAGE_SIZE = 25;
const statuses: [string, string][] = [
  ["pending", "승인 대기"],
  ["active", "활성"],
  ["rejected", "거절"],
  ["disabled", "중지"],
];
const statusName = Object.fromEntries(statuses);
const failures: Record<string, [string, string]> = {
  last_admin: [
    "마지막 활성 admin이에요",
    "활성 admin이 한 명뿐이라 중지하거나 역할을 낮출 수 없어요. 다른 admin을 먼저 지정해 주세요.",
  ],
  invalid_state: [
    "지금은 할 수 없는 작업이에요",
    "이미 처리됐거나 상태가 바뀐 사용자예요. 목록을 새로고침해 현재 상태를 확인해 주세요.",
  ],
  invalid_target: [
    "이 사용자에게는 적용할 수 없어요",
    "대상 사용자에게 요청한 작업을 적용할 수 없어요. 대상이 admin이거나 본인 계정인지 확인해 주세요.",
  ],
  forbidden: [
    "이 작업을 할 권한이 없어요",
    "이 작업에 필요한 권한이 없어요. admin만 할 수 있는 작업이거나 user.approve 권한이 필요해요.",
  ],
  not_found: ["사용자를 찾을 수 없어요", "목록을 새로고침해 주세요."],
};
const labels: Record<string, string> = {
  "dashboard.read": "대시보드 조회",
  "alert.read": "Alert 조회",
  "event.read": "Event 조회",
  "ticket.read": "Ticket 조회",
  "incident.read": "Incident 조회",
  "case.read": "Case 조회",
  "hunt.read": "Hunting 조회",
  "news.read": "위협 뉴스 조회",
  "policy.read": "Ticket 정책 조회",
  "policy.update": "Ticket 정책 변경",
  "user.read": "사용자 목록 조회",
  "user.approve": "가입 승인·거절·중지·비밀번호 재설정",
  "user.permission": "권한 편집",
  "incident.approve": "Incident 승인",
  "incident.reject": "Incident 반려",
  "incident.close": "Incident 종결",
};
// No API applies these yet (#284), so they can be shown but not changed.
const NOT_READY = new Set([
  "incident.approve",
  "incident.reject",
  "incident.close",
]);
// Not shown in the editor: the news screen was removed (#286), so the permission does nothing.
// It stays in `chosen`, so saving still sends the value the user already has.
const HIDDEN = new Set(["news.read"]);
const groups: [string, (name: string) => boolean][] = [
  ["조회", (n) => n.endsWith(".read")],
  ["정책 변경", (n) => n === "policy.update"],
  ["사용자 관리", (n) => n.startsWith("user.")],
  ["Incident 처리", (n) => NOT_READY.has(n)],
];
const emptyTitle: Record<string, string> = {
  pending: "승인 대기 사용자가 없어요",
  active: "활성 사용자가 없어요",
  rejected: "거절된 사용자가 없어요",
  disabled: "중지된 사용자가 없어요",
};
const statusPill: Record<string, string> = {
  pending: "pill pill-warn",
  active: "pill pill-ok",
};
const date = (ms: number | null) =>
  ms === null ? "—" : new Date(ms).toLocaleDateString("sv-SE");

type Act = {
  method: "POST" | "PATCH" | "PUT";
  path: string;
  body?: unknown;
  // The temporary password is read from the input at send time, so it is never a mutation variable.
  temporary?: boolean;
  leaves?: boolean;
};

function Failure({ error }: { error: Error }) {
  const code = error instanceof ApiError ? error.code : "";
  const [title, body] = failures[code] ?? [
    "작업하지 못했어요",
    "서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.",
  ];
  return (
    <Banner tone="error" title={title}>
      {body}
    </Banner>
  );
}
function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

function PermissionEditor({
  user,
  mine,
  locked,
  run,
}: {
  user: UserItem;
  mine: string[];
  locked: string | null;
  run: (act: Act) => void;
}) {
  const catalog = useQuery({
    queryKey: ["permissions"],
    queryFn: ({ signal }) => get<PermissionList>("permissions", signal),
  });
  // The whole list is replaced on save, so values of items that cannot be edited stay in the body.
  const [chosen, setChosen] = useState(() => new Set(user.permissions));
  if (catalog.isPending) return <p role="status">권한 불러오는 중…</p>;
  if (catalog.error)
    return (
      <ErrorState
        inline
        error={catalog.error}
        retry={() => void catalog.refetch()}
      />
    );
  const names = catalog.data.permissions.filter((p) => !HIDDEN.has(p.name));
  return (
    <Section title="권한 편집">
      {locked && <p className="auth-hint">{locked}</p>}
      {groups.map(([group, test]) => {
        const rows = names.filter((p) => test(p.name));
        return (
          rows.length > 0 && (
            <fieldset key={group} disabled={!!locked}>
              <legend>{group}</legend>
              {rows.map((p) => {
                const fixed = NOT_READY.has(p.name) || !mine.includes(p.name);
                return (
                  <label key={p.name} className="perm">
                    <input
                      type="checkbox"
                      checked={chosen.has(p.name)}
                      disabled={fixed}
                      onChange={(e) => {
                        const next = new Set(chosen);
                        if (e.target.checked) next.add(p.name);
                        else next.delete(p.name);
                        setChosen(next);
                      }}
                    />
                    <code>{p.name}</code>
                    <span>{labels[p.name] ?? ""}</span>
                    {p.analyst_default && <small>기본 지급</small>}
                    {NOT_READY.has(p.name) && <small>준비 중</small>}
                    {!NOT_READY.has(p.name) && !mine.includes(p.name) && (
                      <small>내게 없는 권한</small>
                    )}
                  </label>
                );
              })}
            </fieldset>
          )
        );
      })}
      <Button
        className="btn btn-primary btn-block"
        disabled={!!locked}
        onClick={() =>
          run({
            method: "PUT",
            path: "/permissions",
            body: { permissions: [...chosen].sort() },
          })
        }
      >
        권한 저장
      </Button>
    </Section>
  );
}

function UserPanel({
  user,
  activeAdmins,
  onClose,
}: {
  user: UserItem;
  activeAdmins: number;
  onClose: () => void;
}) {
  const me = useMe().data!;
  const client = useQueryClient();
  const dialog = useRef<HTMLDialogElement>(null);
  const temporary = useRef<HTMLInputElement>(null);
  const role = useRef<HTMLSelectElement>(null);
  const [saved, setSaved] = useState(false);
  const isAdmin = me.role === "admin";
  const canApprove = me.permissions.includes("user.approve");
  const canEditPermissions = me.permissions.includes("user.permission");
  const self = user.id === me.id;
  const adminTarget = user.role === "admin";
  const lastAdmin =
    adminTarget && user.status === "active" && activeAdmins <= 1;
  const blocked = adminTarget && !isAdmin;
  useEffect(() => {
    const element = dialog.current;
    element?.showModal();
    return () => element?.close();
  }, []);
  const mutation = useMutation<UserItem, Error, Act>({
    mutationFn: (act) =>
      send<UserItem>(
        act.method,
        `users/${user.id}${act.path}`,
        act.temporary
          ? { temporary_password: temporary.current?.value ?? "" }
          : act.body,
      ),
    onMutate: () => setSaved(false),
    onSuccess: (_, act) => {
      if (temporary.current) temporary.current.value = "";
      setSaved(true);
      void client.invalidateQueries({ queryKey: ["users"] });
      if (act.leaves) onClose();
    },
  });
  const run = (act: Act) => mutation.mutate(act);
  const permissionLock = !canEditPermissions
    ? "권한 편집은 user.permission 권한이 필요해요."
    : adminTarget
      ? "admin은 항상 모든 권한을 가져요. admin 사용자의 권한은 편집할 수 없어요."
      : self
        ? "본인의 권한은 편집할 수 없어요."
        : null;
  return (
    <dialog
      ref={dialog}
      className="detail-panel user-panel"
      aria-labelledby="user-title"
      onCancel={onClose}
    >
      <header>
        <div>
          <span className="eyebrow">USER ACTION</span>
          <h2 id="user-title">
            {user.status === "pending" ? "가입 승인" : "사용자 작업"}
          </h2>
        </div>
        <Button variant="ghost" onClick={onClose} aria-label="작업 닫기">
          <LineIcon name="x" />
        </Button>
      </header>
      <div className="detail-content">
        <div className="user-summary">
          <span className="avatar-light">{[...user.display_name][0]}</span>
          <span className="user-names">
            <strong>{user.display_name}</strong>
            <small>{user.username}</small>
          </span>
          <span className="user-badges">
            <span className={statusPill[user.status] ?? "pill"}>
              {statusName[user.status]}
            </span>
            {user.role && (
              <span
                className={user.role === "admin" ? "pill pill-accent" : "pill"}
              >
                {user.role}
              </span>
            )}
          </span>
        </div>
        {mutation.error && <Failure error={mutation.error} />}
        {saved && <Banner tone="success" title="저장했어요" />}
        {lastAdmin && (
          <Banner tone="info" title={failures.last_admin[0]}>
            {failures.last_admin[1]}
          </Banner>
        )}
        {blocked && (
          <p className="auth-hint">
            admin 사용자에게는 admin만 작업할 수 있어요.
          </p>
        )}
        {user.status === "pending" && canApprove && (
          <>
            <Section title="승인">
              <div className="field">
                <label htmlFor="approve-role">부여할 역할</label>
                <select id="approve-role" ref={role} defaultValue="analyst">
                  <option value="analyst">analyst</option>
                  {isAdmin && <option value="admin">admin</option>}
                </select>
                <small>
                  승인하면 analyst 기본 조회 권한 9개가 지급돼요. admin 역할은
                  admin만 부여할 수 있어요.
                </small>
              </div>
              <Button
                className="btn btn-primary btn-block"
                onClick={() =>
                  run({
                    method: "POST",
                    path: "/approve",
                    body: { role: role.current?.value ?? "analyst" },
                    leaves: true,
                  })
                }
              >
                승인하기
              </Button>
            </Section>
            <Section title="거절">
              <p className="auth-hint">
                거절하면 이 계정으로 로그인할 수 없어요.
              </p>
              <Button
                variant="outline"
                className="btn btn-danger btn-block"
                onClick={() =>
                  run({ method: "POST", path: "/reject", leaves: true })
                }
              >
                가입 거절
              </Button>
            </Section>
          </>
        )}
        {user.status === "active" && (
          <>
            {isAdmin && (
              <Section title="역할 변경">
                <div className="field">
                  <label htmlFor="change-role">역할</label>
                  <select
                    id="change-role"
                    ref={role}
                    defaultValue={user.role ?? "analyst"}
                    disabled={self || lastAdmin}
                  >
                    <option value="analyst">analyst</option>
                    <option value="admin">admin</option>
                  </select>
                  <small>역할 변경은 admin만 할 수 있어요.</small>
                </div>
                <Button
                  className="btn btn-primary btn-block"
                  disabled={self || lastAdmin}
                  onClick={() =>
                    run({
                      method: "PATCH",
                      path: "",
                      body: { role: role.current?.value },
                    })
                  }
                >
                  역할 저장
                </Button>
              </Section>
            )}
            {canApprove && !blocked && (
              <>
                <Section title="비밀번호 재설정">
                  <div className="field">
                    <label htmlFor="temporary-password">임시 비밀번호</label>
                    <input
                      id="temporary-password"
                      ref={temporary}
                      type="password"
                      autoComplete="new-password"
                    />
                    <small>
                      12~128자 · 재설정 후 다음 로그인 때 비밀번호 변경이
                      필수예요.
                    </small>
                  </div>
                  <Button
                    className="btn btn-primary btn-block"
                    onClick={() =>
                      run({
                        method: "POST",
                        path: "/reset-password",
                        temporary: true,
                      })
                    }
                  >
                    비밀번호 재설정
                  </Button>
                </Section>
                <Section title="계정 중지">
                  <p className="auth-hint">중지하면 즉시 로그인할 수 없어요.</p>
                  <Button
                    variant="outline"
                    className="btn btn-danger btn-block"
                    disabled={self || lastAdmin}
                    onClick={() =>
                      run({ method: "POST", path: "/disable", leaves: true })
                    }
                  >
                    계정 중지
                  </Button>
                </Section>
              </>
            )}
            {user.role && (
              <PermissionEditor
                key={user.id + user.permissions.join()}
                user={user}
                mine={me.permissions}
                locked={permissionLock}
                run={run}
              />
            )}
          </>
        )}
      </div>
    </dialog>
  );
}

export function UsersPage() {
  const [search, setSearch] = useSearchParams();
  const asked = search.get("status");
  const status = statuses.some(([s]) => s === asked) ? asked! : "pending";
  const params = new URLSearchParams({ status, limit: String(PAGE_SIZE) });
  if (search.get("cursor")) params.set("cursor", search.get("cursor")!);
  const path = `users?${params}`;
  const query = useQuery({
    queryKey: ["users", path],
    queryFn: ({ signal }) => get<UserList>(path, signal),
  });
  const { current, page } = usePager(query.data?.next_cursor);
  const selected = search.get("selected");
  const user = query.data?.items.find((u) => u.id === selected);
  function change(next: string) {
    setSearch({ status: next });
  }
  function close() {
    const next = new URLSearchParams(search);
    next.delete("selected");
    setSearch(next);
  }
  if (query.error)
    return (
      <ErrorState
        needs="user.read"
        error={query.error}
        retry={() => void query.refetch()}
      />
    );
  return (
    <section className="card user-list">
      <h3>사용자 목록</h3>
      <div className="status-tabs" role="group" aria-label="상태">
        <span>상태</span>
        {statuses.map(([value, label]) => (
          <button
            key={value}
            type="button"
            aria-pressed={status === value}
            onClick={() => change(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {query.isPending ? (
        <p role="status" className="empty">
          불러오는 중…
        </p>
      ) : query.data.items.length ? (
        <div className="user-table">
          <table>
            <colgroup>
              <col style={{ width: 174 }} />
              <col style={{ width: 102 }} />
              <col style={{ width: 76 }} />
              <col style={{ width: 86 }} />
              <col style={{ width: 86 }} />
              <col style={{ width: 86 }} />
              <col style={{ width: 30 }} />
            </colgroup>
            <thead>
              <tr>
                <th>아이디</th>
                <th>표시 이름</th>
                <th>역할</th>
                <th>상태</th>
                <th>가입일</th>
                <th>승인일</th>
                <th aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((u) => (
                <tr
                  key={u.id}
                  onClick={() => {
                    const next = new URLSearchParams(search);
                    next.set("selected", u.id);
                    setSearch(next);
                  }}
                >
                  <td>
                    <button className="user-link">{u.username}</button>
                  </td>
                  <td className="user-name">{u.display_name}</td>
                  <td>
                    {u.role ? (
                      <span
                        className={
                          u.role === "admin" ? "pill pill-accent" : "pill"
                        }
                      >
                        {u.role}
                      </span>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>
                    <span className={statusPill[u.status] ?? "pill"}>
                      {statusName[u.status]}
                    </span>
                  </td>
                  <td className="date">{date(u.created_at)}</td>
                  <td className="date">{date(u.approved_at)}</td>
                  <td className="row-open">
                    <LineIcon name="chevron-right" size={14} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="users-empty">
          <span className="empty-circle">
            <LineIcon name="users" size={22} />
          </span>
          <h3>{emptyTitle[status]}</h3>
          <p>다른 상태 탭에서 사용자를 확인해 보세요.</p>
        </div>
      )}
      {(query.data?.items.length || search.has("cursor")) && (
        <footer className="pagination">
          <div className="pagination-controls">
            <button
              aria-label="이전 페이지"
              disabled={!search.has("cursor") || query.isFetching}
              onClick={() => page("previous")}
            >
              <Icon name="left" />
            </button>
            <span aria-live="polite">{current}/-</span>
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
      )}
      {user && (
        <UserPanel
          key={user.id}
          user={user}
          activeAdmins={
            query.data!.items.filter(
              (u) => u.role === "admin" && u.status === "active",
            ).length
          }
          onClose={close}
        />
      )}
    </section>
  );
}
