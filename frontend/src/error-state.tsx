import { Link } from "react-router";
import { ApiError } from "./api/client";
import { LineIcon, type LineIconName } from "./components/line-icon";
import { Button } from "./components/ui/button";

type Known = {
  title: string;
  body: string;
  chip: string;
  icon: LineIconName;
  tone: "warn" | "danger";
};
// Texts, icons and tones are from the design (25 permission_denied, 26 db_unavailable, 27 origin_not_allowed).
const known = (needs?: string): Record<string, Known> => ({
  permission_denied: {
    title: "이 화면을 볼 권한이 없어요",
    body: `계정에 필요한 권한${needs ? `(${needs})` : ""}이 없어요. 권한이 필요하면 관리자에게 요청해 주세요.`,
    chip: "403 · permission_denied",
    icon: "lock",
    tone: "warn",
  },
  db_unavailable: {
    title: "서버에 일시적으로 연결할 수 없어요",
    body: "데이터베이스에 연결하지 못했어요. 입력한 내용은 그대로 유지돼요. 잠시 후 다시 시도해 주세요.",
    chip: "503 · db_unavailable",
    icon: "server-off",
    tone: "danger",
  },
  origin_not_allowed: {
    title: "허용되지 않은 접속 주소예요",
    body: "현재 접속한 주소는 변경 요청이 허용된 목록에 없어요. 계정 권한과는 관계없어요. 관리자에게 접속 주소 등록을 요청해 주세요.",
    chip: "403 · origin_not_allowed",
    icon: "circle-alert",
    tone: "warn",
  },
});
// `inline` is for a list or panel that failed inside a page; the full card is for a whole screen.
export function ErrorState({
  error,
  retry,
  inline = false,
  needs,
}: {
  error: Error;
  retry: () => void;
  inline?: boolean;
  needs?: string;
}) {
  const code = error instanceof ApiError ? error.code : "";
  const info = known(needs)[code];
  const denied = code === "permission_denied";
  const home = (
    <Button variant="outline" asChild className="btn btn-secondary">
      <Link to="/">대시보드로 이동</Link>
    </Button>
  );
  const again = (primary: boolean) => (
    <Button
      variant="outline"
      className={primary ? "btn btn-primary" : "btn btn-secondary"}
      onClick={retry}
    >
      다시 시도
    </Button>
  );
  if (!info || inline)
    return (
      <div role="alert" className="empty">
        {info ? (
          <>
            <h3>{info.title}</h3>
            <p>{info.body}</p>
            <small>{info.chip}</small>
          </>
        ) : (
          <p>{error.message}</p>
        )}
        {denied ? home : again(false)}
      </div>
    );
  return (
    <div role="alert" className="error-state">
      <span className={`icon-circle icon-${info.tone}`}>
        <LineIcon name={info.icon} size={26} />
      </span>
      <h2>{info.title}</h2>
      <p>{info.body}</p>
      <code className="code-chip">{info.chip}</code>
      <div className="error-actions">
        {denied && home}
        {code === "db_unavailable" && (
          <>
            {again(true)}
            {home}
          </>
        )}
        {code === "origin_not_allowed" && again(false)}
      </div>
    </div>
  );
}
