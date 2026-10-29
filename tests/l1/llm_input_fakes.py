"""Demo-sized evidence for the L1 input tests (#91), built from small hand-made templates.

``siem_alerts`` gives N C2 records the SIEM MCP would return for one IP, and the
C3 stored for each of them, so a summary can be checked against known counts.
"""

import hashlib
import json
from pathlib import Path

from soc.contracts import validate_contract
from soc.ingest.connector import source_record_id
from soc.normalize.ids import alert_id_for

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "l1" / "llm_input"


def read_json(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _fill(value, n, filler):
    if isinstance(value, str):
        text = value.replace("{n}", str(n))
        return text + filler if text.endswith(" ") else text
    if isinstance(value, dict):
        return {key: _fill(item, n, filler) for key, item in value.items()}
    if isinstance(value, list):
        return [_fill(item, n, filler) for item in value]
    return value


def siem_alerts(count=None):
    """(C2 content list, SiemAlert list, AlertRecord list) of the template."""
    template = read_json("siem_alerts.json")
    count = template["count"] if count is None else count
    filler = "x" * template["filler_chars"]
    rules = [(rule_id, name) for rule_id, name, times in template["rules"] for _ in range(times)]
    contents, sources, alerts = [], [], []
    for n in range(count):
        content = _fill(template["c2"], n, filler)
        content["source_record_id"] = source_record_id(content)
        source = validate_contract("SiemAlert", content)
        time = template["start_time"] + n * template["step_ms"]
        # 7 and 500 share no factor, so this spreads every rule over the window.
        rule_id, rule_name = rules[(n * 7) % len(rules)]
        alert = validate_contract(
            "AlertRecord",
            _fill(template["alert"], n, filler)
            | {
                "alert_id": alert_id_for(source.source_record_id),
                "source_record_id": source.source_record_id,
                "time": time,
                "rule_id": rule_id,
                "rule_name": rule_name,
                "first_seen": time,
                "last_seen": time,
            },
        )
        contents.append(source.model_dump(mode="json"))
        sources.append(source)
        alerts.append(alert)
    return contents, sources, alerts


def web_flow_events(at, *, extra_4xx=0):
    """C13 of ``web_flow.json`` around ``at`` (ms), plus ``extra_4xx`` 404 scan lines.

    Returns (events, IDs of the upload and web shell command lines).
    """
    flow = read_json("web_flow.json")
    lines = list(flow["lines"])
    for n in range(extra_4xx):
        offset = -20 + (n * 40) // max(1, extra_4xx)
        url = f"/synthetic-wordlist/entry-{n:04d}/admin/config.backup.php"
        lines.append({"offset_s": offset, "url": url, "status": 404, "role": "scan"})
    events, attack_ids = [], []
    for n, line in enumerate(lines):
        digest = hashlib.sha256(f"web-flow-{n}".encode()).hexdigest()
        event = {
            "event_id": f"ev_{digest}",
            "source_record_id": f"src_{digest}",
            "class_uid": 4002,
            "time": at + line["offset_s"] * 1000,
            "activity": "http_request",
            "src_ip": flow["src_ip"],
            "dst_ip": flow["dst_ip"],
            "host": "web-01",
            "user": None,
            "http_url": line["url"],
            "http_status": line["status"],
            "http_bytes": None,
            "api_operation": None,
            "status": None,
            "src_asset": None,
            "dst_asset": None,
            "user_info": None,
            "raw_ids": [f"raw_synthetic_access.log_{n + 1}"],
            "unmapped": {
                "method": "POST" if line["role"] == "upload" else "GET",
                "bytes": "1301",
                "user_agent": "python-requests/2.27.1",
            },
            "extensions": {},
        }
        events.append(validate_contract("EventRecord", event))
        if line["role"] in {"upload", "command"}:
            attack_ids.append(event["event_id"])
    return events, attack_ids
