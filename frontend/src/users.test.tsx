import { expect, test } from "vitest";
import { screen, fireEvent, waitFor, within } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { auth, server, requests, show } from "./test-utils";

const [pendingOne, pendingTwo, analyst, admin] = auth.users;
const list = (items: unknown[], next_cursor: string | null = null) =>
  http.get("*/api/users", () => HttpResponse.json({ items, next_cursor }));
const catalog = () =>
  http.get("*/api/permissions", () =>
    HttpResponse.json({ permissions: auth.permissions }),
  );
const meAs = (me: typeof auth.admin) =>
  http.get("*/api/auth/me", () => HttpResponse.json(me));
const usersAsked = () => requests.filter((r) => r.pathname === "/api/users");

test("pending tab is the default and user strings stay text", async () => {
  server.use(list([pendingOne, pendingTwo]));
  show("/users");
  expect(await screen.findByText(pendingOne.display_name)).toBeInTheDocument();
  expect(document.querySelector("b")).toBeNull();
  const asked = usersAsked()[0].searchParams;
  expect(asked.get("status")).toBe("pending");
  expect(asked.get("limit")).toBe("25");
  expect(
    screen.getByLabelText("상태", { selector: "[role=group]" }),
  ).toBeTruthy();
  expect(screen.getByText("1/-")).toBeInTheDocument();
});

test("status tabs reload the list and an empty tab says so", async () => {
  server.use(list([]));
  show("/users");
  await screen.findByText("승인 대기 사용자가 없어요");
  fireEvent.click(screen.getByRole("button", { name: "거절" }));
  expect(await screen.findByText("거절된 사용자가 없어요")).toBeInTheDocument();
  await waitFor(() =>
    expect(usersAsked().at(-1)?.searchParams.get("status")).toBe("rejected"),
  );
});

test("next page uses next_cursor and previous returns", async () => {
  server.use(list([pendingOne], "1762646400000000_abc"));
  show("/users");
  await screen.findByText(pendingOne.display_name);
  fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() =>
    expect(usersAsked().at(-1)?.searchParams.get("cursor")).toBe(
      "1762646400000000_abc",
    ),
  );
  expect(await screen.findByText("2/-")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
  expect(await screen.findByText("1/-")).toBeInTheDocument();
});

test("approving a user sends the chosen role and reloads the list", async () => {
  let body: unknown = null;
  server.use(
    list([pendingOne]),
    http.post(`*/api/users/${pendingOne.id}/approve`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({
        ...pendingOne,
        status: "active",
        role: "analyst",
      });
    }),
  );
  show("/users");
  fireEvent.click(
    await screen.findByRole("button", { name: pendingOne.username }),
  );
  expect(await screen.findByText("가입 승인")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "승인하기" }));
  await waitFor(() => expect(body).toEqual({ role: "analyst" }));
  await waitFor(() => expect(usersAsked().length).toBeGreaterThan(1));
});

test("the admin role can only be given by an admin", async () => {
  server.use(
    list([pendingOne]),
    meAs({
      ...auth.analyst,
      permissions: ["user.read", "user.approve", "dashboard.read"],
    }),
  );
  show("/users");
  fireEvent.click(
    await screen.findByRole("button", { name: pendingOne.username }),
  );
  const role = await screen.findByLabelText("부여할 역할");
  expect(within(role).queryByRole("option", { name: "admin" })).toBeNull();
});

test("without user.approve the panel has no actions", async () => {
  server.use(
    list([pendingOne]),
    meAs({ ...auth.analyst, permissions: ["user.read"] }),
  );
  show("/users");
  fireEvent.click(
    await screen.findByRole("button", { name: pendingOne.username }),
  );
  await screen.findByText("가입 승인");
  expect(screen.queryByRole("button", { name: "승인하기" })).toBeNull();
  expect(screen.queryByRole("button", { name: "가입 거절" })).toBeNull();
});

test.each([
  ["last_admin", 409, "마지막 활성 admin이에요"],
  ["invalid_state", 409, "지금은 할 수 없는 작업이에요"],
  ["invalid_target", 409, "이 사용자에게는 적용할 수 없어요"],
  ["forbidden", 403, "이 작업을 할 권한이 없어요"],
  ["not_found", 404, "사용자를 찾을 수 없어요"],
])("an action error %s shows its own message", async (error, status, text) => {
  server.use(
    list([pendingOne]),
    http.post(`*/api/users/${pendingOne.id}/reject`, () =>
      HttpResponse.json({ error }, { status }),
    ),
  );
  show("/users");
  fireEvent.click(
    await screen.findByRole("button", { name: pendingOne.username }),
  );
  fireEvent.click(await screen.findByRole("button", { name: "가입 거절" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(text);
});

test("temporary password reset reads the input once and clears it", async () => {
  let body: unknown = null;
  server.use(
    list([analyst]),
    catalog(),
    http.post(
      `*/api/users/${analyst.id}/reset-password`,
      async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(analyst);
      },
    ),
  );
  show("/users?status=active");
  fireEvent.click(
    await screen.findByRole("button", { name: analyst.username }),
  );
  const input = await screen.findByLabelText("임시 비밀번호");
  fireEvent.change(input, { target: { value: "temporary-password-1" } });
  fireEvent.click(screen.getByRole("button", { name: "비밀번호 재설정" }));
  await waitFor(() =>
    expect(body).toEqual({ temporary_password: "temporary-password-1" }),
  );
  await waitFor(() => expect(input).toHaveValue(""));
  expect(requests.map((r) => r.href).join(" ")).not.toContain(
    "temporary-password",
  );
});

test("self and the last admin cannot be disabled or demoted", async () => {
  server.use(list([admin]), catalog());
  show("/users?status=active");
  fireEvent.click(await screen.findByRole("button", { name: admin.username }));
  expect(
    await screen.findByText("마지막 활성 admin이에요"),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "계정 중지" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "역할 저장" })).toBeDisabled();
});

test("only an admin sees role change, and it sends PATCH", async () => {
  let body: unknown = null;
  server.use(
    list([analyst, admin, { ...admin, id: "x", username: "second.admin" }]),
    catalog(),
    http.patch(`*/api/users/${analyst.id}`, async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ ...analyst, role: "admin" });
    }),
  );
  show("/users?status=active");
  fireEvent.click(
    await screen.findByRole("button", { name: analyst.username }),
  );
  fireEvent.change(await screen.findByLabelText("역할"), {
    target: { value: "admin" },
  });
  fireEvent.click(screen.getByRole("button", { name: "역할 저장" }));
  await waitFor(() => expect(body).toEqual({ role: "admin" }));
});

test("permission edit keeps the values of items the actor cannot change", async () => {
  let body: { permissions: string[] } | null = null;
  const target = {
    ...analyst,
    permissions: [...analyst.permissions, "policy.update", "incident.approve"],
  };
  server.use(
    list([target]),
    catalog(),
    meAs({
      ...auth.analyst,
      permissions: [
        "user.read",
        "user.permission",
        "dashboard.read",
        "alert.read",
      ],
    }),
    http.put(`*/api/users/${analyst.id}/permissions`, async ({ request }) => {
      body = (await request.json()) as { permissions: string[] };
      return HttpResponse.json(target);
    }),
  );
  show("/users?status=active");
  fireEvent.click(
    await screen.findByRole("button", { name: analyst.username }),
  );
  const alert = await screen.findByRole("checkbox", { name: /alert\.read/ });
  expect(
    screen.getByRole("checkbox", { name: /policy\.update/ }),
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: /incident\.approve/ }),
  ).toBeDisabled();
  expect(
    screen.getByRole("checkbox", { name: /incident\.approve/ }),
  ).toBeChecked();
  fireEvent.click(alert);
  fireEvent.click(screen.getByRole("button", { name: "권한 저장" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect(body!.permissions).toContain("policy.update");
  expect(body!.permissions).toContain("incident.approve");
  expect(body!.permissions).not.toContain("alert.read");
  expect(body!.permissions).toHaveLength(target.permissions.length - 1);
});

test("an admin target cannot have its permissions edited", async () => {
  server.use(
    list([admin, { ...admin, id: "y", username: "other.admin" }]),
    catalog(),
  );
  show("/users?status=active");
  fireEvent.click(await screen.findByRole("button", { name: "other.admin" }));
  expect(
    await screen.findByText(/admin은 항상 모든 권한을 가져요/),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "권한 저장" })).toBeDisabled();
});

test("without user.read the users screen shows no permission", async () => {
  server.use(
    http.get("*/api/users", () =>
      HttpResponse.json({ error: "permission_denied" }, { status: 403 }),
    ),
  );
  show("/users");
  expect(
    await screen.findByText("이 화면을 볼 권한이 없어요"),
  ).toBeInTheDocument();
});

test("news.read is not offered in the editor but is still sent on save", async () => {
  let body: { permissions: string[] } | null = null;
  server.use(
    list([analyst]),
    catalog(),
    http.put(`*/api/users/${analyst.id}/permissions`, async ({ request }) => {
      body = (await request.json()) as { permissions: string[] };
      return HttpResponse.json(analyst);
    }),
  );
  show("/users?status=active");
  fireEvent.click(
    await screen.findByRole("button", { name: analyst.username }),
  );
  await screen.findByRole("checkbox", { name: /alert\.read/ });
  expect(screen.queryByRole("checkbox", { name: /news\.read/ })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "권한 저장" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect(body!.permissions).toContain("news.read");
});

test("the side panel can be resized with the keyboard and stays above the minimum", async () => {
  server.use(list([pendingOne]));
  show("/users");
  fireEvent.click(
    await screen.findByRole("button", { name: pendingOne.username }),
  );
  const handle = await screen.findByRole("separator", {
    name: "패널 너비 조절",
  });
  const panel = handle.closest("dialog")!;
  expect(panel.style.getPropertyValue("--panel-w")).toBe("420px");
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(panel.style.getPropertyValue("--panel-w")).toBe("444px");
  for (let i = 0; i < 10; i++) fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(panel.style.getPropertyValue("--panel-w")).toBe("360px");
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  fireEvent.doubleClick(handle);
  expect(panel.style.getPropertyValue("--panel-w")).toBe("420px");
});
