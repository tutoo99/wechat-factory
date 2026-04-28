#!/usr/bin/env python3
"""Recommend WeChat article themes from theme pack v1 metadata."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

from core.normalize import parse_frontmatter, strip_publish_materials
from core.themes.loader import list_available_themes, load_theme_pack


FACTORY_ROOT = Path(__file__).resolve().parents[1]
CHANNELS_CONFIG = FACTORY_ROOT.parent / "channels.yaml"


@dataclass
class ThemeCandidate:
    theme_name: str
    theme: Dict
    score: int
    reasons: List[str]
    risks: List[str]


def load_channels() -> Dict:
    import yaml

    if not CHANNELS_CONFIG.exists():
        return {}
    with open(CHANNELS_CONFIG, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    channels = data.get("channels") or {}
    return channels if isinstance(channels, dict) else {}


def infer_from_channel(channel_id: str) -> Tuple[str | None, str | None]:
    channels = load_channels()
    channel = channels.get(channel_id) or {}
    lane = (channel.get("lane") or "").strip() or None
    persona = (channel.get("persona") or "").strip() or None
    return lane, persona


def analyze_source(source_path: Path) -> Dict:
    md_text = source_path.read_text(encoding="utf-8")
    _, body = parse_frontmatter(md_text)
    body = strip_publish_materials(body)

    contains_code = "```" in body or "`" in body
    contains_table = bool(re.search(r"^\|.+\|$", body, re.MULTILINE))
    contains_quote = bool(re.search(r"^\s*>\s+", body, re.MULTILINE))
    article_length = "short"
    char_count = len(body)
    if char_count > 3500:
        article_length = "long"
    elif char_count > 1800:
        article_length = "medium"

    emotional_markers = ["委屈", "关系", "婚姻", "情绪", "心里", "孤独", "后悔", "温柔", "体面", "边界"]
    emotional_density = "high" if sum(marker in body for marker in emotional_markers) >= 3 else "low"

    return {
        "contains_code": contains_code,
        "contains_table": contains_table,
        "contains_quote": contains_quote,
        "article_length": article_length,
        "emotional_density": emotional_density,
    }


def normalize_features(args) -> Dict:
    features: Dict[str, object] = {}
    if args.source:
        features.update(analyze_source(Path(args.source)))
    if args.contains_code is not None:
        features["contains_code"] = args.contains_code
    if args.contains_table is not None:
        features["contains_table"] = args.contains_table
    if args.emotional_density:
        features["emotional_density"] = args.emotional_density
    if args.audience_age:
        features["audience_age"] = args.audience_age
    if args.article_length:
        features["article_length"] = args.article_length
    return features


def compare_feature(expected, actual) -> bool:
    if expected is None:
        return False
    if isinstance(expected, bool):
        return bool(actual) == expected
    return str(actual).lower() == str(expected).lower()


def score_theme(
    theme_name: str,
    theme: Dict,
    lane: str | None,
    persona: str | None,
    article_subtype: str | None,
    goals: List[str],
    features: Dict,
) -> ThemeCandidate:
    manifest = theme.get("manifest") or {}
    heuristics = theme.get("heuristics") or {}
    score = 0
    reasons: List[str] = []
    risks: List[str] = []

    lane_fit = manifest.get("lane_fit") or []
    if lane and lane in lane_fit:
        score += 24
        reasons.append(f"赛道匹配 `{lane}`")
    elif lane_fit:
        risks.append(f"主适配赛道为 `{', '.join(lane_fit)}`")

    persona_fit = manifest.get("persona_fit") or []
    if persona and persona in persona_fit:
        score += 16
        reasons.append(f"人设匹配 `{persona}`")

    article_fit = manifest.get("article_fit") or []
    if article_subtype and article_subtype in article_fit:
        score += 18
        reasons.append(f"文章类型匹配 `{article_subtype}`")
    elif article_subtype and article_fit:
        risks.append(f"更适合 `{', '.join(article_fit[:3])}`")

    goal_fit = set(manifest.get("goal_fit") or [])
    goal_overlap = sorted(goal_fit & set(goals))
    if goal_overlap:
        score += len(goal_overlap) * 8
        reasons.append(f"目标匹配 `{ ' / '.join(goal_overlap) }`")

    prefer = heuristics.get("prefer") or {}
    avoid = heuristics.get("avoid") or {}

    prefer_features = prefer.get("content_features") or {}
    for key, expected in prefer_features.items():
        if key in features and compare_feature(expected, features.get(key)):
            score += 6
            reasons.append(f"{key} 偏好命中")

    avoid_features = avoid.get("content_features") or {}
    for key, expected in avoid_features.items():
        if key in features and compare_feature(expected, features.get(key)):
            score -= 10
            risks.append(f"{key} 与该主题偏好相反")

    if features.get("article_length") == "long":
        if article_subtype in {"mistake_breakdown", "long_read"} or "long_read" in article_fit:
            score += 4

    safe_level = (manifest.get("wechat_safe_level") or "medium").lower()
    if safe_level == "high":
        score += 4
    elif safe_level == "experimental":
        score -= 2
        risks.append("兼容性仍处于 experimental")

    if not reasons:
        reasons.append("基础条件可用")

    notes = (heuristics.get("notes") or []) + (manifest.get("authoring_notes") or [])
    if notes and len(risks) < 2:
        risks.append(notes[0])

    return ThemeCandidate(theme_name=theme_name, theme=theme, score=score, reasons=reasons[:3], risks=risks[:2])


def recommend_themes(
    lane: str | None,
    persona: str | None,
    article_subtype: str | None,
    goals: List[str],
    features: Dict,
    top_k: int,
) -> List[ThemeCandidate]:
    candidates: List[ThemeCandidate] = []
    for theme_name in list_available_themes():
        theme = load_theme_pack(theme_name)
        candidates.append(score_theme(theme_name, theme, lane, persona, article_subtype, goals, features))
    candidates.sort(
        key=lambda item: (
            item.score,
            item.theme.get("manifest", {}).get("wechat_safe_level") == "high",
            item.theme_name,
        ),
        reverse=True,
    )
    return candidates[:top_k]


def print_result(
    lane: str | None,
    persona: str | None,
    article_subtype: str | None,
    goals: List[str],
    features: Dict,
    candidates: List[ThemeCandidate],
) -> None:
    print("# 主题推荐\n")
    print(f"- lane: `{lane or '-'}`")
    print(f"- persona: `{persona or '-'}`")
    print(f"- article_subtype: `{article_subtype or '-'}`")
    print(f"- goals: {', '.join(goals) if goals else '-'}")
    print(f"- features: {features or '-'}")
    print("")

    for index, candidate in enumerate(candidates, start=1):
        manifest = candidate.theme.get("manifest") or {}
        print(f"{index}. {manifest.get('display_name') or candidate.theme_name}")
        print(f"   - id: `{candidate.theme_name}`")
        print(f"   - score: {candidate.score}")
        print(f"   - summary: {manifest.get('description') or '-'}")
        print(f"   - 推荐原因: {'；'.join(candidate.reasons) if candidate.reasons else '-'}")
        print(f"   - 风险提示: {'；'.join(candidate.risks) if candidate.risks else '-'}")
        print("")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="根据 channel / 内容特征推荐排版主题")
    parser.add_argument("--channel", default=None, help="channel 标识，如 tech / emotion")
    parser.add_argument("--lane", default=None, help="手动指定赛道")
    parser.add_argument("--persona", default=None, help="手动指定 persona")
    parser.add_argument("--article-subtype", default=None, help="文章类型，如 mistake_breakdown / emotional_story")
    parser.add_argument("--goal", action="append", default=[], help="传播目标，可重复传入")
    parser.add_argument("--source", default=None, help="Markdown 源文件，可自动分析内容特征")
    parser.add_argument("--contains-code", dest="contains_code", action="store_true", help="显式声明包含代码")
    parser.add_argument("--no-contains-code", dest="contains_code", action="store_false", help="显式声明不包含代码")
    parser.set_defaults(contains_code=None)
    parser.add_argument("--contains-table", dest="contains_table", action="store_true", help="显式声明包含表格")
    parser.add_argument("--no-contains-table", dest="contains_table", action="store_false", help="显式声明不包含表格")
    parser.set_defaults(contains_table=None)
    parser.add_argument("--emotional-density", choices=["low", "high"], default=None, help="情绪浓度")
    parser.add_argument("--audience-age", choices=["general", "senior"], default=None, help="读者年龄层")
    parser.add_argument("--article-length", choices=["short", "medium", "long"], default=None, help="文章长度")
    parser.add_argument("--top-k", type=int, default=3, help="返回候选数量，默认 3")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    lane = args.lane
    persona = args.persona
    if args.channel:
        channel_lane, channel_persona = infer_from_channel(args.channel)
        lane = lane or channel_lane
        persona = persona or channel_persona

    goals = [goal.strip() for goal in args.goal if goal.strip()]
    features = normalize_features(args)
    candidates = recommend_themes(
        lane=lane,
        persona=persona,
        article_subtype=args.article_subtype,
        goals=goals,
        features=features,
        top_k=args.top_k,
    )
    print_result(lane, persona, args.article_subtype, goals, features, candidates)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
