#!/usr/bin/env python3
"""Markdown normalization helpers for WeChat article rendering."""

from __future__ import annotations

import re
from typing import Dict, Tuple

import yaml


PUBLISH_MATERIAL_HEADINGS = {"发布素材", "标题备选", "摘要", "导语", "封面文案"}


def parse_frontmatter(text: str) -> Tuple[Dict, str]:
    """Parse YAML frontmatter and return ``(meta, body)``."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
                return meta, parts[2].strip()
            except yaml.YAMLError:
                pass
    return {}, text


def strip_publish_materials(md_text: str) -> str:
    """Strip publish-only material sections accidentally appended to正文."""
    lines = md_text.splitlines()

    def normalize_heading(line: str) -> str:
        stripped = line.strip()
        if not stripped.startswith("#"):
            return ""
        heading = re.sub(r"^#+\s*", "", stripped)
        heading = re.sub(r"\s+", "", heading)
        heading = re.sub(r"[：:]+$", "", heading)
        return heading

    found = []
    for index, line in enumerate(lines):
        heading = normalize_heading(line)
        if heading in PUBLISH_MATERIAL_HEADINGS:
            found.append((index, heading))

    if not found:
        return md_text

    start_index = None
    first_heading = found[0][1]
    distinct_found = {heading for _, heading in found}
    if first_heading == "发布素材" or len(distinct_found & (PUBLISH_MATERIAL_HEADINGS - {"发布素材"})) >= 2:
        start_index = found[0][0]

    if start_index is None:
        return md_text

    previous_index = start_index - 1
    while previous_index >= 0 and not lines[previous_index].strip():
        previous_index -= 1
    if previous_index >= 0 and lines[previous_index].strip() in {"---", "***", "___"}:
        start_index = previous_index

    return "\n".join(lines[:start_index]).rstrip() + "\n"
