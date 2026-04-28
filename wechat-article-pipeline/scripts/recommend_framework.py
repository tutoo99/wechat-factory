#!/usr/bin/env python3
"""
按 channel / 选题 / 目标 / 素材形态推荐文章框架。

示例：
  python3 recommend_framework.py \
    --channel tech \
    --topic "我把公众号发布系统重构成 channel 模型" \
    --goal click --goal save \
    --material-type case --material-type opinion \
    --material-depth heavy
"""

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
FACTORY_ROOT = SCRIPT_DIR.parent.parent
FRAMEWORKS_ROOT = FACTORY_ROOT / "frameworks"
CHANNELS_CONFIG = FACTORY_ROOT / "channels.yaml"

DEPTH_ORDER = {"light": 1, "medium": 2, "heavy": 3}
FALLBACK_CODES = [
    ("8", "重推，偏点击"),
    ("9", "重推，偏完读"),
    ("10", "重推，偏收藏"),
    ("11", "我补充素材，你再推荐"),
    ("12", "现有框架都不合适，生成新框架草案"),
]


@dataclass
class FrameworkCandidate:
    path: Path
    data: Dict
    score: int
    reasons: List[str]
    risks: List[str]


def load_yaml(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_channels() -> Dict:
    if not CHANNELS_CONFIG.exists():
        raise FileNotFoundError("未找到 channels.yaml: %s" % CHANNELS_CONFIG)
    data = load_yaml(CHANNELS_CONFIG)
    channels = data.get("channels") or {}
    if not isinstance(channels, dict):
        raise ValueError("channels.yaml 格式错误：channels 必须是对象映射")
    return channels


def infer_lane(channel_id: str, channel: Dict) -> str:
    lane = (channel.get("lane") or "").strip()
    if lane:
        return lane
    persona = (channel.get("persona") or "").strip()
    archive_account = (channel.get("archive_account") or "").strip()
    for candidate in (persona, archive_account, channel_id):
        if candidate in {"tech", "emotion"}:
            return candidate
    return persona or archive_account or channel_id


def load_frameworks(lane: str) -> List[Tuple[Path, Dict]]:
    dirs = [FRAMEWORKS_ROOT / lane, FRAMEWORKS_ROOT / "common"]
    frameworks = []
    for base in dirs:
        if not base.exists():
            continue
        for path in sorted(base.glob("*.yaml")):
            frameworks.append((path, load_yaml(path)))
    return frameworks


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"[\s,，。！？、:：/\-_()（）]+", text.lower())
    return [part for part in parts if part]


def count_keyword_hits(topic: str, keywords: List[str]) -> int:
    topic_lower = topic.lower()
    return sum(1 for word in keywords if word and isinstance(word, str) and word.lower() in topic_lower)


def depth_ok(requested: str, minimum: str) -> bool:
    requested = (requested or "light").lower()
    minimum = (minimum or "light").lower()
    return DEPTH_ORDER.get(requested, 1) >= DEPTH_ORDER.get(minimum, 1)


def score_framework(
    framework: Dict,
    lane: str,
    topic: str,
    goals: List[str],
    material_types: List[str],
    material_depth: str,
) -> Tuple[int, List[str], List[str]]:
    score = 0
    reasons: List[str] = []
    risks: List[str] = []

    framework_lane = framework.get("lane")
    if framework_lane == lane:
        score += 40
        reasons.append("赛道完全匹配 `%s`" % lane)
    elif framework_lane == "common":
        score += 22
        reasons.append("属于跨赛道通用框架")
    else:
        return -999, [], ["赛道不匹配"]

    keyword_hits = count_keyword_hits(topic, framework.get("keywords") or [])
    if keyword_hits:
        score += min(keyword_hits * 7, 28)
        reasons.append("选题命中 %d 个关键词" % keyword_hits)

    anti_hits = count_keyword_hits(topic, framework.get("anti_keywords") or [])
    if anti_hits:
        score -= anti_hits * 8
        risks.append("选题命中 %d 个反向关键词" % anti_hits)

    goal_overlap = sorted(set(goals) & set(framework.get("suitable_goals") or []))
    if goal_overlap:
        score += len(goal_overlap) * 9
        reasons.append("传播目标匹配 `%s`" % " / ".join(goal_overlap))
    else:
        risks.append("传播目标与该框架不够贴")

    material_overlap = sorted(set(material_types) & set(framework.get("material_types") or []))
    if material_overlap:
        score += len(material_overlap) * 8
        reasons.append("素材形态匹配 `%s`" % " / ".join(material_overlap))
    else:
        risks.append("素材形态和该框架不够贴")

    minimum_depth = ((framework.get("material_depth") or {}).get("min") or "light").lower()
    if depth_ok(material_depth, minimum_depth):
        score += 8
        reasons.append("素材完整度满足最低要求 `%s`" % minimum_depth)
    else:
        score -= 12
        risks.append("素材完整度偏低，最低建议 `%s`" % minimum_depth)

    priority = int(framework.get("priority") or 0)
    score += min(priority // 20, 5)

    if not reasons:
        reasons.append("基础条件满足")
    risks.extend(framework.get("constraints") or [])
    return score, reasons[:3], risks[:2]


def recommend(
    channel_id: str,
    topic: str,
    goals: List[str],
    material_types: List[str],
    material_depth: str,
    top_k: int,
) -> Tuple[str, List[FrameworkCandidate]]:
    channels = load_channels()
    channel = channels.get(channel_id)
    if not channel:
        raise KeyError("未找到 channel '%s'" % channel_id)

    lane = infer_lane(channel_id, channel)
    frameworks = load_frameworks(lane)
    if not frameworks:
        raise FileNotFoundError("没有找到 lane=%s 的框架文件" % lane)

    candidates: List[FrameworkCandidate] = []
    for path, framework in frameworks:
        score, reasons, risks = score_framework(
            framework=framework,
            lane=lane,
            topic=topic,
            goals=goals,
            material_types=material_types,
            material_depth=material_depth,
        )
        if score <= -999:
            continue
        candidates.append(
            FrameworkCandidate(
                path=path,
                data=framework,
                score=score,
                reasons=reasons,
                risks=risks,
            )
        )

    candidates.sort(
        key=lambda item: (
            item.score,
            int(item.data.get("priority") or 0),
            item.data.get("name") or "",
        ),
        reverse=True,
    )
    return lane, candidates[:top_k]


def print_result(
    channel_id: str,
    lane: str,
    topic: str,
    goals: List[str],
    material_types: List[str],
    material_depth: str,
    candidates: List[FrameworkCandidate],
) -> None:
    print("为你推荐以下写作框架（回复编号即可选择）：\n")

    for index, candidate in enumerate(candidates, start=1):
        data = candidate.data
        name = data.get("name", candidate.path.stem)
        summary = data.get("summary") or "-"
        # 从 suitable_topics 取前 2 个作为场景提示
        topics = data.get("suitable_topics") or []
        scene = "、".join(topics[:2]) if topics else ""
        print("%d. 【%s】" % (index, name))
        print("   %s" % summary)
        if scene:
            print("   适用：%s" % scene)
        if candidate.reasons:
            print("   推荐理由：%s" % "；".join(candidate.reasons))
        if candidate.risks:
            print("   注意：%s" % "；".join(candidate.risks))
        print("")

    direct_codes = "/".join(str(i) for i in range(1, len(candidates) + 1)) if candidates else "-"
    print("回复编号直接选择：`%s`" % direct_codes)
    for code, text in FALLBACK_CODES:
        print("- `%s`：%s" % (code, text))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="按选题推荐框架（编号式输出）")
    parser.add_argument("--channel", required=True, help="频道标识，如 tech / emotion")
    parser.add_argument("--topic", required=True, help="本次文章选题")
    parser.add_argument("--goal", action="append", default=[], help="传播目标，可重复传入，如 click / save")
    parser.add_argument(
        "--material-type",
        action="append",
        default=[],
        help="素材形态，可重复传入，如 story / problem / case / list / opinion",
    )
    parser.add_argument(
        "--material-depth",
        default="medium",
        choices=["light", "medium", "heavy"],
        help="素材完整度，默认 medium",
    )
    parser.add_argument("--top-k", type=int, default=3, help="返回候选数量，默认 3")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    goals = [goal.strip() for goal in args.goal if goal.strip()]
    material_types = [value.strip() for value in args.material_type if value.strip()]
    lane, candidates = recommend(
        channel_id=args.channel,
        topic=args.topic,
        goals=goals,
        material_types=material_types,
        material_depth=args.material_depth,
        top_k=args.top_k,
    )
    print_result(
        channel_id=args.channel,
        lane=lane,
        topic=args.topic,
        goals=goals,
        material_types=material_types,
        material_depth=args.material_depth,
        candidates=candidates,
    )


if __name__ == "__main__":
    main()
