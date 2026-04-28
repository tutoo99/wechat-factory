#!/usr/bin/env python3
"""Render and validate preview.md for all schema-v1 themes."""

from __future__ import annotations

import argparse
from pathlib import Path

from core.themes.loader import list_available_themes, load_theme_pack
from render_wechat_article import render_article


SCRIPT_DIR = Path(__file__).resolve().parent
THEMES_DIR = SCRIPT_DIR / "themes"


def main() -> int:
    parser = argparse.ArgumentParser(description="批量渲染所有主题的 preview.md")
    parser.add_argument(
        "-o",
        "--output-dir",
        default=str(SCRIPT_DIR.parent / "work" / "theme-previews"),
        help="输出目录",
    )
    parser.add_argument("--strict-validate", action="store_true", help="出现 warn 也返回非零状态码")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    has_error = False
    has_warn = False

    for theme_name in list_available_themes():
        theme_dir = THEMES_DIR / theme_name
        preview_path = theme_dir / "preview.md"
        if not preview_path.exists():
            print(f"[skip] {theme_name}: 缺少 preview.md")
            continue

        theme = load_theme_pack(theme_name)
        _, _, html, issues = render_article(preview_path, theme_name)
        output_path = output_dir / f"{theme_name}.html"
        output_path.write_text(html, encoding="utf-8")

        print(f"[ok] {theme_name} -> {output_path}")
        print(f"  主题: {theme['manifest'].get('display_name')}")
        for level, message in issues:
            print(f"  [{level}] {message}")
            has_error = has_error or level == "error"
            has_warn = has_warn or level == "warn"

    if has_error or (args.strict_validate and has_warn):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
