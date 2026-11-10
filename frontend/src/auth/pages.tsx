import { useId, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link } from "react-router";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ApiError, send } from "../api/client";
import type { Me } from "../api/generated/Me";
import type { SignupResult } from "../api/generated/SignupResult";
import { Button } from "../components/ui/button";
import logo from "../assets/o-ticket-mark.png";
import { useLogout, useSessionReset } from "./session";

const messages = {
  username: "a-z 0-9 . _ - 만 사용해 3~64자로 입력해 주세요.",
  display_name: "표시 이름을 입력해 주세요.",
  password: "12~128자로 입력해 주세요.",
  new_password: "12~128자로 입력해 주세요.",
  current_password: "현재 비밀번호를 입력해 주세요.",
  confirm: "비밀번호가 일치하지 않아요.",
};
const formError = "올바르게 입력해 주세요.";
type Errors = Record<string, string>;

function read(form: HTMLFormElement) {
  const data = new FormData(form);
  return (name: string) => String(data.get(name) ?? "");
}
function serverFields(error: unknown): Errors {
  if (!(error instanceof ApiError) || error.status !== 422) return {};
  return Object.fromEntries(
    error.fields.map((f) => [
      f,
      messages[f as keyof typeof messages] ?? formError,
    ]),
  );
}
function Banner({
  tone,
  title,
  children,
}: {
  tone: "error" | "success" | "info";
  title: string;
  children?: ReactNode;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={`banner banner-${tone}`}
    >
      <strong>{title}</strong>
      {children && <p>{children}</p>}
    </div>
  );
}
function Field({
  label,
  name,
  type = "text",
  error,
  hint,
  disabled,
  autoComplete,
}: {
  label: string;
  name: string;
  type?: string;
  error?: string;
  hint?: string;
  disabled?: boolean;
  autoComplete?: string;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        type={type}
        // readOnly, not disabled: FormData skips disabled inputs when the mutation reads the form.
        readOnly={disabled}
        autoComplete={autoComplete}
        aria-invalid={!!error}
      />
      {error ? (
        <small className="field-error">{error}</small>
      ) : (
        hint && <small>{hint}</small>
      )}
    </div>
  );
}
function AuthLayout({ children }: { children: ReactNode }) {
  return (
    <div className="auth-page">
      <section className="auth-brand">
        <span className="brand">
          <img className="brand-mark" src={logo} alt="" />
          <span>
            Ø-Ticket
            <small>
              AI Agent-based
              <br />
              SOC Automation
            </small>
          </span>
        </span>
        <h2>
          침해 대응을
          <br />
          AI Agent가 자동으로
          <br />
          분류하고 제안합니다
        </h2>
        <p>
          Alert 수집부터 Incident 분석, Case 승인까지 한 화면에서 관리하세요.
        </p>
        <small>© 2026 Ø-Ticket</small>
      </section>
      <section className="auth-form">{children}</section>
    </div>
  );
}

const loginErrors: Record<string, [string, string]> = {
  invalid_credentials: [
    "아이디 또는 비밀번호가 올바르지 않아요",
    "입력한 내용을 확인한 뒤 다시 시도해 주세요.",
  ],
  account_pending: [
    "승인 대기 중인 계정이에요",
    "관리자가 가입을 승인하면 로그인할 수 있어요.",
  ],
  account_rejected: [
    "가입이 거절된 계정이에요",
    "자세한 내용은 관리자에게 문의해 주세요.",
  ],
  account_disabled: [
    "사용이 중지된 계정이에요",
    "계정 사용 재개는 관리자에게 요청해 주세요.",
  ],
};
export function LoginPage() {
  const client = useQueryClient();
  const reset = useSessionReset();
  const form = useRef<HTMLFormElement>(null);
  const expired = client.getQueryData(["expired"]) === true;
  const login = useMutation<Me, ApiError>({
    mutationFn: () => {
      const value = read(form.current!);
      return send<Me>("POST", "auth/login", {
        username: value("username").trim().toLowerCase(),
        password: value("password"),
      });
    },
    onSuccess: reset,
  });
  const failure = login.error
    ? (loginErrors[login.error.code] ??
      (login.error.status === 422
        ? ["입력을 확인해 주세요", formError]
        : [
            "로그인하지 못했어요",
            "서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.",
          ]))
    : null;
  return (
    <AuthLayout>
      <form
        ref={form}
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
      >
        <h1>로그인</h1>
        {failure ? (
          <Banner tone="error" title={failure[0]}>
            {failure[1]}
          </Banner>
        ) : (
          expired && (
            <Banner tone="info" title="세션이 만료되었어요">
              다시 로그인하면 보던 화면으로 돌아가요.
            </Banner>
          )
        )}
        <Field
          label="아이디"
          name="username"
          disabled={login.isPending}
          autoComplete="username"
        />
        <Field
          label="비밀번호"
          name="password"
          type="password"
          disabled={login.isPending}
          autoComplete="current-password"
        />
        <Button type="submit" disabled={login.isPending}>
          {login.isPending ? "로그인 중…" : "로그인"}
        </Button>
        <p className="auth-hint">
          비밀번호를 잊으셨다면 관리자에게 재설정을 요청하세요.
        </p>
        <p className="auth-switch">
          계정이 없으신가요? <Link to="/signup">회원가입</Link>
        </p>
      </form>
    </AuthLayout>
  );
}

export function SignupPage() {
  const form = useRef<HTMLFormElement>(null);
  const [errors, setErrors] = useState<Errors>({});
  const signup = useMutation<SignupResult, ApiError>({
    mutationFn: () => {
      const value = read(form.current!);
      return send<SignupResult>("POST", "auth/signup", {
        username: value("username").trim().toLowerCase(),
        display_name: value("display_name").trim(),
        password: value("password"),
      });
    },
    onError: (error) => setErrors(serverFields(error)),
  });
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const value = read(e.currentTarget);
    const next: Errors = {};
    if (!/^[a-z0-9._-]{3,64}$/.test(value("username").trim().toLowerCase()))
      next.username = messages.username;
    if (!value("display_name").trim())
      next.display_name = messages.display_name;
    if (value("password").length < 12 || value("password").length > 128)
      next.password = messages.password;
    if (value("password") !== value("confirm")) next.confirm = messages.confirm;
    setErrors(next);
    if (!Object.keys(next).length) signup.mutate();
  }
  if (signup.isSuccess)
    return (
      <AuthLayout>
        <div>
          <h1>가입 신청이 완료됐어요</h1>
          <Banner tone="success" title="관리자 승인 후 로그인할 수 있어요" />
          <dl className="summary">
            <dt>아이디</dt>
            <dd>{signup.data.username}</dd>
            <dt>상태</dt>
            <dd>승인 대기</dd>
          </dl>
          <Button asChild>
            <Link to="/login">로그인 화면으로</Link>
          </Button>
        </div>
      </AuthLayout>
    );
  const taken = signup.error?.code === "username_taken";
  return (
    <AuthLayout>
      <form ref={form} onSubmit={submit} noValidate>
        <h1>회원가입</h1>
        {signup.error &&
          !taken &&
          !Object.keys(serverFields(signup.error)).length && (
            <Banner tone="error" title="가입하지 못했어요">
              서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.
            </Banner>
          )}
        <Field
          label="아이디"
          name="username"
          disabled={signup.isPending}
          autoComplete="username"
          error={
            taken
              ? "이미 사용 중인 아이디예요. 다른 아이디를 입력해 주세요."
              : errors.username
          }
        />
        <Field
          label="표시 이름"
          name="display_name"
          disabled={signup.isPending}
          error={errors.display_name}
        />
        <Field
          label="비밀번호"
          name="password"
          type="password"
          disabled={signup.isPending}
          autoComplete="new-password"
          error={errors.password}
          hint="12~128자"
        />
        <Field
          label="비밀번호 확인"
          name="confirm"
          type="password"
          disabled={signup.isPending}
          autoComplete="new-password"
          error={errors.confirm}
        />
        <Button type="submit" disabled={signup.isPending}>
          회원가입
        </Button>
        <p className="auth-switch">
          이미 계정이 있으신가요? <Link to="/login">로그인</Link>
        </p>
      </form>
    </AuthLayout>
  );
}

export function PasswordForm({ forced = false }: { forced?: boolean }) {
  const reset = useSessionReset();
  const form = useRef<HTMLFormElement>(null);
  const [errors, setErrors] = useState<Errors>({});
  const [done, setDone] = useState(false);
  const change = useMutation<Me, ApiError>({
    mutationFn: () => {
      const value = read(form.current!);
      return send<Me>("POST", "auth/password", {
        current_password: value("current_password"),
        new_password: value("new_password"),
      });
    },
    onSuccess: (me) => {
      form.current?.reset();
      setErrors({});
      setDone(true);
      reset(me);
    },
    onError: (error) => {
      setDone(false);
      setErrors(
        error.code === "invalid_credentials"
          ? {
              current_password:
                "현재 비밀번호가 올바르지 않아요. 다시 확인해 주세요.",
            }
          : serverFields(error),
      );
    },
  });
  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const value = read(e.currentTarget);
    const next: Errors = {};
    if (!value("current_password"))
      next.current_password = messages.current_password;
    if (value("new_password").length < 12 || value("new_password").length > 128)
      next.new_password = messages.new_password;
    if (value("new_password") !== value("confirm"))
      next.confirm = messages.confirm;
    setErrors(next);
    if (!Object.keys(next).length) change.mutate();
  }
  const generic = change.error && !Object.keys(errors).length;
  return (
    <form ref={form} onSubmit={submit} noValidate>
      {done && !forced && (
        <Banner tone="success" title="비밀번호를 변경했어요">
          다음 로그인부터 새 비밀번호를 사용해 주세요.
        </Banner>
      )}
      {generic && (
        <Banner tone="error" title="비밀번호를 변경하지 못했어요">
          서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.
        </Banner>
      )}
      <Field
        label="현재 비밀번호"
        name="current_password"
        type="password"
        disabled={change.isPending}
        autoComplete="current-password"
        error={errors.current_password}
      />
      <Field
        label="새 비밀번호"
        name="new_password"
        type="password"
        disabled={change.isPending}
        autoComplete="new-password"
        error={errors.new_password}
        hint="12~128자 · 현재 비밀번호와 달라야 해요."
      />
      <Field
        label="새 비밀번호 확인"
        name="confirm"
        type="password"
        disabled={change.isPending}
        autoComplete="new-password"
        error={errors.confirm}
      />
      <Button type="submit" disabled={change.isPending}>
        비밀번호 변경
      </Button>
    </form>
  );
}

export function ForcedPasswordPage() {
  const logout = useLogout();
  return (
    <AuthLayout>
      <div>
        <h1>비밀번호를 변경해 주세요</h1>
        <p className="auth-hint">
          최초 로그인이거나 관리자가 재설정한 비밀번호예요. 변경을 마칠 때까지
          다른 메뉴는 사용할 수 없어요.
        </p>
        <PasswordForm forced />
        <Button variant="outline" onClick={() => logout.mutate()}>
          로그아웃
        </Button>
      </div>
    </AuthLayout>
  );
}

export function SettingsPage({ me }: { me: Me }) {
  return (
    <>
      <section className="card settings-card">
        <h3>내 계정</h3>
        <dl className="summary">
          <dt>아이디</dt>
          <dd>{me.username}</dd>
          <dt>표시 이름</dt>
          <dd>{me.display_name}</dd>
          <dt>역할</dt>
          <dd>{me.role}</dd>
          <dt>권한</dt>
          <dd>
            {me.role === "admin"
              ? "모든 권한 (admin)"
              : me.permissions.join(", ") || "없음"}
          </dd>
        </dl>
      </section>
      <section className="card settings-card">
        <h3>비밀번호 변경</h3>
        <p className="auth-hint">로그인한 계정의 비밀번호를 바꿔요.</p>
        <PasswordForm />
      </section>
    </>
  );
}
