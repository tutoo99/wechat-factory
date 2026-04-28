#!/usr/bin/env python3
"""
Schema-v1 主题包版 Markdown → 微信公众号 HTML 渲染工具。

用法：
    python3 render_wechat_article.py input.md -o output.html [-t theme_name]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from core.normalize import parse_frontmatter, strip_publish_materials
from core.qa.validate_html import validate_html
from core.renderers.wechat_html import render_markdown_to_html
from core.themes.loader import load_theme_pack


DEFAULT_THEME = "emotion-warm"


def render_article(input_path: Path, theme_name: str) -> Tuple[Dict, Dict, str, List[Tuple[str, str]]]:
    theme = load_theme_pack(theme_name)
    md_text = input_path.read_text(encoding="utf-8")
    meta, body = parse_frontmatter(md_text)
    body = strip_publish_materials(body)
    html = render_markdown_to_html(body, theme)
    issues = validate_html(html)
    return meta, theme, html, issues


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Schema-v1 主题包版 Markdown → 微信公众号HTML排版工具")
    parser.add_argument("input", help="输入 Markdown 文件路径")
    parser.add_argument("-o", "--output", required=True, help="输出 HTML 文件路径")
    parser.add_argument("-t", "--theme", default=DEFAULT_THEME, help=f"主题名称（默认: {DEFAULT_THEME}）")
    parser.add_argument("--strict-validate", action="store_true", help="若校验出现 warn 也返回非零状态码")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] 文件不存在: {input_path}", file=sys.stderr)
        return 1

    try:
        meta, theme, html, issues = render_article(input_path, args.theme)
    except FileNotFoundError as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")

    title = meta.get("title", "未命名文章")
    display_name = theme["manifest"].get("display_name") or args.theme

    print(f"[ok] 排版完成: {output_path}")
    print(f"  标题: {title}")
    print(f"  主题: {display_name}")

    has_error = False
    has_warn = False
    for level, message in issues:
        print(f"  [{level}] {message}")
        has_error = has_error or level == "error"
        has_warn = has_warn or level == "warn"

    if has_error or (args.strict_validate and has_warn):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
