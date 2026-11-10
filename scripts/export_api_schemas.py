"""API 응답 JSON Schema를 stdout으로 내보낸다(DB 연결 없음)."""

import json

from soc.api import auth_models, models, ui_models

NAMES = {
    models: ("HuntPage", "HuntDetail", "TicketingPolicyResponse"),
    auth_models: ("Me", "UserItem", "UserList", "PermissionList", "SignupResult"),
    ui_models: (
        "RawPage",
        "RawDetail",
        "TicketPage",
        "TicketDetail",
        "IncidentPage",
        "IncidentDetail",
        "CasePage",
        "CaseDetail",
        "Dashboard",
    ),
}

if __name__ == "__main__":
    print(
        json.dumps(
            {
                name: getattr(module, name).model_json_schema()
                for module, names in NAMES.items()
                for name in names
            }
        )
    )
