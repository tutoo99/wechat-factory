#!/usr/bin/env python3
"""Block-level HTML render helpers for theme pack v1."""

from __future__ import annotations

import re
from html import escape
from typing import Dict


def css(style_map: Dict[str, object]) -> str:
    parts = []
    for key, value in style_map.items():
        if value is None or value == "":
            continue
        parts.append(f"{key}:{value};")
    return "".join(parts)


def block_config(theme: Dict, block_name: str) -> Dict:
    return ((theme.get("blocks") or {}).get(block_name) or {})


def render_paragraph(text: str, theme: Dict, is_lead: bool = False) -> str:
    body_cfg = block_config(theme, "body_text")
    lead_cfg = block_config(theme, "lead_text")
    typography = theme["tokens"]["typography"]
    spacing = theme["tokens"]["spacing"]
    colors = theme["tokens"]["colors"]

    align = body_cfg.get("align") or "justify"
    font_size = body_cfg.get("font_size") or typography.get("body_size", 17)
    line_height = body_cfg.get("line_height") or typography.get("line_height", 2.0)
    letter_spacing = body_cfg.get("letter_spacing", typography.get("letter_spacing", 0.5))
    color = colors.get("text", "#3D2C2C")
    background = None
    padding = None
    border_radius = None
    if is_lead and lead_cfg.get("enabled", True):
        lead_variant = lead_cfg.get("variant") or "spacious"
        font_size = lead_cfg.get("font_size") or typography.get("lead_size", font_size + lead_cfg.get("font_size_delta", 1))
        if lead_variant != "same-as-body":
            color = lead_cfg.get("color") or color
            line_height = lead_cfg.get("line_height") or line_height
            letter_spacing = lead_cfg.get("letter_spacing", letter_spacing)
        if lead_variant == "dark-intro":
            background = lead_cfg.get("background") or colors.get("intro_bg") or colors.get("surface_soft")
            padding = f"{lead_cfg.get('padding_y', 12)}px {lead_cfg.get('padding_x', 14)}px"
            border_radius = f"{lead_cfg.get('border_radius', 0)}px"

    style = {
        "margin": f"0 0 {spacing.get('paragraph_gap', 18)}px",
        "font-size": f"{font_size}px",
        "line-height": line_height,
        "color": color,
        "letter-spacing": f"{letter_spacing}px",
        "text-align": align,
        "font-family": typography.get("font_family"),
        "background": background,
        "padding": padding,
        "border-radius": border_radius,
    }
    return f'<p style="{css(style)}">{text}</p>\n'


def render_section_title(text: str, theme: Dict, index: int) -> str:
    cfg = block_config(theme, "section_title")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    spacing = theme["tokens"]["spacing"]
    radius = theme["tokens"]["radius"]
    border = theme["tokens"]["border"]

    palette = colors.get("heading_palette") or [
        colors.get("primary"),
        colors.get("secondary"),
        colors.get("accent"),
    ]
    color = palette[index % len(palette)]
    icon = ""
    icons = cfg.get("icons") or []
    if index < len(icons):
        icon = icons[index]

    variant = cfg.get("variant") or "underline"

    if variant in {"plain-bold", "dark-red"}:
        style = {
            "margin": f"{cfg.get('margin_top', spacing.get('section_gap_top', 32))}px 0 {cfg.get('margin_bottom', spacing.get('section_gap_bottom', 16))}px",
            "padding": 0,
            "font-size": f"{cfg.get('font_size') or typography.get('h2_size', 20)}px",
            "font-weight": cfg.get("font_weight") or typography.get("font_weight_heading") or 700,
            "color": cfg.get("color") or colors.get("text"),
            "line-height": cfg.get("line_height") or 1.45,
            "letter-spacing": f"{cfg.get('letter_spacing')}px" if cfg.get("letter_spacing") is not None else None,
            "font-family": typography.get("font_family"),
        }
        return f'<h2 style="{css(style)}">{text}</h2>\n'

    if variant == "image-number":
        match = re.match(r"^(\d{1,2})(\s+|[.、．-]+)?(.*)$", text.strip())
        number = match.group(1) if match else f"{index + 1:02d}"
        title = (match.group(3) if match else text).strip()
        wrapper_style = {
            "margin": f"{cfg.get('margin_top', spacing.get('section_gap_top', 32))}px 0 {cfg.get('margin_bottom', spacing.get('section_gap_bottom', 16))}px",
            "line-height": 1.25,
            "font-family": typography.get("font_family"),
            "color": cfg.get("color") or colors.get("text"),
        }
        number_style = {
            "display": "block",
            "font-size": f"{cfg.get('font_size') or typography.get('h2_size', 42)}px",
            "font-weight": cfg.get("font_weight") or typography.get("font_weight_heading") or 700,
            "letter-spacing": f"{typography.get('letter_spacing_tight', 0.5)}px",
        }
        title_style = {
            "display": "block",
            "margin-top": "2px",
            "font-size": f"{typography.get('h3_size', 20)}px",
            "font-weight": cfg.get("font_weight") or typography.get("font_weight_heading") or 700,
            "letter-spacing": f"{typography.get('letter_spacing_tight', 0.5)}px",
        }
        return (
            f'<h2 style="{css(wrapper_style)}">'
            f'<span style="{css(number_style)}">{number}</span>'
            f'<span style="{css(title_style)}">{title}</span></h2>\n'
        )

    if variant == "underline-number":
        style = {
            "margin": f"{spacing.get('section_gap_top', 32)}px 0 {spacing.get('section_gap_bottom', 16)}px",
            "padding": "0 0 10px",
            "font-size": f"{typography.get('h2_size', 20)}px",
            "font-weight": 700,
            "color": color,
            "border-bottom": f"{border.get('width_strong', 2)}px solid {color}",
            "line-height": 1.4,
            "font-family": typography.get("font_family"),
        }
        content = f"{icon or f'{index + 1:02d}'} {text}".strip()
        return f'<h2 style="{css(style)}">{content}</h2>\n'

    if variant == "badge-left":
        wrapper_style = {
            "margin": f"{spacing.get('section_gap_top', 32)}px 0 {spacing.get('section_gap_bottom', 16)}px",
            "font-size": f"{typography.get('h2_size', 20)}px",
            "font-weight": 700,
            "color": colors.get("text"),
            "line-height": 1.4,
            "font-family": typography.get("font_family"),
            "display": "flex",
            "align-items": "center",
            "gap": "10px",
        }
        badge_style = {
            "display": "inline-block",
            "min-width": "34px",
            "padding": "4px 8px",
            "border-radius": f"{radius.get('md', 8)}px",
            "background": color,
            "color": "#ffffff",
            "font-size": "13px",
            "text-align": "center",
            "font-weight": 700,
        }
        badge = icon or f"{index + 1:02d}"
        return (
            f'<h2 style="{css(wrapper_style)}">'
            f'<span style="{css(badge_style)}">{badge}</span>'
            f"<span>{text}</span></h2>\n"
        )

    if variant == "badge-left-light":
        wrapper_style = {
            "margin": f"{spacing.get('section_gap_top', 32)}px 0 {spacing.get('section_gap_bottom', 16)}px",
            "font-size": f"{typography.get('h2_size', 20)}px",
            "font-weight": 700,
            "color": colors.get("text"),
            "line-height": 1.4,
            "font-family": typography.get("font_family"),
            "display": "flex",
            "align-items": "baseline",
            "gap": "10px",
        }
        badge_style = {
            "display": "inline-block",
            "min-width": "28px",
            "padding": "1px 6px",
            "border-radius": f"{radius.get('lg', 12)}px",
            "background": colors.get("surface_soft"),
            "border": f"1px solid {color}33",
            "color": color,
            "font-size": "11px",
            "line-height": 1.5,
            "text-align": "center",
            "font-weight": 600,
            "letter-spacing": "0.4px",
        }
        title_style = {
            "display": "inline-block",
            "border-bottom": f"1px solid {color}22",
            "padding-bottom": "2px",
        }
        badge = icon or f"{index + 1:02d}"
        return (
            f'<h2 style="{css(wrapper_style)}">'
            f'<span style="{css(badge_style)}">{badge}</span>'
            f'<span style="{css(title_style)}">{text}</span></h2>\n'
        )

    if variant == "soft-band":
        style = {
            "margin": f"{spacing.get('section_gap_top', 32)}px 0 {spacing.get('section_gap_bottom', 16)}px",
            "padding": "10px 14px",
            "font-size": f"{typography.get('h2_size', 20)}px",
            "font-weight": 700,
            "color": color,
            "background": colors.get("surface_soft"),
            "border-radius": f"{radius.get('md', 8)}px",
            "line-height": 1.4,
            "font-family": typography.get("font_family"),
        }
        return f'<h2 style="{css(style)}">{text}</h2>\n'

    style = {
        "margin": f"{spacing.get('section_gap_top', 32)}px 0 {spacing.get('section_gap_bottom', 16)}px",
        "padding": "0 0 10px",
        "font-size": f"{typography.get('h2_size', 20)}px",
        "font-weight": 700,
        "color": color,
        "border-bottom": f"{border.get('width_strong', 2)}px solid {color}",
        "line-height": 1.4,
        "font-family": typography.get("font_family"),
    }
    return f'<h2 style="{css(style)}">{text}</h2>\n'


def render_sub_title(text: str, theme: Dict) -> str:
    cfg = block_config(theme, "sub_title")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    spacing = theme["tokens"]["spacing"]
    border = theme["tokens"]["border"]

    variant = cfg.get("variant") or "left-accent"
    if variant in {"plain-bold", "bold-upsize", "black-bold", "bold-inline"}:
        style = {
            "margin": f"{spacing.get('sub_section_gap_top', 24)}px 0 {spacing.get('sub_section_gap_bottom', 12)}px",
            "font-size": f"{cfg.get('font_size') or typography.get('h3_size', 17)}px",
            "font-weight": cfg.get("font_weight") or 700,
            "color": cfg.get("color") or colors.get("text"),
            "line-height": cfg.get("line_height") or 1.45,
            "letter-spacing": f"{cfg.get('letter_spacing')}px" if cfg.get("letter_spacing") is not None else None,
            "font-family": typography.get("font_family"),
        }
        return f'<h3 style="{css(style)}">{text}</h3>\n'

    if variant == "pink-highlight":
        wrapper_style = {
            "margin": f"{spacing.get('sub_section_gap_top', 24)}px 0 {spacing.get('sub_section_gap_bottom', 12)}px",
            "font-size": f"{cfg.get('font_size') or typography.get('h3_size', 18)}px",
            "font-weight": cfg.get("font_weight") or 700,
            "color": cfg.get("color") or colors.get("text"),
            "line-height": cfg.get("line_height") or 1.55,
            "font-family": typography.get("font_family"),
        }
        mark_style = {
            "background": cfg.get("background") or colors.get("highlight_bg"),
            "padding": "0 4px",
            "box-decoration-break": "clone",
            "-webkit-box-decoration-break": "clone",
        }
        return f'<h3 style="{css(wrapper_style)}"><span style="{css(mark_style)}">{text}</span></h3>\n'

    style = {
        "margin": f"{spacing.get('sub_section_gap_top', 24)}px 0 {spacing.get('sub_section_gap_bottom', 12)}px",
        "font-size": f"{typography.get('h3_size', 17)}px",
        "font-weight": 600,
        "color": colors.get("text"),
        "line-height": 1.4,
        "border-left": f"{border.get('width_strong', 2) + 2}px solid {colors.get('primary')}",
        "padding-left": "12px",
        "font-family": typography.get("font_family"),
    }
    return f'<h3 style="{css(style)}">{text}</h3>\n'


def render_quote_card(text: str, theme: Dict) -> str:
    cfg = block_config(theme, "quote_card")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    radius = theme["tokens"]["radius"]
    variant = cfg.get("variant") or "left-bar"

    if cfg.get("enabled") is False or variant == "none":
        return text

    base_style = {
        "margin": "16px 0",
        "color": colors.get("text_secondary"),
        "font-size": f"{typography.get('body_size', 17) - 1}px",
        "line-height": typography.get("line_height", 2.0),
        "font-family": typography.get("font_family"),
    }

    if variant == "soft-panel":
        style = {
            **base_style,
            "padding": "16px 18px",
            "background": colors.get("surface_soft"),
            "border-radius": f"{radius.get('md', 8)}px",
            "border": f"1px solid {colors.get('border')}",
        }
        return f'<blockquote style="{css(style)}">{text}</blockquote>\n'

    if variant == "warm-note":
        style = {
            **base_style,
            "padding": "16px 18px",
            "background": colors.get("quote_bg"),
            "border-radius": f"{radius.get('md', 8)}px",
            "border-left": f"4px solid {colors.get('accent')}",
        }
        return f'<blockquote style="{css(style)}">{text}</blockquote>\n'

    if variant == "shadow-float":
        style = {
            **base_style,
            "margin": cfg.get("margin") or "16px 0",
            "padding": cfg.get("padding") or "18px",
            "background": colors.get("quote_bg"),
            "box-shadow": cfg.get("box_shadow") or theme["tokens"].get("shadow", {}).get("card"),
            "border-radius": f"{cfg.get('border_radius', radius.get('md', 8))}px",
        }
        return f'<blockquote style="{css(style)}">{text}</blockquote>\n'

    if variant == "left-indent":
        style = {
            **base_style,
            "padding": f"0 0 0 {cfg.get('padding_left', 10)}px",
            "color": cfg.get("color") or colors.get("text"),
            "border-left": f"2px solid {colors.get('border')}",
            "background": "transparent",
        }
        return f'<blockquote style="{css(style)}">{text}</blockquote>\n'

    style = {
        **base_style,
        "padding": "16px 20px",
        "background": colors.get("quote_bg"),
        "border-left": f"4px solid {colors.get('primary')}",
        "border-radius": f"0 {radius.get('md', 8)}px {radius.get('md', 8)}px 0",
    }
    return f'<blockquote style="{css(style)}">{text}</blockquote>\n'


def render_inline_code(text: str, theme: Dict) -> str:
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    radius = theme["tokens"]["radius"]
    style = {
        "background": colors.get("code_inline_bg"),
        "color": colors.get("inline_code_text"),
        "padding": "2px 6px",
        "border-radius": f"{radius.get('sm', 4)}px",
        "font-size": f"{typography.get('code_size', 13)}px",
        "font-family": "'SF Mono',Menlo,monospace",
    }
    return f'<code style="{css(style)}">{text}</code>'


def render_strong_text(text: str, theme: Dict) -> str:
    cfg = block_config(theme, "accent_text")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    variant = cfg.get("variant") or "highlight"

    if cfg.get("enabled") and variant in {"red-bold", "orange-highlight", "gray-italic"}:
        color_key = "orange_accent" if variant == "orange-highlight" else "red_accent"
        style = {
            "font-weight": cfg.get("font_weight") or 700,
            "color": cfg.get("color") or colors.get(color_key) or colors.get("accent"),
            "font-size": f"{cfg.get('font_size') or typography.get('body_size', 17)}px",
            "letter-spacing": f"{cfg.get('letter_spacing') or typography.get('letter_spacing_accent') or typography.get('letter_spacing', 0)}px",
            "font-style": "italic" if variant == "gray-italic" else None,
        }
        return f'<strong style="{css(style)}">{text}</strong>'

    style = {
        "font-weight": 700,
        "color": colors.get("text"),
        "background": f"linear-gradient(transparent 60%,{colors.get('highlight_bg')} 60%)",
    }
    return f'<strong style="{css(style)}">{text}</strong>'


def render_code_panel(code: str, info: str | None, theme: Dict) -> str:
    cfg = block_config(theme, "code_panel")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    radius = theme["tokens"]["radius"]
    variant = cfg.get("variant") or "light-panel"
    show_label = cfg.get("show_language_label", True)

    lang = info.split()[0] if info else ""
    label = lang.upper() if lang else "CODE"
    normalized_code = code.rstrip("\n").replace("\t", "    ")

    if cfg.get("enabled") is False or variant == "none":
        typography = theme["tokens"]["typography"]
        colors = theme["tokens"]["colors"]
        pre_style = {
            "margin": "14px 0",
            "font-size": f"{typography.get('code_size', 13)}px",
            "line-height": 1.65,
            "color": colors.get("text"),
            "white-space": "pre-wrap",
            "word-break": "break-word",
            "font-family": "'SF Mono',Menlo,monospace",
        }
        return f'<pre style="{css(pre_style)}"><code>{escape(normalized_code)}</code></pre>\n'

    label_html = ""
    if show_label:
        label_style = {
            "background": colors.get("code_bg") if variant == "dark-terminal" else colors.get("surface_soft"),
            "padding": "8px 14px",
            "font-size": "11px",
            "color": colors.get("code_label"),
            "font-family": "'SF Mono',Menlo,monospace",
            "letter-spacing": "1px",
        }
        if variant == "wechat-card":
            pill_style = {
                "display": "inline-block",
                "padding": "2px 8px",
                "border-radius": f"{radius.get('lg', 12)}px",
                "background": colors.get("surface"),
                "border": f"1px solid {colors.get('border')}",
                "font-size": "10px",
                "line-height": 1.4,
                "color": colors.get("code_label"),
                "font-family": "'SF Mono',Menlo,monospace",
                "letter-spacing": "0.6px",
            }
            label_style = {
                "padding": "10px 12px 0",
                "background": colors.get("surface_soft"),
            }
            label_html = f'<div style="{css(label_style)}"><span style="{css(pill_style)}">{label}</span></div>'
        else:
            if variant != "dark-terminal":
                label_style["border-bottom"] = f"1px solid {colors.get('border')}"
            label_html = f'<div style="{css(label_style)}">{label}</div>'

    wrapper_style = {
        "margin": "16px 0",
        "border-radius": f"{radius.get('md', 8)}px",
        "overflow": "hidden",
    }
    body_style = {
        "margin": 0,
        "padding": "12px 14px 16px",
        "overflow-x": "auto",
        "overflow-y": "hidden",
    }
    code_style = {
        "display": "block",
        "margin": 0,
        "font-size": f"{typography.get('code_size', 13)}px",
        "line-height": 1.6,
        "font-family": "'SF Mono',Menlo,monospace",
        "white-space": "normal",
        "word-break": "normal",
        "overflow-wrap": "normal",
    }
    if variant == "dark-terminal":
        body_style.update(
            {
                "background": colors.get("code_bg"),
                "color": colors.get("code_text"),
            }
        )
        code_style["color"] = colors.get("code_text")
    elif variant == "wechat-card":
        wrapper_style.update(
            {
                "border": f"1px solid {colors.get('border')}",
                "background": colors.get("surface_soft"),
            }
        )
        body_style.update(
            {
                "padding": "8px 12px 12px",
                "background": colors.get("surface_soft"),
                "color": colors.get("text"),
            }
        )
        code_style.update(
            {
                "font-size": f"{max(12, typography.get('code_size', 13))}px",
                "line-height": 1.55,
                "color": colors.get("text"),
            }
        )
    else:
        body_style.update(
            {
                "background": colors.get("surface_soft"),
                "color": colors.get("text"),
                "border": f"1px solid {colors.get('border')}",
                "border-top": "none" if label_html else f"1px solid {colors.get('border')}",
            }
        )
        code_style["color"] = colors.get("text")

    rendered_lines = []
    for line in normalized_code.split("\n"):
        safe_line = escape(line).replace(" ", "&nbsp;")
        rendered_lines.append(safe_line or "&nbsp;")
    code_html = "<br/>".join(rendered_lines)
    return (
        f'<section style="{css(wrapper_style)}">{label_html}'
        f'<div style="{css(body_style)}"><code style="{css(code_style)}">{code_html}</code></div>'
        f"</section>\n"
    )


def render_divider(theme: Dict) -> str:
    cfg = block_config(theme, "divider")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    variant = cfg.get("variant") or "gradient-line"
    if cfg.get("enabled") is False or variant == "none":
        return ""
    if variant == "thin-line":
        margin_top = cfg.get("margin_top", 28)
        margin_bottom = cfg.get("margin_bottom", 0 if "margin_bottom" in cfg else 28)
        style = {
            "border": "none",
            "height": f"{cfg.get('border_width', 1)}px",
            "background": cfg.get("border_color") or colors.get("border"),
            "margin": f"{margin_top}px 0 {margin_bottom}px",
        }
        return f'<hr style="{css(style)}" />\n'
    if variant == "spaced-dots":
        dots_style = {
            "margin": "28px 0",
            "text-align": "center",
            "color": colors.get("text_secondary"),
            "letter-spacing": "6px",
        }
        return f'<div style="{css(dots_style)}">• • •</div>\n'
    if variant == "colored-dots":
        dots = []
        for color in cfg.get("dot_colors") or [colors.get("accent"), colors.get("primary"), colors.get("secondary")]:
            dot_style = {
                "display": "inline-block",
                "width": f"{cfg.get('dot_size', 8)}px",
                "height": f"{cfg.get('dot_size', 8)}px",
                "border-radius": cfg.get("dot_radius") or "50%",
                "background": color,
                "margin": "0 5px",
                "vertical-align": "middle",
            }
            dots.append(f'<span style="{css(dot_style)}"></span>')
        wrapper_style = {"margin": "24px 0", "text-align": "center", "line-height": 1}
        return f'<div style="{css(wrapper_style)}">{"".join(dots)}</div>\n'
    if variant == "end-mark":
        style = {
            "margin": "28px 0",
            "text-align": "center",
            "font-family": cfg.get("font_family") or typography.get("end_mark_font") or typography.get("font_family"),
            "font-size": f"{cfg.get('font_size') or typography.get('end_mark_size', 16)}px",
            "color": colors.get("text_secondary"),
            "font-style": "italic",
            "letter-spacing": f"{typography.get('letter_spacing_meta', 0.5)}px",
        }
        return f'<div style="{css(style)}">{cfg.get("text") or "- End -"}</div>\n'
    style = {
        "border": "none",
        "height": "1px",
        "background": f"linear-gradient(to right,transparent,{colors.get('primary')},transparent)",
        "margin": "28px 0",
    }
    return f'<hr style="{css(style)}" />\n'


def render_list(text: str, ordered: bool, theme: Dict) -> str:
    typography = theme["tokens"]["typography"]
    block_name = "step_list" if ordered else "checklist"
    cfg = block_config(theme, block_name)
    divider_cfg = block_config(theme, "divider")
    plain_text = re.sub(r"<[^>]+>", "", text).strip()
    if not ordered and divider_cfg.get("variant") == "end-mark" and plain_text in {"End -", "- End -"}:
        return render_divider(theme)
    style = {
        "margin": "12px 0",
        "padding-left": "24px",
        "font-family": typography.get("font_family"),
        "list-style-position": "outside",
        "list-style-type": "decimal" if ordered else "disc",
    }
    if not ordered and cfg.get("variant") not in {"clean-bullets", None, ""}:
        style["list-style-type"] = "circle"
    if cfg.get("variant") == "plain-list":
        style["list-style-type"] = "disc"
    tag = "ol" if ordered else "ul"
    return f'<{tag} style="{css(style)}">{text}</{tag}>\n'


def render_list_item(text: str, theme: Dict) -> str:
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    style = {
        "margin": "6px 0",
        "color": colors.get("text"),
        "font-size": f"{typography.get('body_size', 17)}px",
        "line-height": typography.get("line_height", 2.0),
        "padding-left": "4px",
    }
    return f'<li style="{css(style)}">{text}</li>'


def render_table(text: str, theme: Dict) -> str:
    typography = theme["tokens"]["typography"]
    style = {
        "width": "100%",
        "border-collapse": "collapse",
        "margin": "16px 0",
        "font-family": typography.get("font_family"),
    }
    cfg = block_config(theme, "data_table")
    if cfg.get("enabled") is False or cfg.get("variant") == "none":
        style["border-collapse"] = "separate"
    return f'<table style="{css(style)}">{text}</table>\n'


def render_table_head(text: str, theme: Dict) -> str:
    colors = theme["tokens"]["colors"]
    return f'<thead style="{css({"background": colors.get("quote_bg")})}">{text}</thead>'


def render_table_body(text: str) -> str:
    return f"<tbody>{text}</tbody>"


def render_table_row(text: str, theme: Dict) -> str:
    colors = theme["tokens"]["colors"]
    style = {"border-bottom": f"1px solid {colors.get('border')}"}
    return f'<tr style="{css(style)}">{text}</tr>'


def render_table_cell(text: str, align: str | None, head: bool, theme: Dict) -> str:
    cfg = block_config(theme, "data_table")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    variant = cfg.get("variant") or "compact-grid"
    tag = "th" if head else "td"
    style = {
        "padding": "10px 12px",
        "font-size": f"{typography.get('body_size', 17) - 1}px",
        "color": colors.get("text"),
        "border": None if cfg.get("enabled") is False or variant == "none" else f"1px solid {colors.get('border')}",
    }
    if head:
        style["font-weight"] = 700
        style["background"] = colors.get("quote_bg") if variant == "compact-grid" else colors.get("surface_soft")
    if align:
        style["text-align"] = align
    return f'<{tag} style="{css(style)}">{text}</{tag}>'


def render_image(text: str, url: str, theme: Dict) -> str:
    cfg = block_config(theme, "image_block")
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    spacing = theme["tokens"]["spacing"]
    radius = theme["tokens"]["radius"]
    shadow = theme["tokens"]["shadow"]
    variant = cfg.get("variant") or "rounded-caption"

    image_style = {"max-width": "100%", "width": cfg.get("width")}
    if variant not in {"plain", "fullwidth-raw", "float-wrap"}:
        image_style["border-radius"] = f"{cfg.get('border_radius', radius.get('md', 8))}px"
    elif cfg.get("border_radius") is not None:
        image_style["border-radius"] = f"{cfg.get('border_radius')}px"
    if variant == "shadow-card":
        image_style["box-shadow"] = shadow.get("image")

    caption_html = ""
    if text:
        caption_style = {
            "font-size": f"{typography.get('caption_size', 13)}px",
            "color": colors.get("text_secondary"),
            "margin-top": "6px",
        }
        caption_html = f'<figcaption style="{css(caption_style)}">{text}</figcaption>'

    figure_style = {
        "margin": f"{spacing.get('image_gap', 20)}px 0",
        "text-align": "center",
    }
    return (
        f'<figure style="{css(figure_style)}">'
        f'<img src="{url}" alt="{text}" style="{css(image_style)}" />'
        f"{caption_html}</figure>\n"
    )
