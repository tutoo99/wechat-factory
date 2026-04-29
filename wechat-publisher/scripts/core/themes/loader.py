#!/usr/bin/env python3
"""Load schema-v1 theme packs with backward compatibility for legacy themes."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Dict

import yaml


THEMES_DIR = Path(__file__).resolve().parents[2] / "themes"


DEFAULT_THEME = {
    "manifest": {
        "schema_version": 1,
        "id": "unknown",
        "display_name": "未命名主题",
        "description": "",
        "status": "active",
        "wechat_safe_level": "high",
        "lane_fit": [],
        "persona_fit": [],
        "article_fit": [],
        "goal_fit": [],
        "authoring_notes": [],
    },
    "tokens": {
        "colors": {
            "primary": "#E07C4F",
            "secondary": "#D4553B",
            "accent": "#F4A261",
            "text": "#3D2C2C",
            "text_secondary": "#7A6363",
            "text_muted": "#94A3B8",
            "surface": "#FFFFFF",
            "surface_soft": "#FFF8F5",
            "border": "#E2E8F0",
            "link": "#D4553B",
            "code_bg": "#FFF8F5",
            "code_inline_bg": "#FFF0EB",
            "quote_bg": "#FFF5F0",
            "highlight_bg": "#FFECD2",
            "heading_palette": ["#D4553B", "#E07C4F", "#C44536"],
            "code_text": "#E2E8F0",
            "code_label": "#A0AEC0",
            "inline_code_text": "#C0392B",
        },
        "typography": {
            "font_family": "'PingFang SC','Microsoft YaHei','Noto Sans SC',-apple-system,sans-serif",
            "body_size": 15,
            "lead_size": 18,
            "caption_size": 13,
            "code_size": 13,
            "line_height": 1.6,
            "letter_spacing": 0.5,
            "text_align": "justify",
            "text_indent": 1.6,
            "h2_size": 20,
            "h3_size": 17,
            "footnote_size": 12,
        },
        "spacing": {
            "content_padding_x": 8,
            "paragraph_gap": 18,
            "block_gap": 16,
            "section_gap_top": 32,
            "section_gap_bottom": 16,
            "sub_section_gap_top": 24,
            "sub_section_gap_bottom": 12,
            "image_gap": 20,
        },
        "radius": {"sm": 4, "md": 8, "lg": 12},
        "border": {"width_thin": 1, "width_strong": 2},
        "shadow": {"card": "none", "image": "none"},
    },
    "blocks": {
        "body_text": {"enabled": True, "variant": "default", "align": "justify", "text_indent": 1.6},
        "lead_text": {"enabled": True, "variant": "spacious", "font_size_delta": 1},
        "section_title": {
            "enabled": True,
            "variant": "underline",
            "icons": [],
            "rotate_colors": True,
        },
        "sub_title": {"enabled": True, "variant": "left-accent"},
        "quote_card": {"enabled": True, "variant": "left-bar"},
        "tip_box": {"enabled": False, "variant": "hidden"},
        "checklist": {"enabled": True, "variant": "clean-bullets"},
        "step_list": {"enabled": True, "variant": "numbered-flow"},
        "code_panel": {"enabled": True, "variant": "light-panel", "show_language_label": True},
        "data_table": {"enabled": True, "variant": "compact-grid"},
        "image_block": {"enabled": True, "variant": "rounded-caption"},
        "divider": {"enabled": True, "variant": "gradient-line"},
        "summary_box": {"enabled": False, "variant": "soft-callout"},
    },
    "heuristics": {"prefer": {}, "avoid": {}, "notes": []},
}


def deep_merge(base: Dict, override: Dict) -> Dict:
    merged = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_yaml(path: Path) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def list_available_themes() -> list[str]:
    if not THEMES_DIR.exists():
        return []
    return sorted(path.name for path in THEMES_DIR.iterdir() if path.is_dir())


def normalize_legacy_theme(theme_name: str, legacy: Dict) -> Dict:
    colors = legacy.get("colors", {})
    typography = legacy.get("typography", {})
    section_icons = legacy.get("section_icons") or []
    code_style = (legacy.get("code_style") or "").lower()

    code_variant = "light-panel"
    if code_style in {"monokai", "dark-terminal"}:
        code_variant = "dark-terminal"

    section_variant = "underline-number" if section_icons else "underline"
    quote_variant = "soft-panel" if theme_name == "tech-clean" else "warm-note"
    table_variant = "compact-grid" if theme_name == "tech-clean" else "soft-grid"

    converted = {
        "manifest": {
            "schema_version": 1,
            "id": legacy.get("name") or theme_name,
            "display_name": legacy.get("display_name") or theme_name,
            "description": legacy.get("description") or "",
            "status": "active",
            "wechat_safe_level": "high",
            "lane_fit": ["tech"] if theme_name == "tech-clean" else ["emotion"],
            "persona_fit": ["tech"] if theme_name == "tech-clean" else ["auntie"],
            "article_fit": [],
            "goal_fit": [],
            "authoring_notes": [],
        },
        "tokens": {
            "colors": {
                "primary": colors.get("primary"),
                "secondary": colors.get("secondary"),
                "accent": colors.get("accent"),
                "text": colors.get("text"),
                "text_secondary": colors.get("text_secondary"),
                "link": colors.get("link"),
                "code_bg": colors.get("bg_code"),
                "code_inline_bg": colors.get("bg_code_inline"),
                "quote_bg": colors.get("bg_blockquote"),
                "highlight_bg": colors.get("bold_highlight"),
                "heading_palette": colors.get("headings"),
            },
            "typography": {
                "body_size": typography.get("font_size"),
                "lead_size": (typography.get("font_size") or 17) + 1,
                "line_height": typography.get("line_height"),
                "letter_spacing": typography.get("letter_spacing"),
                "h2_size": 20,
                "h3_size": 17,
            },
        },
        "blocks": {
            "section_title": {
                "enabled": True,
                "variant": section_variant,
                "icons": section_icons,
                "rotate_colors": True,
            },
            "sub_title": {"enabled": True, "variant": "left-accent"},
            "quote_card": {"enabled": True, "variant": quote_variant},
            "code_panel": {"enabled": True, "variant": code_variant, "show_language_label": True},
            "data_table": {"enabled": True, "variant": table_variant},
            "image_block": {"enabled": True, "variant": "rounded-caption"},
            "divider": {"enabled": True, "variant": "gradient-line"},
        },
        "heuristics": {"prefer": {}, "avoid": {}, "notes": []},
    }
    return deep_merge(DEFAULT_THEME, converted)


def load_theme_pack(theme_name: str) -> Dict:
    theme_dir = THEMES_DIR / theme_name
    if not theme_dir.exists():
        available = ", ".join(list_available_themes())
        raise FileNotFoundError(f"主题 '{theme_name}' 未找到。可用主题: {available}")

    manifest_path = theme_dir / "manifest.yaml"
    if manifest_path.exists():
        theme_data = {
            "manifest": load_yaml(manifest_path),
            "tokens": load_yaml(theme_dir / "tokens.yaml") if (theme_dir / "tokens.yaml").exists() else {},
            "blocks": load_yaml(theme_dir / "blocks.yaml") if (theme_dir / "blocks.yaml").exists() else {},
            "heuristics": load_yaml(theme_dir / "heuristics.yaml") if (theme_dir / "heuristics.yaml").exists() else {},
        }
        normalized = deep_merge(DEFAULT_THEME, theme_data)
        normalized["manifest"]["id"] = normalized["manifest"].get("id") or theme_name
        normalized["theme_dir"] = str(theme_dir)
        return normalized

    legacy_path = theme_dir / "theme.yaml"
    if legacy_path.exists():
        legacy = load_yaml(legacy_path)
        normalized = normalize_legacy_theme(theme_name, legacy)
        normalized["theme_dir"] = str(theme_dir)
        normalized["manifest"]["legacy_source"] = str(legacy_path)
        return normalized

    raise FileNotFoundError(f"主题目录缺少配置文件: {theme_dir}")
