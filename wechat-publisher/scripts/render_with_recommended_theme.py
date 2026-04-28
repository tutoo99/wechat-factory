#!/usr/bin/env python3
"""Render Markdown to WeChat HTML using explicit or recommended theme metadata."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import yaml

import recommend_theme as rt
from render_wechat_article import DEFAULT_THEME, render_article


def load_theme_recommendation(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_output_path(input_path: Path, output_path: str | None) -> Path:
    if output_path:
        return Path(output_path)
    return input_path.with_name("article.html")


def resolve_theme(
    input_path: Path,
    theme: str | None = None,
    theme_file: Path | None = None,
    channel: str | None = None,
    lane: str | None = None,
    persona: str | None = None,
    article_subtype: str | None = None,
    goals: List[str] | None = None,
    fallback_theme: str = DEFAULT_THEME,
) -> Dict:
    if theme:
        return {
            "theme_name": theme,
            "decision_source": "explicit_theme",
            "decision_note": "显式指定 --theme",
        }

    if theme_file:
        if not theme_file.exists():
            raise FileNotFoundError(f"主题推荐文件不存在: {theme_file}")
        recommendation = load_theme_recommendation(theme_file)
        recommended_theme = (recommendation.get("recommended_theme") or "").strip()
        if recommended_theme:
            return {
                "theme_name": recommended_theme,
                "decision_source": "theme_file",
                "decision_note": str(theme_file),
                "recommendation": recommendation,
            }

    goals = goals or []
    resolved_lane = lane
    resolved_persona = persona
    if channel:
        channel_lane, channel_persona = rt.infer_from_channel(channel)
        resolved_lane = resolved_lane or channel_lane
        resolved_persona = resolved_persona or channel_persona

    if resolved_lane or resolved_persona or article_subtype or goals:
        features = rt.analyze_source(input_path)
        candidates = rt.recommend_themes(
            lane=resolved_lane,
            persona=resolved_persona,
            article_subtype=article_subtype,
            goals=goals,
            features=features,
            top_k=1,
        )
        if candidates:
            candidate = candidates[0]
            return {
                "theme_name": candidate.theme_name,
                "decision_source": "source_analysis",
                "decision_note": "根据 source 内容特征重新推荐",
                "features": features,
                "candidate_score": candidate.score,
                "candidate_reasons": candidate.reasons,
            }

    return {
        "theme_name": fallback_theme,
        "decision_source": "fallback_theme",
        "decision_note": "未提供可用推荐信息，回退默认主题",
    }


def render_with_recommended_theme(
    input_path: Path,
    output_path: str | None = None,
    theme: str | None = None,
    theme_file: Path | None = None,
    channel: str | None = None,
    lane: str | None = None,
    persona: str | None = None,
    article_subtype: str | None = None,
    goals: List[str] | None = None,
    fallback_theme: str = DEFAULT_THEME,
) -> Dict:
    decision = resolve_theme(
        input_path=input_path,
        theme=theme,
        theme_file=theme_file,
        channel=channel,
        lane=lane,
        persona=persona,
        article_subtype=article_subtype,
        goals=goals,
        fallback_theme=fallback_theme,
    )
    meta, theme_data, html, issues = render_article(input_path, decision["theme_name"])
    resolved_output = resolve_output_path(input_path, output_path)
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(html, encoding="utf-8")
    return {
        "meta": meta,
        "theme": theme_data,
        "html_path": resolved_output,
        "issues": issues,
        "decision": decision,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="优先按推荐主题把 final.md 渲染成 article.html")
    parser.add_argument("input", help="输入 Markdown 文件路径（通常为 final.md）")
    parser.add_argument("-o", "--output", default=None, help="输出 HTML 文件路径，默认与输入同目录 article.html")
    parser.add_argument("-t", "--theme", default=None, help="直接指定主题，优先级最高")
    parser.add_argument("--theme-file", default=None, help="framework_flow 产出的 *.theme.yaml 路径")
    parser.add_argument("--channel", default=None, help="channel 标识，可辅助重新推荐")
    parser.add_argument("--lane", default=None, help="显式指定赛道")
    parser.add_argument("--persona", default=None, help="显式指定 persona")
    parser.add_argument("--article-subtype", default=None, help="文章类型，如 mistake_breakdown / emotional_story")
    parser.add_argument("--goal", action="append", default=[], help="传播目标，可重复传入")
    parser.add_argument("--fallback-theme", default=DEFAULT_THEME, help=f"默认回退主题（默认: {DEFAULT_THEME}）")
    parser.add_argument("--strict-validate", action="store_true", help="若校验出现 warn 也返回非零状态码")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] 文件不存在: {input_path}", file=sys.stderr)
        return 1

    theme_file = Path(args.theme_file) if args.theme_file else None

    try:
        result = render_with_recommended_theme(
            input_path=input_path,
            output_path=args.output,
            theme=args.theme,
            theme_file=theme_file,
            channel=args.channel,
            lane=args.lane,
            persona=args.persona,
            article_subtype=args.article_subtype,
            goals=[goal.strip() for goal in args.goal if goal.strip()],
            fallback_theme=args.fallback_theme,
        )
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    title = result["meta"].get("title", "未命名文章")
    theme_name = result["decision"]["theme_name"]
    theme_display_name = result["theme"]["manifest"].get("display_name") or theme_name

    print(f"[ok] 排版完成: {result['html_path']}")
    print(f"  标题: {title}")
    print(f"  主题: {theme_display_name} ({theme_name})")
    print(f"  来源: {result['decision']['decision_source']}")
    print(f"  说明: {result['decision']['decision_note']}")

    has_error = False
    has_warn = False
    for level, message in result["issues"]:
        print(f"  [{level}] {message}")
        has_error = has_error or level == "error"
        has_warn = has_warn or level == "warn"

    if has_error or (args.strict_validate and has_warn):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
