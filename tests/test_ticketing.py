"""Ticket 정책 로드, 계약, API 요청 경계를 확인한다(#246)."""

import json
from pathlib import Path

import pytest
from auth_support import admin_client, make_client

from soc.api.app import create_app
from soc.api.config import load_settings
from soc.contracts import ContractError, validate_contract
from soc.ticketing import ConfigError, TicketingPolicy, load_policy, parse_policy


def test_default_ticketing_policy_is_auto(default_config_dir: Path) -> None:
    assert load_policy(default_config_dir) == TicketingPolicy("auto", ())


def test_local_ticketing_policy_overrides_default(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(
        '[ticketing]\nmode = "auto"\nscenario_rule_ids = []\n', encoding="utf-8"
    )
    (tmp_path / "local.toml").write_text(
        '[ticketing]\nmode = "scenario"\nscenario_rule_ids = ["rule-1"]\n',
        encoding="utf-8",
    )

    assert load_policy(tmp_path) == TicketingPolicy("scenario", ("rule-1",))


@pytest.mark.parametrize(
    "value",
    [
        None,
        {},
        {"mode": "unknown", "scenario_rule_ids": []},
        {"mode": "auto", "scenario_rule_ids": "rule-1"},
        {"mode": "auto", "scenario_rule_ids": [1]},
        {"mode": "auto", "scenario_rule_ids": [], "extra": True},
    ],
)
def test_invalid_ticketing_policy_is_rejected(value: object) -> None:
    with pytest.raises(ConfigError):
        parse_policy(value)


def test_w04_ticket_contract_rejects_multiple_alerts() -> None:
    fixture = Path(__file__).parent / "fixtures" / "contracts" / "valid" / "ticket.json"
    ticket = json.loads(fixture.read_text(encoding="utf-8"))[0]["data"]
    ticket["alert_ids"] = [
        "alt_01a19f93-1150-7000-8000-000000000001",
        "alt_01a19f93-1150-7000-8000-000000000002",
    ]

    with pytest.raises(ContractError) as error:
        validate_contract("ticket", ticket)

    assert [(violation.path, violation.rule) for violation in error.value.violations] == [
        ("alert_ids", "maxItems")
    ]


def test_l3_ticket_contract_still_allows_multiple_alerts() -> None:
    fixture = Path(__file__).parent / "fixtures" / "contracts" / "valid" / "ticket.json"
    tickets = json.loads(fixture.read_text(encoding="utf-8"))
    ticket = next(row["data"] for row in tickets if row["case"] == "l3_escalated")
    ticket["alert_ids"] = [
        "alt_01a19f93-1150-7000-8000-000000000001",
        "alt_01a19f93-1150-7000-8000-000000000002",
    ]

    validate_contract("ticket", ticket)


def test_ticketing_policy_api_is_connected_and_needs_a_session() -> None:
    app = create_app(load_settings())
    operations = app.openapi()["paths"]["/api/ticketing-policy"]
    assert set(operations) == {"get", "put"}

    client = make_client()
    assert client.get("/api/ticketing-policy").status_code == 401
    body = {"mode": "auto", "scenario_rule_ids": []}
    assert client.put("/api/ticketing-policy", json=body).status_code == 401


def test_invalid_policy_body_does_not_echo_values_or_require_database(
    caplog: pytest.LogCaptureFixture,
) -> None:
    marker = "BODY-MUST-NOT-LEAK"
    with admin_client() as client:
        response = client.put(
            "/api/ticketing-policy",
            json={"mode": marker, "scenario_rule_ids": []},
        )

    assert response.status_code == 422
    assert response.json() == {"error": "invalid_body", "fields": ["mode"]}
    assert marker not in response.text
    assert marker not in caplog.text
