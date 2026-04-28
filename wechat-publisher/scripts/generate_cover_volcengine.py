#!/usr/bin/env python3
"""
火山引擎文生图 — 公众号封面生成工具

用法：
  # 自动匹配风格（根据 channel + article_type）
  python3 generate_cover_volcengine.py final.md -o cover.jpg

  # 指定风格
  python3 generate_cover_volcengine.py final.md -o cover.jpg -s cyberpunk

  # 查看所有可用风格
  python3 generate_cover_volcengine.py --list-styles

依赖：pip3 install requests pyyaml
"""

import argparse
import json
import os
import re
import sys
import time

import requests
import yaml
from PIL import Image

# ── 路径 ────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)
PROMPTS_FILE = os.path.join(SKILL_DIR, "cover-prompts.yaml")

# ── 配置 ────────────────────────────────────────────────
# API 端点与模型
API_URL = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
MODEL = "doubao-seedream-4-0-250828"
DEFAULT_IMAGE_SIZE = "1880x800"
TARGET_ASPECT = 2.35


def load_config():
    """从环境变量加载 API key"""
    api_key = os.environ.get("ARK_API_KEY", "")
    if not api_key:
        print(
            "[error] 未设置环境变量 ARK_API_KEY\n"
            "  export ARK_API_KEY=\"ark-xxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-xxxxx\"\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return {"api_key": api_key}


def load_prompts():
    """加载提示词模板和匹配规则"""
    with open(PROMPTS_FILE, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_frontmatter(filepath):
    """从 Markdown 文件提取 YAML frontmatter"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    return yaml.safe_load(m.group(1)) or {}


def load_prompt_file(filepath):
    """读取当前会话 LLM 生成的完整生图提示词"""
    if not os.path.exists(filepath):
        print(f"[error] 提示词文件不存在: {filepath}", file=sys.stderr)
        sys.exit(1)

    with open(filepath, "r", encoding="utf-8") as f:
        prompt = f.read().strip()

    if not prompt:
        print(f"[error] 提示词文件为空: {filepath}", file=sys.stderr)
        sys.exit(1)

    return prompt


def sanitize_prompt(prompt):
    """避免比例/尺寸等控制信息被文生图模型渲染进画面。"""
    replacements = {
        "2.35:1": "公众号常用横向宽幅",
        "900×383": "公众号常用横向宽幅",
        "900x383": "公众号常用横向宽幅",
        "900 x 383": "公众号常用横向宽幅",
    }
    sanitized = prompt
    for source, target in replacements.items():
        sanitized = sanitized.replace(source, target)
    return sanitized


def recommend_templates(prompts_data, channel, article_type=None):
    """根据 channel + article_type 推荐3个最佳模板，返回 [(template_id, name, reason), ...]"""
    rules = prompts_data.get("matching_rules", {})
    channel_rules = rules.get(channel, [])
    templates = prompts_data.get("templates", {})

    scored = []
    for rule in channel_rules:
        tid = rule.get("template") or rule.get("default")
        if not tid or tid not in templates:
            continue
        if article_type and article_type in rule.get("article_types", []):
            scored.append((tid, templates[tid].get("name", tid), rule.get("reason", ""), 10))
        elif "default" in rule:
            scored.append((tid, templates[tid].get("name", tid), "兜底推荐", 1))
        else:
            # 该频道下其他模板给中等分数
            scored.append((tid, templates[tid].get("name", tid), templates[tid].get("description", ""), 5))

    # 按 score 降序，取前3
    scored.sort(key=lambda x: x[3], reverse=True)
    return scored[:3]


def build_prompt(template_text, title, cover_text=None):
    """用实际文案填充模板占位符"""
    display_title = cover_text or title

    prompt = template_text.replace("{{title}}", display_title)

    # 处理副标题：如果有则填入，没有则删除整个副标题句子
    if "{{subtitle}}" in prompt:
        # 匹配并删除包含 {{subtitle}} 的整句话（到句号为止）
        import re
        prompt = re.sub(r'副标题"{{subtitle}}"[^。]*。', '', prompt)

    # 清理残留的副标题占位符
    prompt = prompt.replace("{{subtitle_prompt}}", "")
    prompt = prompt.replace("{{subtitle}}", "")

    return prompt


def parse_size(size):
    m = re.match(r"^(\d+)x(\d+)$", size)
    if not m:
        print(f"[error] size 必须是 WIDTHxHEIGHT 格式，例如 {DEFAULT_IMAGE_SIZE}", file=sys.stderr)
        sys.exit(1)
    width = int(m.group(1))
    height = int(m.group(2))
    if width <= 0 or height <= 0:
        print(f"[error] size 宽高必须大于 0: {size}", file=sys.stderr)
        sys.exit(1)
    return width, height


def validate_cover_aspect_size(size):
    width, height = parse_size(size)
    aspect = width / height
    if abs(aspect - TARGET_ASPECT) > 0.001:
        print(f"[error] 火山封面 size 必须是 2.35:1，当前 {size} = {aspect:.4f}:1", file=sys.stderr)
        sys.exit(1)
    return width, height


def call_volcengine(prompt, api_key, image_size):
    """调用火山引擎文生图 API，返回图片 URL"""
    validate_cover_aspect_size(image_size)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = {
        "model": MODEL,
        "prompt": prompt,
        "sequential_image_generation": "disabled",
        "response_format": "url",
        "size": image_size,
        "stream": False,
        "watermark": False,
    }

    print(f"[api] 调用火山引擎文生图...")
    print(f"[api] 模型: {MODEL}")
    print(f"[api] 尺寸: {image_size} (2.35:1)")

    resp = requests.post(API_URL, headers=headers, json=payload, timeout=120)

    if resp.status_code != 200:
        print(f"[error] API 返回 {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    data = resp.json()

    # 提取图片 URL
    images = data.get("data", [])
    if not images:
        print(f"[error] API 未返回图片: {json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)

    image_url = images[0].get("url", "")
    if not image_url:
        print(f"[error] 图片 URL 为空: {json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)

    return image_url


def download_image(url, output_path, expected_size):
    """下载图片到本地"""
    print(f"[下载] 正在下载封面图...")
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        print(f"[error] 下载失败: {resp.status_code}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) / 1024
    print(f"[ok] 封面已下载: {output_path} ({size_kb:.0f}KB)")
    verify_downloaded_size(output_path, expected_size)


def verify_downloaded_size(output_path, expected_size):
    expected_width, expected_height = parse_size(expected_size)
    with Image.open(output_path) as im:
        width, height = im.size
    if (width, height) != (expected_width, expected_height):
        print(
            f"[error] 火山返回尺寸不是请求的 2.35:1 尺寸: got {width}x{height}, expected {expected_size}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[ok] 封面尺寸验证通过: {width}x{height} (2.35:1)")


def list_styles():
    """列出所有可用风格"""
    prompts_data = load_prompts()
    templates = prompts_data.get("templates", {})

    print("可用封面风格：\n")
    print(f"{'ID':<20} {'名称':<15} {'适合频道':<15} 说明")
    print("-" * 70)
    for tid, tmpl in templates.items():
        channels = ", ".join(tmpl.get("fit_channels", []))
        desc = tmpl.get("description", "")
        name = tmpl.get("name", tid)
        print(f"{tid:<20} {name:<15} {channels:<15} {desc}")


def main():
    parser = argparse.ArgumentParser(description="火山引擎文生图 — 公众号封面生成")
    parser.add_argument("input", nargs="?", help="Markdown 文件路径（需含 YAML frontmatter）")
    parser.add_argument("-o", "--output", default="cover.jpg", help="输出文件路径 (默认 cover.jpg)")
    parser.add_argument("-s", "--style", default=None, help="指定风格 ID（不指定则自动匹配）")
    parser.add_argument("--channel", default=None, help="手动指定 channel (tech/emotion)")
    parser.add_argument("--article-type", default=None, help="手动指定文章类型")
    parser.add_argument("--prompt-file", default=None, help="读取当前会话 LLM 生成的完整生图提示词")
    parser.add_argument("--size", default=DEFAULT_IMAGE_SIZE, help=f"火山输出尺寸，必须是 2.35:1（默认 {DEFAULT_IMAGE_SIZE}）")
    parser.add_argument("--list-styles", action="store_true", help="列出所有可用风格")
    parser.add_argument("--recommend", "--rec", action="store_true", help="推荐3种风格（不生成图片）")
    parser.add_argument("--dry-run", action="store_true", help="只输出生成的提示词，不调API")
    args = parser.parse_args()

    if args.list_styles:
        list_styles()
        return

    if not args.input:
        parser.error("input is required unless --list-styles is used")

    # 加载模板
    prompts_data = load_prompts()
    templates = prompts_data.get("templates", {})

    # 解析 frontmatter
    fm = parse_frontmatter(args.input)
    title = fm.get("title", "")
    cover_text = fm.get("cover_text", "")
    channel = args.channel or fm.get("channel", "tech")
    article_type = args.article_type or fm.get("framework", "")

    print(f"[信息] 标题: {title}")
    print(f"[信息] 封面文案: {cover_text or '(使用标题)'}")
    print(f"[信息] 频道: {channel}")
    print(f"[信息] 文章类型: {article_type or '(未指定)'}")
    validate_cover_aspect_size(args.size)
    print(f"[信息] 目标尺寸: {args.size} (2.35:1)")

    # 推荐或指定模板
    if args.style:
        template_id = args.style
        if template_id not in templates:
            print(f"[error] 未知风格 '{template_id}'，可用风格：{', '.join(templates.keys())}", file=sys.stderr)
            sys.exit(1)
        print(f"[信息] 用户指定风格: {template_id}")
    elif args.recommend:
        recs = recommend_templates(prompts_data, channel, article_type)
        print(f"\n[推荐] 根据文章内容推荐以下风格：\n")
        for i, (tid, name, reason, _) in enumerate(recs, 1):
            print(f"  {i}. {name} ({tid})")
            print(f"     {reason}")
        print(f"\n请选择风格 ID，例如：")
        print(f"  python3 {sys.argv[0]} {args.input} -o {args.output} -s {recs[0][0]}")
        return
    elif not args.prompt_file:
        recs = recommend_templates(prompts_data, channel, article_type)
        if recs:
            template_id = recs[0][0]
        else:
            template_id = "minimal_bw"
        print(f"[信息] 默认推荐风格: {template_id}")

    # 构建提示词
    if args.prompt_file:
        prompt = load_prompt_file(args.prompt_file)
        print(f"[信息] 提示词来源: {args.prompt_file}")
        if args.style:
            print(f"[信息] 风格由外部提示词控制，-s/--style 仅保留为流程记录: {args.style}")
    else:
        tmpl = templates[template_id]
        print(f"[信息] 风格名称: {tmpl.get('name', template_id)}")
        prompt = build_prompt(tmpl["prompt"], title, cover_text)

    sanitized_prompt = sanitize_prompt(prompt)
    if sanitized_prompt != prompt:
        print("[信息] 已清理提示词中的比例/尺寸字面量，避免被渲染进图片")
        prompt = sanitized_prompt

    print(f"\n[提示词]\n{prompt}\n")

    if args.dry_run:
        print("[dry-run] 以上为生成的提示词，未调用 API")
        return

    # 加载配置
    config = load_config()
    api_key = config.get("api_key")
    if not api_key:
        print("[error] 配置文件中缺少 api_key", file=sys.stderr)
        sys.exit(1)

    # 调 API
    image_url = call_volcengine(prompt, api_key, args.size)
    print(f"[api] 图片 URL: {image_url[:80]}...")

    # 下载
    download_image(image_url, args.output, args.size)
    print(f"\n[完成] 封面图已保存到: {args.output}")


if __name__ == "__main__":
    main()
