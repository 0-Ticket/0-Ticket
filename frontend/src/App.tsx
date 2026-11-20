import { Navigate, useLocation } from "react-router";
import { ErrorState } from "./error-state";
import { ForcedPasswordPage, LoginPage, SignupPage } from "./auth/pages";
import { useLoginTarget, useMe } from "./auth/session";
import { Workspace } from "./layout";

export default function App() {
  const location = useLocation();
  const me = useMe();
  const target = useLoginTarget();
  const path = location.pathname;
  if (me.isPending) return <p role="status">불러오는 중…</p>;
  if (me.error)
    return <ErrorState error={me.error} retry={() => void me.refetch()} />;
  const user = me.data;
  if (!user) {
    if (path === "/login") return <LoginPage />;
    if (path === "/signup") return <SignupPage />;
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  if (path === "/login" || path === "/signup")
    return (
      <Navigate to={user.must_change_password ? "/password" : target} replace />
    );
  if (user.must_change_password)
    return path === "/password" ? (
      <ForcedPasswordPage />
    ) : (
      <Navigate to="/password" replace />
    );
  if (path === "/password") return <Navigate to="/" replace />;
  return <Workspace me={user} />;
}
