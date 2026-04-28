#!/usr/bin/env python3
"""WeChat-safe HTML renderer backed by theme pack v1."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

import mistune
from mistune.plugins.table import table as table_plugin
from mistune.renderers.html import HTMLRenderer

from core.renderers.blocks import (
    render_code_panel,
    render_divider,
    render_image,
    render_inline_code,
    render_list,
    render_list_item,
    render_paragraph,
    render_quote_card,
    render_section_title,
    render_strong_text,
    render_sub_title,
    render_table,
    render_table_body,
    render_table_cell,
    render_table_head,
    render_table_row,
)


def render_markdown_to_html(md_text: str, theme: Dict) -> str:
    colors = theme["tokens"]["colors"]
    typography = theme["tokens"]["typography"]
    spacing = theme["tokens"]["spacing"]

    section_counter = [0]
    paragraph_counter = [0]
    seen_heading = [False]
    footnotes: List[Tuple[int, str, str]] = []
    footnote_index = [0]

    class StyledRenderer(HTMLRenderer):

        def text(self, text: str) -> str:
            return text

        def emphasis(self, text: str) -> str:
            return f'<em style="font-style:italic;color:{colors.get("text_secondary")};">{text}</em>'

        def strong(self, text: str) -> str:
            return render_strong_text(text, theme)

        def link(self, text: str, url: str, title=None) -> str:
            if url.startswith("http"):
                footnote_index[0] += 1
                index = footnote_index[0]
                footnotes.append((index, text, url))
                return (
                    f"{text}"
                    f'<sup style="font-size:10px;color:{colors.get("link")};vertical-align:super;">[{index}]</sup>'
                )
            return f'<a style="color:{colors.get("link")};text-decoration:none;" href="{url}">{text}</a>'

        def image(self, text: str, url: str, title=None) -> str:
            return render_image(text, url, theme)

        def codespan(self, text: str) -> str:
            return render_inline_code(text, theme)

        def paragraph(self, text: str) -> str:
            if text.strip().startswith("<figure"):
                return text
            is_lead = paragraph_counter[0] == 0 and not seen_heading[0]
            paragraph_counter[0] += 1
            return render_paragraph(text, theme, is_lead=is_lead)

        def heading(self, text: str, level: int, **attrs) -> str:
            if level == 1:
                return ""
            seen_heading[0] = True
            if level == 2:
                output = render_section_title(text, theme, section_counter[0])
                section_counter[0] += 1
                return output
            if level == 3:
                return render_sub_title(text, theme)
            size = max(14, typography.get("h3_size", 17) - max(level - 3, 0))
            return (
                f'<h{level} style="margin:20px 0 10px;font-size:{size}px;'
                f'font-weight:600;color:{colors.get("text")};font-family:{typography.get("font_family")};">'
                f"{text}</h{level}>\n"
            )

        def block_code(self, code: str, info=None, **attrs) -> str:
            return render_code_panel(code, info, theme)

        def block_quote(self, text: str) -> str:
            return render_quote_card(text, theme)

        def list(self, text: str, ordered: bool, **attrs) -> str:
            return render_list(text, ordered, theme)

        def list_item(self, text: str) -> str:
            text = re.sub(r"^\s*<p[^>]*>", "", text)
            text = re.sub(r"</p>\s*$", "", text)
            text = re.sub(r"</p>\s*<p[^>]*>", "<br />", text)
            return render_list_item(text, theme)

        def hr(self) -> str:
            return render_divider(theme)

        def thematic_break(self) -> str:
            return render_divider(theme)

        def table(self, text: str) -> str:
            return render_table(text, theme)

        def table_head(self, text: str) -> str:
            return render_table_head(text, theme)

        def table_body(self, text: str) -> str:
            return render_table_body(text)

        def table_row(self, text: str) -> str:
            return render_table_row(text, theme)

        def table_cell(self, text: str, align=None, head=False, **attrs) -> str:
            return render_table_cell(text, align, head, theme)

    markdown = mistune.create_markdown(
        renderer=StyledRenderer(),
        plugins=[table_plugin, "footnotes", "strikethrough", "mark"],
    )
    body_html = markdown(md_text)

    footnote_html = ""
    if footnotes:
        lines = []
        for index, text, url in footnotes:
            lines.append(
                f'<p style="font-size:{typography.get("footnote_size", 12)}px;color:{colors.get("text_secondary")};'
                f'margin:4px 0;word-break:break-all;font-family:{typography.get("font_family")};">'
                f'[{index}] {text}: <span style="color:{colors.get("link")};">{url}</span></p>'
            )
        footnote_html = (
            f'<section style="margin-top:24px;padding-top:16px;border-top:1px solid {colors.get("border")};">'
            + "".join(lines)
            + "</section>"
        )

    return (
        f'<section style="padding:{spacing.get("content_padding_x", 8)}px;">'
        f"{body_html}{footnote_html}</section>"
    )
