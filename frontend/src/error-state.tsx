import { Link } from "react-router";
import { ApiError } from "./api/client";
import { Button } from "./components/ui/button";

export function ErrorState({
  error,
  retry,
}: {
  error: Error;
  retry: () => void;
}) {
  const code = error instanceof ApiError ? error.code : "";
  const known: Record<string, [string, string, string]> = {
    permission_denied: [
      "이 화면을 볼 권한이 없어요",
      "계정에 필요한 권한이 없어요. 권한이 필요하면 관리자에게 요청해 주세요.",
      "403 · permission_denied",
    ],
    db_unavailable: [
      "서버에 일시적으로 연결할 수 없어요",
      "데이터베이스에 연결하지 못했어요. 입력한 내용은 그대로 유지돼요. 잠시 후 다시 시도해 주세요.",
      "503 · db_unavailable",
    ],
    origin_not_allowed: [
      "허용되지 않은 접속 주소예요",
      "현재 접속한 주소는 변경 요청이 허용된 목록에 없어요. 계정 권한과는 관계없어요. 관리자에게 접속 주소 등록을 요청해 주세요.",
      "403 · origin_not_allowed",
    ],
  };
  const info = known[code];
  return (
    <div role="alert" className="empty">
      {info ? (
        <>
          <h3>{info[0]}</h3>
          <p>{info[1]}</p>
          <small>{info[2]}</small>
        </>
      ) : (
        <p>{error.message}</p>
      )}
      {code === "permission_denied" ? (
        <Button variant="outline" asChild>
          <Link to="/">대시보드로 이동</Link>
        </Button>
      ) : (
        <Button variant="outline" onClick={retry}>
          다시 시도
        </Button>
      )}
    </div>
  );
}
