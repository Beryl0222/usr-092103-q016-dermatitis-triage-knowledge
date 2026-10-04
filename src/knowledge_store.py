"""知识版本包装载与索引。

每个知识包（knowledge/kb-YYYY-NN.json）把权威来源、适用人群、暴露方式、
症状组合、严重程度、禁忌处理、居家步骤、就医条件（规则）、采集问题、
季节风险与发布渠道分别放在独立模块中，每个模块带自己的 module_version，
便于单独修订与追溯。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_DIR = REPO_ROOT / "knowledge"

# 严重程度的缺省排序（知识包 severity_levels 模块缺失时兜底）
DEFAULT_RANK = {
    "emergency_now": 4,
    "urgent_same_day": 3,
    "reassess_24_48": 2,
    "home_observe": 1,
    "indeterminate": 0,
}

ESCALATION_LEVELS = {"urgent_same_day", "emergency_now"}

# 要得出“可居家观察”结论，至少要问清的采集问题（任一相关事实确认或否认）
CORE_QUESTIONS_FOR_HOME = (
    "q-age",
    "q-site",
    "q-lesion",
    "q-area",
    "q-integrity",
    "q-systemic",
)

# 这些问题没问清时，必须以不确定性提示就高不就低
HIGH_RISK_FACTS = (
    "systemic_anaphylaxis",
    "extensive_blisters",
    "erosion_oozing",
    "infection_signs",
    "site_face",
    "tick_attached",
    "is_infant",
)


@lru_cache(maxsize=None)
def load_kb(version: str) -> dict:
    path = KNOWLEDGE_DIR / f"{version}.json"
    if not path.exists():
        raise FileNotFoundError(f"知识版本不存在：{version}（{path}）")
    return json.loads(path.read_text(encoding="utf-8"))


def active_kb_version() -> str:
    versions = sorted(p.stem for p in KNOWLEDGE_DIR.glob("kb-*.json"))
    for v in reversed(versions):
        if load_kb(v).get("status") == "active":
            return v
    if versions:
        return versions[-1]
    raise FileNotFoundError("knowledge/ 下没有任何知识版本包")


def module(kb: dict, name: str) -> dict:
    return kb.get("modules", {}).get(name, {})


def module_version(kb: dict, name: str) -> str | None:
    return module(kb, name).get("module_version")


def catalog_index(kb: dict, module_name: str) -> dict[str, dict]:
    return {item["id"]: item for item in module(kb, module_name).get("items", [])}


def level_rank(kb: dict, level: str) -> int:
    for item in module(kb, "severity_levels").get("items", []):
        if item.get("level") == level:
            return int(item["rank"])
    return DEFAULT_RANK.get(level, 0)


def level_label(kb: dict, level: str) -> str:
    for item in module(kb, "severity_levels").get("items", []):
        if item.get("level") == level:
            return item.get("public_label", level)
    return {
        "emergency_now": "立即急诊/拨120",
        "urgent_same_day": "当日尽快就医",
        "reassess_24_48": "24–48小时内复诊评估",
        "home_observe": "可居家护理并观察",
        "indeterminate": "信息不足，先补充问题",
    }.get(level, level)
