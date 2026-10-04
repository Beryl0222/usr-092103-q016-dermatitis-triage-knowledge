"""领域事件公共字段与按类型载荷的基础校验（仅依赖标准库）。"""

from __future__ import annotations

REQUIRED = ("event_id", "event_type", "aggregate_type", "aggregate_id", "occurred_at", "version", "summary")

EVENT_TYPES = (
    "KNOWLEDGE_PUBLISHED",
    "RISK_SIGNAL_REPORTED",
    "CLUSTER_REVIEWED",
    "CONSULTATION_ASSESSED",
    "CASE_ESCALATED",
    "CONTENT_WITHDRAWN",
    "CHANNEL_PUBLISHED",
    "CHANNEL_TAKEDOWN_CONFIRMED",
)

AGGREGATE_TYPES = ("knowledge_revision", "consultation_case", "risk_signal", "channel_release", "cluster_alert")

LEVELS = ("home_observe", "reassess_24_48", "urgent_same_day", "emergency_now", "indeterminate")

# 每种事件 payload 的必填字段
PAYLOAD_REQUIRED = {
    "KNOWLEDGE_PUBLISHED": ("kb_version",),
    "RISK_SIGNAL_REPORTED": ("signal_id", "reported_by_facility", "case_count", "status"),
    "CLUSTER_REVIEWED": ("decision", "signal_ids"),
    "CONSULTATION_ASSESSED": ("case_id", "kb_version", "facts", "level", "uncertainty", "missing_question_ids"),
    "CASE_ESCALATED": ("case_id", "target", "reason_rule_id"),
    "CONTENT_WITHDRAWN": ("items",),
    "CHANNEL_PUBLISHED": ("channel", "revision_id", "kb_version", "content_refs"),
    "CHANNEL_TAKEDOWN_CONFIRMED": ("revision_id", "withdrawn_event_id", "confirmed_by"),
}


def validate_event(record: dict) -> list[str]:
    errors = [f"缺少字段：{name}" for name in REQUIRED if name not in record]
    if "version" in record and (not isinstance(record["version"], int) or record["version"] < 1):
        errors.append("version 必须是正整数")
    if "event_type" in record and record["event_type"] not in EVENT_TYPES:
        errors.append(f"event_type 未登记：{record['event_type']}")
    if "aggregate_type" in record and record["aggregate_type"] not in AGGREGATE_TYPES:
        errors.append(f"aggregate_type 未登记：{record['aggregate_type']}")
    return errors


def validate_event_full(record: dict) -> list[str]:
    """信封 + 载荷类型的结构校验。"""
    errors = validate_event(record)
    event_type = record.get("event_type")
    payload = record.get("payload")
    if event_type in PAYLOAD_REQUIRED:
        if not isinstance(payload, dict):
            errors.append(f"{event_type} 必须包含对象类型 payload")
        else:
            for name in PAYLOAD_REQUIRED[event_type]:
                if name not in payload:
                    errors.append(f"{event_type}.payload 缺少字段：{name}")
            if event_type == "CONSULTATION_ASSESSED" and payload.get("level") not in LEVELS:
                errors.append("CONSULTATION_ASSESSED.level 非法")
            if event_type == "CLUSTER_REVIEWED" and payload.get("decision") not in (
                "confirm_alert", "no_alert", "need_more_info"
            ):
                errors.append("CLUSTER_REVIEWED.decision 非法")
    return errors
