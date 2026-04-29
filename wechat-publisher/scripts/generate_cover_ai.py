#!/usr/bin/env python3
"""
AI 文生图 — 公众号封面统一生成工具

用法：
  # 当前会话 LLM 先生成完整场景化提示词，再调用指定 provider
  python3 generate_cover_ai.py final.md -o cover.jpg --prompt-file final.cover.prompt.md --provider sensenova
  python3 generate_cover_ai.py final.md -o cover.jpg --prompt-file final.cover.prompt.md --provider volcengine

  # 只检查提示词、provider 和尺寸，不调 API
  python3 generate_cover_ai.py final.md --prompt-file final.cover.prompt.md --provider sensenova --dry-run

依赖：pip3 install requests pillow
"""

import argparse
import base64
import json
import os
import re
import sys
from dataclasses import dataclass

import requests
from PIL import Image


DEFAULT_IMAGE_SIZE = "1880x800"
TARGET_ASPECT = 2.35


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    display_name: str
    api_url: str
    model: str
    env_var: str


PROVIDERS = {
    "volcengine": ProviderSpec(
        name="volcengine",
        display_name="火山引擎文生图",
        api_url="https://ark.cn-beijing.volces.com/api/v3/images/generations",
        model="doubao-seedream-4-0-250828",
        env_var="ARK_API_KEY",
    ),
    "sensenova": ProviderSpec(
        name="sensenova",
        display_name="SenseNova 文生图",
        api_url="https://token.sensenova.cn/v1/images/generations",
        model="sensenova-u1-fast",
        env_var="SENSENOVA_API_KEY",
    ),
}


def load_config(provider):
    """从环境变量加载 provider API key。"""
    api_key = os.environ.get(provider.env_var, "")
    if not api_key:
        print(
            f"[error] 未设置环境变量 {provider.env_var}\n"
            f"  请在 ~/.zshrc 中添加并 source：\n"
            f"  export {provider.env_var}=\"your-key-here\"\n",
            file=sys.stderr,
        )
        sys.exit(1)
    return {"api_key": api_key}


def parse_frontmatter(filepath):
    """从 Markdown 文件提取 YAML frontmatter。"""
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, val = line.partition(":")
        meta[key.strip()] = val.strip().strip("\"'")
    return meta


def load_prompt_file(filepath):
    """读取当前会话 LLM 生成的完整生图提示词。"""
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
        "1880x800": "公众号常用横向宽幅",
        "1880×800": "公众号常用横向宽幅",
        "900×383": "公众号常用横向宽幅",
        "900x383": "公众号常用横向宽幅",
        "900 x 383": "公众号常用横向宽幅",
        "3072x1376": "",
        "3072×1376": "",
        "2752x1536": "",
        "2752×1536": "",
    }
    sanitized = prompt
    for source, target in replacements.items():
        sanitized = sanitized.replace(source, target)
    sanitized = re.sub(r"[ \t]+", " ", sanitized)
    while "，，" in sanitized:
        sanitized = sanitized.replace("，，", "，")
    sanitized = sanitized.replace("，。", "。")
    return sanitized.strip(" ，,")


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
        print(f"[error] AI 封面 size 必须是 2.35:1，当前 {size} = {aspect:.4f}:1", file=sys.stderr)
        sys.exit(1)
    return width, height


def build_payload(provider, prompt, image_size):
    if provider.name == "volcengine":
        return {
            "model": provider.model,
            "prompt": prompt,
            "sequential_image_generation": "disabled",
            "response_format": "url",
            "size": image_size,
            "stream": False,
            "watermark": False,
        }
    if provider.name == "sensenova":
        return {
            "model": provider.model,
            "prompt": prompt,
            "size": image_size,
            "n": 1,
        }
    print(f"[error] 暂不支持 provider: {provider.name}", file=sys.stderr)
    sys.exit(1)


def extract_image_ref(provider, data):
    images = data.get("data", [])
    if not images:
        print(f"[error] API 未返回图片: {json.dumps(data, ensure_ascii=False)}", file=sys.stderr)
        sys.exit(1)

    image = images[0]
    image_url = image.get("url", "")
    if image_url:
        return image_url

    b64 = image.get("b64_json", "")
    if b64:
        return f"base64:{b64}"

    print(
        f"[error] {provider.display_name} 返回中没有 url 或 b64_json: {json.dumps(data, ensure_ascii=False)}",
        file=sys.stderr,
    )
    sys.exit(1)


def call_provider(provider, prompt, api_key, image_size):
    """调用文生图 provider，返回图片 URL 或 base64 引用。"""
    validate_cover_aspect_size(image_size)
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    payload = build_payload(provider, prompt, image_size)

    print(f"[api] 调用 {provider.display_name}...")
    print(f"[api] Provider: {provider.name}")
    print(f"[api] 模型: {provider.model}")
    print(f"[api] 尺寸: {image_size} (2.35:1)")

    resp = requests.post(provider.api_url, headers=headers, json=payload, timeout=120)

    if resp.status_code != 200:
        print(f"[error] API 返回 {resp.status_code}: {resp.text}", file=sys.stderr)
        sys.exit(1)

    return extract_image_ref(provider, resp.json())


def verify_downloaded_size(output_path, expected_size, provider):
    expected_width, expected_height = parse_size(expected_size)
    with Image.open(output_path) as im:
        width, height = im.size
    if (width, height) != (expected_width, expected_height):
        print(
            f"[error] {provider.display_name} 返回尺寸不是请求的 2.35:1 尺寸: "
            f"got {width}x{height}, expected {expected_size}",
            file=sys.stderr,
        )
        sys.exit(1)
    print(f"[ok] 封面尺寸验证通过: {width}x{height} (2.35:1)")


def download_image(image_ref, output_path, expected_size, provider):
    """下载或保存图片到本地，并校验尺寸。"""
    if image_ref.startswith("base64:"):
        b64_data = image_ref[len("base64:") :]
        img_bytes = base64.b64decode(b64_data)
        with open(output_path, "wb") as f:
            f.write(img_bytes)
        print(f"[ok] 封面已保存 (base64): {output_path}")
        verify_downloaded_size(output_path, expected_size, provider)
        return

    print("[下载] 正在下载封面图...")
    resp = requests.get(image_ref, timeout=60)
    if resp.status_code != 200:
        print(f"[error] 下载失败: {resp.status_code}", file=sys.stderr)
        sys.exit(1)

    with open(output_path, "wb") as f:
        f.write(resp.content)

    size_kb = len(resp.content) / 1024
    print(f"[ok] 封面已下载: {output_path} ({size_kb:.0f}KB)")
    verify_downloaded_size(output_path, expected_size, provider)


def main(default_provider=None):
    parser = argparse.ArgumentParser(description="AI 文生图 — 公众号封面统一生成")
    parser.add_argument("input", help="Markdown 文件路径（需含 YAML frontmatter）")
    parser.add_argument("-o", "--output", default="cover.jpg", help="输出文件路径 (默认 cover.jpg)")
    parser.add_argument("--channel", default=None, help="手动指定 channel (tech/emotion)")
    parser.add_argument("--article-type", default=None, help="手动指定文章类型")
    parser.add_argument("--prompt-file", required=True, help="读取当前会话 LLM 生成的完整生图提示词")
    parser.add_argument(
        "--provider",
        choices=sorted(PROVIDERS.keys()),
        default=default_provider,
        required=default_provider is None,
        help="文生图 provider",
    )
    parser.add_argument("--size", default=DEFAULT_IMAGE_SIZE, help=f"输出尺寸，必须是 2.35:1（默认 {DEFAULT_IMAGE_SIZE}）")
    parser.add_argument("--dry-run", action="store_true", help="只输出提示词和配置，不调 API")
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]

    fm = parse_frontmatter(args.input)
    title = fm.get("title", "")
    cover_text = fm.get("cover_text", "")
    channel = args.channel or fm.get("channel", "tech")
    article_type = args.article_type or fm.get("framework", "")

    print(f"[信息] 标题: {title}")
    print(f"[信息] 封面文案: {cover_text or '(使用标题)'}")
    print(f"[信息] 频道: {channel}")
    print(f"[信息] 文章类型: {article_type or '(未指定)'}")
    print(f"[信息] Provider: {provider.name} ({provider.display_name})")
    print(f"[信息] 模型: {provider.model}")
    print(f"[信息] API key 环境变量: {provider.env_var}")
    validate_cover_aspect_size(args.size)
    print(f"[信息] 目标尺寸: {args.size} (2.35:1)")

    prompt = load_prompt_file(args.prompt_file)
    print(f"[信息] 提示词来源: {args.prompt_file}")

    sanitized_prompt = sanitize_prompt(prompt)
    if sanitized_prompt != prompt:
        print("[信息] 已清理提示词中的比例/尺寸字面量，避免被渲染进图片")
        prompt = sanitized_prompt

    print(f"\n[提示词]\n{prompt}\n")

    if args.dry_run:
        print("[dry-run] 以上为提示词和 provider 配置，未调用 API")
        return

    config = load_config(provider)
    image_ref = call_provider(provider, prompt, config["api_key"], args.size)
    if not image_ref.startswith("base64:"):
        print(f"[api] 图片 URL: {image_ref[:80]}...")

    download_image(image_ref, args.output, args.size, provider)
    print(f"\n[完成] 封面图已保存到: {args.output}")


if __name__ == "__main__":
    main()
