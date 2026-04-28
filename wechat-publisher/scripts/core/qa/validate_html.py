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


def validate_html(html: str) -> List[Tuple[str, str]]:
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
