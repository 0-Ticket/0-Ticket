import { expect, test } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { auth, server, requests, show, dashboard } from "./test-utils";

const unauthenticated = () =>
  http.get("*/api/auth/me", () =>
    HttpResponse.json({ error: "unauthenticated" }, { status: 401 }),
  );
async function type(label: string, value: string) {
  fireEvent.change(await screen.findByLabelText(label), { target: { value } });
}
async function login(username = "analyst.test") {
  await type("아이디", username);
  await type("비밀번호", "a-long-test-password");
  fireEvent.click(screen.getByRole("button", { name: "로그인" }));
}

test("logged-out visit goes to login and returns to the original path and query", async () => {
  dashboard();
  server.use(
    unauthenticated(),
    http.post("*/api/auth/login", () => HttpResponse.json(auth.analyst)),
    http.get("*/api/tickets", () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  );
  show("/tickets?status=new");
  expect(
    await screen.findByRole("heading", { name: "로그인" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/login$/);
  await login();
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(
      "/tickets?status=new",
    ),
  );
  expect(
    await screen.findByRole("group", { name: "상태 필터" }),
  ).toBeInTheDocument();
});

test.each([
  ["invalid_credentials", 401, "아이디 또는 비밀번호가 올바르지 않아요"],
  ["account_pending", 403, "승인 대기 중인 계정이에요"],
  ["account_rejected", 403, "가입이 거절된 계정이에요"],
  ["account_disabled", 403, "사용이 중지된 계정이에요"],
])("login shows a distinct message for %s", async (error, status, text) => {
  server.use(
    unauthenticated(),
    http.post("*/api/auth/login", () =>
      HttpResponse.json({ error }, { status }),
    ),
  );
  show("/login");
  await login();
  expect(await screen.findByText(text)).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/login$/);
});

test("login shows the field error for 422", async () => {
  server.use(
    unauthenticated(),
    http.post("*/api/auth/login", () =>
      HttpResponse.json(
        { error: "invalid_body", fields: ["password"] },
        { status: 422 },
      ),
    ),
  );
  show("/login");
  await login();
  expect(
    await screen.findByText("올바르게 입력해 주세요."),
  ).toBeInTheDocument();
});

test("signup validates locally, then shows pending notice and taken username", async () => {
  let body: unknown = null;
  server.use(
    unauthenticated(),
    http.post("*/api/auth/signup", async ({ request }) => {
      body = await request.json();
      return (body as { username: string }).username === "taken.name"
        ? HttpResponse.json({ error: "username_taken" }, { status: 409 })
        : HttpResponse.json(
            { username: "new.user", status: "pending" },
            { status: 201 },
          );
    }),
  );
  show("/signup");
  await type("아이디", "Min Su");
  await type("표시 이름", "민수");
  await type("비밀번호", "short");
  await type("비밀번호 확인", "different");
  fireEvent.click(screen.getByRole("button", { name: "회원가입" }));
  expect(
    await screen.findByText(/a-z 0-9 \. _ - 만 사용해 3~64자/),
  ).toBeInTheDocument();
  expect(screen.getByText("12~128자로 입력해 주세요.")).toBeInTheDocument();
  expect(screen.getByText("비밀번호가 일치하지 않아요.")).toBeInTheDocument();
  expect(body).toBeNull();
  await type("아이디", "Taken.Name");
  await type("비밀번호", "a-long-test-password");
  await type("비밀번호 확인", "a-long-test-password");
  fireEvent.click(screen.getByRole("button", { name: "회원가입" }));
  expect(await screen.findByText(/이미 사용 중인 아이디/)).toBeInTheDocument();
  expect(body).toMatchObject({ username: "taken.name", display_name: "민수" });
  await type("아이디", "new.user");
  fireEvent.click(screen.getByRole("button", { name: "회원가입" }));
  expect(await screen.findByText("가입 신청이 완료됐어요")).toBeInTheDocument();
  // The design shows the pending state as a badge, not a sentence.
  expect(screen.getByText("승인 대기")).toBeInTheDocument();
  expect(screen.getByText("민수")).toBeInTheDocument();
});

test("must_change_password locks every other route and hides the menu", async () => {
  dashboard();
  server.use(
    http.get("*/api/auth/me", () =>
      HttpResponse.json({ ...auth.analyst, must_change_password: true }),
    ),
  );
  show("/tickets");
  expect(
    await screen.findByRole("heading", { name: "비밀번호를 변경해 주세요" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/password$/);
  expect(
    screen.queryByRole("link", { name: /Ticket/ }),
  ).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "로그아웃" })).toBeInTheDocument();
});

test("password change with a wrong current password is not a session expiry", async () => {
  dashboard();
  server.use(
    http.post("*/api/auth/password", () =>
      HttpResponse.json({ error: "invalid_credentials" }, { status: 401 }),
    ),
  );
  show("/settings");
  await screen.findByRole("heading", { name: "설정" });
  await type("현재 비밀번호", "wrong-current-password");
  await type("새 비밀번호", "a-long-test-password");
  await type("새 비밀번호 확인", "a-long-test-password");
  fireEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));
  expect(
    await screen.findByText(
      "현재 비밀번호가 올바르지 않아요. 다시 확인해 주세요.",
    ),
  ).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/settings$/);
});

test("password change success shows notice and forced mode leaves /password", async () => {
  dashboard();
  let me = { ...auth.analyst, must_change_password: true };
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json(me)),
    http.post("*/api/auth/password", () => {
      me = { ...me, must_change_password: false };
      return HttpResponse.json(me);
    }),
  );
  show("/password");
  await screen.findByRole("heading", { name: "비밀번호를 변경해 주세요" });
  await type("현재 비밀번호", "temporary-password-1");
  await type("새 비밀번호", "a-long-test-password");
  await type("새 비밀번호 확인", "a-long-test-password");
  fireEvent.click(screen.getByRole("button", { name: "비밀번호 변경" }));
  await waitFor(() =>
    expect(screen.getByTestId("where")).toHaveTextContent(/^\/$/),
  );
  expect(await screen.findByRole("list", { name: "처리 흐름" })).toBeVisible();
});

test("a 401 unauthenticated response on data sends the user to login", async () => {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "unauthenticated" }, { status: 401 }),
    ),
  );
  show("/");
  expect(await screen.findByText("세션이 만료되었어요")).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/login$/);
});

test("a 403 permission_denied response shows the no-permission screen", async () => {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "permission_denied" }, { status: 403 }),
    ),
  );
  show("/tickets");
  expect(
    await screen.findByText("이 화면을 볼 권한이 없어요"),
  ).toBeInTheDocument();
  expect(screen.getByText(/403 · permission_denied/)).toBeInTheDocument();
});

test("403 origin_not_allowed shows its own error state", async () => {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "origin_not_allowed" }, { status: 403 }),
    ),
  );
  show("/");
  expect(
    await screen.findByText("허용되지 않은 접속 주소예요"),
  ).toBeInTheDocument();
});

test("db_unavailable shows the server error state", async () => {
  server.use(
    http.get("*/api/dashboard", () =>
      HttpResponse.json({ error: "db_unavailable" }, { status: 503 }),
    ),
  );
  show("/");
  expect(
    await screen.findByText("서버에 일시적으로 연결할 수 없어요"),
  ).toBeInTheDocument();
});

test("menu items follow permissions", async () => {
  dashboard();
  server.use(
    http.get("*/api/auth/me", () =>
      HttpResponse.json({
        ...auth.analyst,
        permissions: ["dashboard.read", "ticket.read", "policy.read"],
      }),
    ),
  );
  show("/");
  const nav = within(await screen.findByRole("navigation"));
  expect(nav.getByRole("link", { name: "DashBoard" })).toBeInTheDocument();
  expect(nav.getByRole("link", { name: "Ticket" })).toBeInTheDocument();
  expect(nav.getByRole("link", { name: "Ticket 정책" })).toBeInTheDocument();
  for (const hidden of [
    "Alert/Event",
    "Incident",
    "Case",
    "Hunting",
    "사용자 관리",
  ])
    expect(nav.queryByRole("link", { name: hidden })).not.toBeInTheDocument();
});

test("admin sees every menu and the user area", async () => {
  dashboard();
  show("/");
  const nav = within(await screen.findByRole("navigation"));
  for (const name of [
    "Alert/Event",
    "Incident",
    "Case",
    "Hunting",
    "Ticket 정책",
    "사용자 관리",
  ])
    expect(nav.getByRole("link", { name })).toBeInTheDocument();
  expect(screen.getByText(auth.admin.display_name)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "설정" })).toBeInTheDocument();
});

test("logout calls the API and returns to login without further requests", async () => {
  dashboard();
  let state = "in";
  server.use(
    http.get("*/api/auth/me", () =>
      state === "in"
        ? HttpResponse.json(auth.admin)
        : HttpResponse.json({ error: "unauthenticated" }, { status: 401 }),
    ),
    http.post("*/api/auth/logout", () => {
      state = "out";
      return new HttpResponse(null, { status: 204 });
    }),
  );
  show("/");
  await screen.findByRole("list", { name: "처리 흐름" });
  fireEvent.click(screen.getByRole("button", { name: "로그아웃" }));
  expect(
    await screen.findByRole("heading", { name: "로그인" }),
  ).toBeInTheDocument();
  expect(requests.some((r) => r.pathname === "/api/auth/logout")).toBe(true);
});

test("the password never appears in a URL", async () => {
  server.use(
    unauthenticated(),
    http.post("*/api/auth/login", () =>
      HttpResponse.json({ error: "invalid_credentials" }, { status: 401 }),
    ),
  );
  show("/login");
  await login();
  await screen.findByText("아이디 또는 비밀번호가 올바르지 않아요");
  expect(requests.map((r) => r.href).join(" ")).not.toContain("a-long-test");
});

test("403 password_change_required sends a stale session to the change screen", async () => {
  let me = auth.analyst as typeof auth.analyst & {
    must_change_password: boolean;
  };
  server.use(
    http.get("*/api/auth/me", () => HttpResponse.json(me)),
    http.get("*/api/dashboard", () => {
      me = { ...me, must_change_password: true };
      return HttpResponse.json(
        { error: "password_change_required" },
        { status: 403 },
      );
    }),
  );
  show("/");
  expect(
    await screen.findByRole("heading", { name: "비밀번호를 변경해 주세요" }),
  ).toBeInTheDocument();
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/password$/);
});

test("login, sign-up and forced change share the card layout and design placeholders", async () => {
  server.use(unauthenticated());
  const first = show("/login");
  expect(await screen.findByPlaceholderText("아이디 입력")).toBeInTheDocument();
  expect(screen.getByPlaceholderText("비밀번호 입력")).toBeInTheDocument();
  expect(document.querySelector(".auth-card .auth-fields")).not.toBeNull();
  first.unmount();
  show("/signup");
  expect(
    await screen.findByPlaceholderText("영문 소문자·숫자 3~64자"),
  ).toBeInTheDocument();
  expect(
    document.querySelector(".auth-brand + .auth-form .auth-card"),
  ).not.toBeNull();
});
