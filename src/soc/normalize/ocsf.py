"""C3 -> OCSF 1.9.0 Detection Finding (class_uid 2004) as plain JSON (box 4, D-017, K6).

In OCSF 1.9.0 the endpoints, HTTP request and response, and user of a finding
live in ``evidences[]`` and ATT&CK in ``finding_info.attacks``, not at the top
level (docs/data-contracts.md C3).
C3 has no ID, so the caller passes the finding's ``uid`` (a C5 passes its
``alert_id``). ``raw_ids`` and ``extensions`` have no OCSF place and are left out.
"""

from typing import Any

from soc.contracts import AlertRecord, NormalizedAlert

OCSF_VERSION = "1.9.0"
PRODUCT_NAME = "0-Ticket SOC"
CATEGORY_UID = 2  # Findings
ACTIVITY_CREATE = 1
ANALYTIC_RULE = 1
DEVICE_TYPE_UNKNOWN = 0


def to_ocsf_detection_finding(
    alert: NormalizedAlert | AlertRecord, finding_uid: str
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "activity_id": ACTIVITY_CREATE,
        "category_uid": CATEGORY_UID,
        "class_uid": alert.class_uid,
        "type_uid": alert.class_uid * 100 + ACTIVITY_CREATE,
        "time": alert.time,
        "severity_id": alert.severity_id,
        "metadata": {"version": OCSF_VERSION, "product": {"name": PRODUCT_NAME}},
        "finding_info": {
            "uid": finding_uid,
            "title": alert.rule_name,
            "analytic": {"uid": alert.rule_id, "name": alert.rule_name, "type_id": ANALYTIC_RULE},
        },
    }
    device = {"hostname": alert.host, "type_id": DEVICE_TYPE_UNKNOWN} if alert.host else None
    if device:
        finding["device"] = device
    # C3 always has src_ip, dst_ip or host, so the evidence always names an endpoint or device.
    evidence: dict[str, Any] = {}
    for key, ip, port in (
        ("src_endpoint", alert.src_ip, alert.src_port),
        ("dst_endpoint", alert.dst_ip, alert.dst_port),
    ):
        if ip is not None:
            evidence[key] = {"ip": ip} if port is None else {"ip": ip, "port": port}
    if device:
        evidence["device"] = dict(device)
    if alert.user is not None:
        evidence["user"] = {"name": alert.user}
    if alert.http_url is not None:
        evidence["http_request"] = {"url": {"url_string": alert.http_url}}
    if alert.http_status is not None:
        evidence["http_response"] = {"code": alert.http_status}
    finding["evidences"] = [evidence]
    if alert.techniques:
        finding["finding_info"]["attacks"] = [
            {"technique": {"uid": uid}} for uid in alert.techniques
        ]
    if alert.unmapped:
        finding["unmapped"] = alert.unmapped
    return finding
