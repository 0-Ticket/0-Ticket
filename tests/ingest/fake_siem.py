"""In-memory fake SIEM connector for tests (SIEM connector, K66).

Like any adapter it returns C2 content without source_record_id; the core assigns it.

It reads its address and token the way a real adapter would: the address from
settings, the token from the environment variable that settings name.
"""

from collections.abc import Mapping

from soc.config import SiemSettings, read_secret
from soc.ingest.siem.base import FetchBatch, HealthStatus, InvalidCursorError

FAKE_ALERTS = [
    {
        "kind": "alert" if number % 2 else "event",
        "scenario": "fake_scenario",
        "raw_ids": [f"raw_fake_{number}"],
        "fields": {"rule": {"id": number}, "src_ip": "192.0.2.1"},
    }
    for number in range(1, 6)
]


class FakeSiem:
    def __init__(self, base_url: str, token: str, alerts=FAKE_ALERTS, reachable: bool = True):
        self.base_url = base_url
        self._token = token
        self._alerts = [dict(alert) for alert in alerts]
        self._reachable = reachable
        self.limits: list[int] = []

    def fetch(self, cursor: str | None, limit: int) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        self.limits.append(limit)
        start = 0
        if cursor is not None:
            if not cursor.isdigit():
                raise InvalidCursorError("fake cursor must be a number")
            start = int(cursor)
        items = tuple(self._alerts[start : start + limit])
        next_cursor = str(start + len(items)) if items else cursor
        return FetchBatch(items=items, next_cursor=next_cursor)

    def health_check(self) -> HealthStatus:
        if not self._reachable:
            return HealthStatus(ok=False, detail=f"cannot reach {self.base_url}")
        return HealthStatus(ok=True, detail=f"connected to {self.base_url}")


def fake_factory(settings: SiemSettings, environ: Mapping[str, str]) -> FakeSiem:
    return FakeSiem(settings.base_url, read_secret(settings.token_env, environ))
