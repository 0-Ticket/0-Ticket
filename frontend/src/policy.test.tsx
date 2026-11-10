import { expect, test } from "vitest";
import { screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { auth, requests, server, show } from "./test-utils";

const policy = () =>
  http.get("*/api/ticketing-policy", () => HttpResponse.json(auth.policy));
const [first, second] = auth.policy.scenario_rule_ids;

test("shows the stored policy and keeps rule ids as text", async () => {
  server.use(policy());
  show("/policy");
  expect(
    await screen.findByRole("radio", { name: /시나리오 \(scenario\)/ }),
  ).toBeChecked();
  expect(screen.getByRole("checkbox", { name: first })).toBeChecked();
  expect(screen.getByText(second)).toBeInTheDocument();
  expect(document.querySelector("i")).toBeNull();
});

test("saving sends the whole policy and shows success", async () => {
  let body: unknown = null;
  server.use(
    policy(),
    http.put("*/api/ticketing-policy", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(body as typeof auth.policy);
    }),
  );
  show("/policy");
  fireEvent.click(await screen.findByRole("checkbox", { name: first }));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  expect(await screen.findByText("정책을 저장했어요")).toBeInTheDocument();
  expect(body).toEqual({ mode: "scenario", scenario_rule_ids: [second] });
});

test("switching to auto keeps the chosen rule ids in the request", async () => {
  let body: unknown = null;
  server.use(
    policy(),
    http.put("*/api/ticketing-policy", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json(body as typeof auth.policy);
    }),
  );
  show("/policy");
  fireEvent.click(await screen.findByRole("radio", { name: /자동 \(auto\)/ }));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(body).not.toBeNull());
  expect(body).toEqual({
    mode: "auto",
    scenario_rule_ids: auth.policy.scenario_rule_ids,
  });
});

test("a new rule id can be added and cancel restores the stored policy", async () => {
  server.use(policy());
  show("/policy");
  await screen.findByRole("checkbox", { name: first });
  fireEvent.change(screen.getByLabelText("규칙 ID 추가"), {
    target: { value: "new-rule" },
  });
  fireEvent.click(screen.getByRole("button", { name: "추가" }));
  expect(screen.getByRole("checkbox", { name: "new-rule" })).toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "변경 취소" }));
  expect(screen.queryByRole("checkbox", { name: "new-rule" })).toBeNull();
});

test("a failed save keeps the form and says so", async () => {
  server.use(
    policy(),
    http.put("*/api/ticketing-policy", () =>
      HttpResponse.json({ error: "db_unavailable" }, { status: 503 }),
    ),
  );
  show("/policy");
  fireEvent.click(await screen.findByRole("checkbox", { name: first }));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  expect(
    await screen.findByText("정책을 저장하지 못했어요"),
  ).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: first })).not.toBeChecked();
});

test("without policy.update the policy is read-only", async () => {
  server.use(
    policy(),
    http.get("*/api/auth/me", () =>
      HttpResponse.json({
        ...auth.analyst,
        permissions: ["policy.read", "dashboard.read"],
      }),
    ),
  );
  show("/policy");
  expect(await screen.findByText("읽기 전용이에요")).toBeInTheDocument();
  expect(screen.getByRole("radio", { name: /자동 \(auto\)/ })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "저장" })).toBeNull();
});

test("the CSV register button is there but does nothing yet", async () => {
  server.use(policy());
  show("/policy");
  const button = await screen.findByRole("button", { name: "CSV로 등록하기" });
  const before = requests.length;
  fireEvent.click(button);
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(requests.length).toBe(before);
  expect(screen.getByTestId("where")).toHaveTextContent(/^\/policy$/);
});
