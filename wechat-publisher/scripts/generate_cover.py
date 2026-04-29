#!/usr/bin/env python3
"""
微信公众号封面图生成脚本

用法:
    python3 generate_cover.py article.md -o cover.jpg [-s style] [-c colors_json]

样式:
    accent-bar     深墨绿背景 + 红色强调条（技术号默认）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys

from PIL import Image, ImageDraw, ImageFont

# ── 常量 ──────────────────────────────────────────────────────────────────────
WIDTH, HEIGHT = 900, 383  # 2.35:1

STYLE_SIZE_OFFSET = {
    "accent-bar": 6,
}

# 字体搜索路径（macOS / Linux / Windows）
FONT_CANDIDATES = [
    # Noto Sans SC
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/google-noto-cjk/NotoSansCJKsc-Regular.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/local/share/fonts/NotoSansSC-Regular.otf",
    os.path.expanduser("~/Library/Fonts/NotoSansSC-Regular.otf"),
    # PingFang SC (macOS)
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    os.path.expanduser("~/Library/Fonts/PingFang.ttc"),
    # Microsoft YaHei (Windows / WSL)
    "/mnt/c/Windows/Fonts/msyh.ttc",
    "C:\\Windows\\Fonts\\msyh.ttc",
    "/usr/share/fonts/truetype/msttcorefonts/msyh.ttf",
]


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def find_chinese_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """尝试加载中文字体，找不到则 fallback 到默认字体。"""
    for path in FONT_CANDIDATES:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    # fallback
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def lerp_color(c1: tuple, c2: tuple, t: float) -> tuple:
    return tuple(int(a + (b - a) * t) for a, b in zip(c1, c2))


def make_gradient_fast(w: int, h: int, colors: list[tuple]) -> Image.Image:
    """逐行绘制渐变，比逐像素快很多。"""
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    n = len(colors)
    for y in range(h):
        t = y / max(h - 1, 1)
        seg = t * (n - 1)
        idx = min(int(seg), n - 2)
        local_t = seg - idx
        c = lerp_color(colors[idx], colors[idx + 1], local_t)
        draw.line([(0, y), (w, y)], fill=c)
    return img


def base_font_size(title_len: int) -> int:
    """根据标题字符数返回基准字号。"""
    if title_len <= 10:
        return 36
    elif title_len <= 16:
        return 32
    elif title_len <= 24:
        return 28
    elif title_len <= 32:
        return 24
    else:
        return 20


def wrap_title(title: str, font: ImageFont.ImageFont, max_width: int) -> list[str]:
    """自动换行：按字符逐个尝试，超出宽度则换行。"""
    lines: list[str] = []
    current = ""
    for ch in title:
        test = current + ch
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > max_width and current:
            lines.append(current)
            current = ch
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def draw_wrapped_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    fill,
    x: float,
    y: float,
    max_width: int,
    line_spacing: int = 8,
    anchor: str = "mm",
) -> float:
    """绘制自动换行文字，返回总高度。"""
    lines = wrap_title(text, font, max_width)
    total_h = len(lines) * (font.size + line_spacing) - line_spacing
    start_y = y - total_h / 2
    for i, line in enumerate(lines):
        ly = start_y + i * (font.size + line_spacing) + font.size / 2
        draw.text((x, ly), line, font=font, fill=fill, anchor="mm")
    return total_h


# ── 解析 frontmatter ─────────────────────────────────────────────────────────

def parse_frontmatter(md_path: str) -> dict:
    """从 Markdown 文件中解析 YAML frontmatter。"""
    with open(md_path, "r", encoding="utf-8") as f:
        content = f.read()

    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not m:
        return {}

    meta: dict = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip().strip("\"'")
        if val:
            meta[key] = val
    return meta


# ── 样式绘制 ──────────────────────────────────────────────────────────────────

def draw_accent_bar(
    draw: ImageDraw.ImageDraw,
    title: str,
    subtitle: str | None,
    category: str | None,
    custom_colors: dict | None,
) -> None:
    """深墨绿 + 红色强调条。"""
    sz = base_font_size(len(title)) + STYLE_SIZE_OFFSET["accent-bar"]
    title_font = find_chinese_font(sz)
    sub_font = find_chinese_font(18)

    title_max_w = WIDTH - 120
    title_x = WIDTH / 2
    title_y = HEIGHT / 2 - (20 if subtitle else 0)
    th = draw_wrapped_text(
        draw, title, title_font, fill=(255, 255, 255), x=title_x, y=title_y,
        max_width=title_max_w,
    )

    # 红色强调条
    bar_w = int(WIDTH * 0.55)
    bar_h = 8
    bar_x = (WIDTH - bar_w) / 2
    bar_y = title_y + th / 2 + 10
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
        radius=4,
        fill=hex_to_rgb("#E53E3E"),
    )

    # 副标题
    if subtitle:
        draw.text(
            (title_x, bar_y + bar_h + 22),
            subtitle,
            font=sub_font,
            fill=(255, 255, 255, 180),
            anchor="mm",
        )

# ── 样式映射 ──────────────────────────────────────────────────────────────────

STYLE_RENDERERS = {
    "accent-bar": draw_accent_bar,
}

STYLE_DEFAULT_GRADIENTS = {
    "accent-bar": ["#243530", "#2d4a3e"],
}


# ── 主流程 ────────────────────────────────────────────────────────────────────

def generate_cover(
    md_path: str,
    output_path: str,
    style: str = "accent-bar",
    colors_json: str | None = None,
) -> str:
    """生成封面图并保存，返回输出文件路径。"""

    if style not in STYLE_RENDERERS:
        print(f"[warn] 未知样式 '{style}'，使用 accent-bar", file=sys.stderr)
        style = "accent-bar"

    # 解析 frontmatter
    meta = parse_frontmatter(md_path)
    title = meta.get("title", "")
    subtitle = meta.get("subtitle")
    category = meta.get("category")

    if not title:
        print("[error] frontmatter 中未找到 title", file=sys.stderr)
        sys.exit(1)

    # 加载自定义颜色
    custom_colors = None
    if colors_json:
        try:
            with open(colors_json, "r", encoding="utf-8") as f:
                custom_colors = json.load(f)
        except Exception as e:
            print(f"[warn] 无法读取颜色配置: {e}", file=sys.stderr)

    # 绘制背景渐变
    grad_hex = STYLE_DEFAULT_GRADIENTS[style]
    if custom_colors and "gradient" in custom_colors:
        grad_hex = custom_colors["gradient"]
    grad_rgb = [hex_to_rgb(c) for c in grad_hex]

    img = make_gradient_fast(WIDTH, HEIGHT, grad_rgb)

    draw = ImageDraw.Draw(img)

    # 调用对应样式的绘制函数
    renderer = STYLE_RENDERERS[style]
    renderer(draw, title, subtitle, category, custom_colors)

    # 保存
    if img.mode == "RGBA":
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg

    out = output_path or "cover.jpg"
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, "JPEG", quality=95)
    print(f"[ok] 封面已生成: {out}")
    return out


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="微信公众号封面图生成器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("article", help="Markdown 文件路径（含 YAML frontmatter）")
    parser.add_argument("-o", "--output", default="cover.jpg", help="输出图片路径（默认 cover.jpg）")
    parser.add_argument(
        "-s",
        "--style",
        default="accent-bar",
        choices=list(STYLE_RENDERERS.keys()),
        help="封面样式（默认 accent-bar）",
    )
    parser.add_argument("-c", "--colors", default=None, help="自定义颜色 JSON 文件路径")

    args = parser.parse_args()

    if not os.path.isfile(args.article):
        print(f"[error] 文件不存在: {args.article}", file=sys.stderr)
        sys.exit(1)

    generate_cover(args.article, args.output, args.style, args.colors)


if __name__ == "__main__":
    main()
