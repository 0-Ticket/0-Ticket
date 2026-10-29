"""Fake lookup provider and sample C4 rows for the box 4 tests."""

from soc.contracts import AssetInfo, UserInfo

T = 1642500341120

WEB_01 = AssetInfo.model_validate(
    {
        "match": "192.0.2.80",
        "hostname": "web-01",
        "criticality": 5,
        "owner": None,
        "zone": "dmz",
        "shared": False,
        "valid_from": None,
        "valid_to": None,
        "extensions": {},
    }
)
ALICE = UserInfo.model_validate(
    {"user": "alice", "dept": None, "privileged": False, "extensions": {}}
)


class FakeLookup:
    def __init__(self, assets=None, users=None):
        self.assets = assets or {}
        self.users = users or {}
        self.calls = []

    def find_asset(self, value, at):
        self.calls.append(("asset", value, at))
        return self.assets.get(value)

    def find_user(self, user, at):
        self.calls.append(("user", user, at))
        return self.users.get(user)
