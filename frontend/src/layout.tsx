import type { ReactNode } from "react";
import { Link, NavLink, useLocation, useSearchParams } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Icon, type IconName } from "./components/icons";
import { LineIcon, type LineIconName } from "./components/line-icon";
import logo from "./assets/o-ticket-mark.png";
import { ApiError, get } from "./api/client";
import type { Resource } from "./api/client";
import type { Dashboard } from "./api/generated/Dashboard";
import type { Me } from "./api/generated/Me";
import type { TicketingPolicyResponse } from "./api/generated/TicketingPolicyResponse";
import { SettingsPage } from "./auth/pages";
import { useLogout } from "./auth/session";
import { resourcePermission, titles } from "./constants";
import { DashboardView, Overview } from "./dashboard";
import { ErrorState } from "./error-state";
import { ListView } from "./list-view";
import { PolicyPage } from "./policy-page";
import { UsersPage } from "./users/users-page";

const menu: [string, string, IconName, string[]][] = [
  ["/", "DashBoard", "dashboard", ["dashboard.read"]],
  ["/alerts", "Alert/Event", "alerts", ["alert.read", "event.read"]],
  ["/tickets", "Ticket", "tickets", ["ticket.read"]],
  ["/incidents", "Incident", "incidents", ["incident.read"]],
  ["/cases", "Case", "cases", ["case.read"]],
  ["/hunts", "Hunting", "hunts", ["hunt.read"]],
];
const adminMenu: [string, string, string, LineIconName][] = [
  ["/policy", "Ticket 정책", "policy.read", "sliders"],
  ["/users", "사용자 관리", "user.read", "users"],
];
// A menu entry the account has no permission for: dimmed and not clickable (not a link).
function NoAccess({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="nav-disabled" aria-disabled="true" title="권한이 없어요">
      <span className="menu-icon">{children}</span>
      {label}
    </span>
  );
}
export function Workspace({ me }: { me: Me }) {
  const location = useLocation();
  const logout = useLogout();
  const [search] = useSearchParams();
  const slug = location.pathname.slice(1);
  const resource = (
    Object.hasOwn(titles, slug) ? slug : null
  ) as Resource | null;
  const isHome = location.pathname === "/";
  const can = (names: string[]) =>
    names.some((n) => me.permissions.includes(n));
  const page =
    location.pathname === "/settings"
      ? "settings"
      : location.pathname === "/users"
        ? "users"
        : location.pathname === "/policy"
          ? "policy"
          : null;
  const waiting = resource === "cases" && search.get("tab") === "waiting";
  // Permission needed to open this screen. Without it no request is sent; the screen says so.
  const needed: string | null = isHome
    ? "dashboard.read"
    : page === "users"
      ? "user.read"
      : page === "policy"
        ? "policy.read"
        : resource
          ? waiting
            ? "incident.read"
            : resourcePermission[resource]
          : null;
  const denied = needed !== null && !can([needed]);
  const mayDashboard = can(["dashboard.read"]);
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: ({ signal }) => get<Dashboard>("dashboard", signal),
    enabled: !denied && mayDashboard && (isHome || resource !== null),
  });
  // The flow has one more stage in scenario mode. Without policy.read the mode is unknown, so default is shown.
  const policyNeeded = isHome && !denied && can(["policy.read"]);
  const policy = useQuery({
    queryKey: ["policy"],
    queryFn: ({ signal }) =>
      get<TicketingPolicyResponse>("ticketing-policy", signal),
    enabled: policyNeeded,
  });
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <Link className="brand" to="/">
          <img className="brand-mark" src={logo} alt="" />
          <span>
            Ø-Ticket
            <small>
              AI Agent-based
              <br />
              SOC Automation
            </small>
          </span>
        </Link>
        <nav>
          {menu.map(([path, label, icon, needs]) =>
            can(needs) ? (
              <NavLink
                key={path}
                // Alert/Event opens Event when only event.read is held.
                to={
                  path === "/alerts" && !can(["alert.read"]) ? "/events" : path
                }
                end={path === "/"}
                className={({ isActive }) =>
                  isActive || (path === "/alerts" && resource === "events")
                    ? "active"
                    : ""
                }
              >
                <span className="menu-icon">
                  <Icon name={icon} />
                </span>
                {label}
              </NavLink>
            ) : (
              <NoAccess key={path} label={label}>
                <Icon name={icon} />
              </NoAccess>
            ),
          )}
          <span className="menu-group">관리</span>
          {adminMenu.map(([path, label, needs, icon]) =>
            can([needs]) ? (
              <NavLink key={path} to={path}>
                <span className="menu-icon">
                  <LineIcon name={icon} size={20} />
                </span>
                {label}
              </NavLink>
            ) : (
              <NoAccess key={path} label={label}>
                <LineIcon name={icon} size={20} />
              </NoAccess>
            ),
          )}
        </nav>
        <div className="user-area">
          <div className="user-row">
            <span className="avatar">{[...me.display_name][0]}</span>
            <span className="user-info">
              <strong>{me.display_name}</strong>
              <span className={`role-badge role-${me.role}`}>{me.role}</span>
            </span>
            <Link className="settings" to="/settings">
              <Icon name="settings" />
              설정
            </Link>
          </div>
          <button
            type="button"
            className="logout-button"
            onClick={() => logout.mutate()}
          >
            <LineIcon name="log-out" size={14} />
            로그아웃
          </button>
        </div>
      </aside>
      <div className="workspace">
        <main>
          <header className="page-heading">
            <div>
              <h1>
                {isHome
                  ? "DashBoard"
                  : page
                    ? page === "users"
                      ? "사용자 관리"
                      : page === "policy"
                        ? "Ticket 정책"
                        : "설정"
                    : resource
                      ? titles[resource]
                      : "페이지를 찾을 수 없습니다"}
              </h1>
            </div>
          </header>
          {denied ? (
            <ErrorState
              needs={needed}
              noHome={isHome}
              error={new ApiError(403, "permission_denied")}
              retry={() => undefined}
            />
          ) : page === "settings" ? (
            <SettingsPage me={me} />
          ) : page === "users" ? (
            <UsersPage />
          ) : page === "policy" ? (
            <PolicyPage />
          ) : !isHome &&
            !resource ? null : !mayDashboard ? null : dashboard.isPending ||
            (policyNeeded && policy.isPending) ? (
            <p role="status">집계 불러오는 중…</p>
          ) : dashboard.error ? (
            <ErrorState
              needs="dashboard.read"
              error={dashboard.error}
              retry={() => void dashboard.refetch()}
            />
          ) : isHome ? (
            <DashboardView
              data={dashboard.data}
              mode={policy.data?.mode ?? "default"}
            />
          ) : (
            resource && <Overview resource={resource} data={dashboard.data} />
          )}
          {!denied && (resource === "alerts" || resource === "events") && (
            <div className="tabs">
              {can(["alert.read"]) && <NavLink to="/alerts">Alert</NavLink>}
              {can(["event.read"]) && <NavLink to="/events">Event</NavLink>}
            </div>
          )}
          {!denied && resource === "cases" && (
            <>
              <div className="tabs">
                {can(["incident.read"]) && (
                  <Link
                    className={waiting ? "active" : ""}
                    to="/cases?tab=waiting"
                  >
                    승인 대기 Incident
                  </Link>
                )}
                <Link className={!waiting ? "active" : ""} to="/cases">
                  승인된 Case
                </Link>
              </div>
              <p className="notice">
                {waiting
                  ? "아직 Case가 아닌 승인 대기 Incident(awaiting_review)입니다. 사람이 승인하면 Case가 됩니다."
                  : "사람이 승인한 시점의 내용을 보관한 Case입니다."}
              </p>
            </>
          )}
          {!denied && resource && (
            <ListView
              key={`${resource}/${waiting}`}
              resource={waiting ? "incidents" : resource}
              waiting={waiting}
              summary={dashboard.data}
            />
          )}
        </main>
        <footer className="workspace-footer">
          0-Ticket SOC{" "}
          <a href="https://github.com/0-Ticket">https://github.com/0-Ticket</a>
        </footer>
      </div>
    </div>
  );
}
