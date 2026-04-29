#!/usr/bin/env python3
"""Lightweight validation for generated WeChat-safe HTML."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple


DISALLOWED_TAGS = ("script", "style", "iframe", "object", "embed", "form")
DISALLOWED_PATTERNS = {
    "javascript_url": re.compile(r"javascript:", re.IGNORECASE),
    "fixed_position": re.compile(r"position\s*:\s*fixed", re.IGNORECASE),
    "external_stylesheet": re.compile(r"<link\b", re.IGNORECASE),
}


def _extract_paragraph_styles(html: str) -> List[str]:
    return re.findall(r"<p\b[^>]*\bstyle=\"([^\"]*)\"", html, re.IGNORECASE)


def _theme_body_size(theme) -> int | None:
    if not theme:
        return None
    tokens = theme.get("tokens") or {}
    typography = tokens.get("typography") or {}
    blocks = theme.get("blocks") or {}
    body_text = blocks.get("body_text") or {}
    size = body_text.get("font_size") or typography.get("body_size")
    return int(size) if size is not None else None


def _has_style_value(styles: List[str], name: str, expected: str) -> bool:
    pattern = re.compile(rf"{re.escape(name)}\s*:\s*{re.escape(expected)}\s*;", re.IGNORECASE)
    return any(pattern.search(style) for style in styles)


def validate_html(html: str, theme=None) -> List[Tuple[str, str]]:
    issues: List[Tuple[str, str]] = []
    for tag in DISALLOWED_TAGS:
        if re.search(rf"<{tag}\b", html, re.IGNORECASE):
            issues.append(("error", f"发现不允许的标签 `<{tag}>`"))
    for key, pattern in DISALLOWED_PATTERNS.items():
        if pattern.search(html):
            level = "error" if key != "fixed_position" else "warn"
            issues.append((level, f"发现潜在不兼容内容: {key}"))
    if "<section" not in html:
        issues.append(("warn", "输出缺少顶层 `<section>` 包裹"))
    if "style=" not in html:
        issues.append(("warn", "输出中没有内联样式，可能不是预期的公众号 HTML"))
    paragraph_styles = _extract_paragraph_styles(html)
    if paragraph_styles:
        if not _has_style_value(paragraph_styles, "text-align", "justify"):
            issues.append(("warn", "正文段落缺少 `text-align:justify`"))
        if not _has_style_value(paragraph_styles, "text-indent", "1.6em"):
            issues.append(("warn", "正文段落缺少 `text-indent:1.6em`"))
        body_size = _theme_body_size(theme)
        if body_size is not None and not _has_style_value(paragraph_styles, "font-size", f"{body_size}px"):
            issues.append(("warn", f"正文段落未见主题正文字号 `{body_size}px`"))
        manifest = (theme or {}).get("manifest") or {}
        is_senior_theme = "auntie" in (manifest.get("persona_fit") or [])
        if body_size is not None and is_senior_theme and body_size < 17:
            issues.append(("warn", "中老年读者主题正文建议使用 `17px`"))
        if body_size is not None and body_size >= 17 and not _has_style_value(paragraph_styles, "font-size", "17px"):
            issues.append(("warn", "中老年读者主题正文建议使用 `17px`"))
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="校验生成的公众号 HTML")
    parser.add_argument("input", help="HTML 文件路径")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"[error] 文件不存在: {input_path}", file=sys.stderr)
        return 1

    html = input_path.read_text(encoding="utf-8")
    issues = validate_html(html)
    if not issues:
        print(f"[ok] 通过校验: {input_path}")
        return 0

    has_error = False
    for level, message in issues:
        print(f"[{level}] {message}")
        if level == "error":
            has_error = True
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
