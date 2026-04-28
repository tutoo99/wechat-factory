#!/usr/bin/env python3

import argparse
import html
import json
import mimetypes
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
from lxml import html as lxml_html


LIST_URL = "https://mp.weixin.qq.com/cgi-bin/appmsgpublish"
DEFAULT_FAKEID = "MzU3MTc1MjE4OQ=="
DEFAULT_FINGERPRINT = "5504547a08cc59c607a82d9367538b2d"


def parse_args():
    parser = argparse.ArgumentParser(description="Fetch WeChat articles and export them as docx.")
    parser.add_argument("--begin", type=int, default=0, help="Pagination offset: 0, 5, 10 ...")
    parser.add_argument("--count", type=int, default=5, help="Number of publish-list entries per page")
    parser.add_argument(
        "--output-dir",
        default="/Users/naipan/.codex/skills/zhouzuoluo-perspective/references/sources/articles",
        help="Directory where generated docx files will be written",
    )
    parser.add_argument("--fakeid", default=DEFAULT_FAKEID)
    parser.add_argument("--fingerprint", default=DEFAULT_FINGERPRINT)
    parser.add_argument("--token", default=os.environ.get("WECHAT_TOKEN", ""))
    parser.add_argument("--cookie", default=os.environ.get("WECHAT_COOKIE", ""))
    parser.add_argument("--dry-run", action="store_true", help="Only list extracted articles, do not fetch details")
    return parser.parse_args()


def build_session(cookie):
    session = requests.Session()
    session.headers.update(
        {
            "accept": "*/*",
            "accept-language": "zh-CN,zh;q=0.9",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
            "x-requested-with": "XMLHttpRequest",
            "cookie": cookie,
        }
    )
    return session


def sanitize_filename(name):
    name = re.sub(r'[<>:"/\\\\|?*\\x00-\\x1f]+', "_", name).strip()
    name = re.sub(r"\\s+", " ", name)
    return name[:120] if len(name) > 120 else name


def fetch_publish_page(session, begin, count, token, fakeid, fingerprint):
    params = {
        "sub": "list",
        "search_field": "null",
        "begin": begin,
        "count": count,
        "query": "",
        "fakeid": fakeid,
        "type": "101_1",
        "free_publish_type": 1,
        "sub_action": "list_ex",
        "fingerprint": fingerprint,
        "token": token,
        "lang": "zh_CN",
        "f": "json",
        "ajax": 1,
    }
    response = session.get(LIST_URL, params=params, timeout=60)
    response.raise_for_status()
    payload = response.json()
    if payload.get("base_resp", {}).get("ret") != 0:
        raise RuntimeError(f"Unexpected ret code: {payload.get('base_resp')}")
    return payload


def iter_articles(payload):
    publish_page = json.loads(payload["publish_page"])
    for publish_entry in publish_page.get("publish_list", []):
        publish_info = json.loads(publish_entry["publish_info"])
        for article in publish_info.get("appmsgex", []):
            yield {
                "title": article.get("title", "").strip(),
                "link": article.get("link", "").replace("\\/", "/"),
                "author": article.get("author_name", "").strip(),
                "content_hint": article.get("content", ""),
                "item_show_type": article.get("item_show_type"),
                "create_time": article.get("create_time"),
            }


def decode_js_escapes(raw):
    raw = raw.replace("\\/", "/")
    raw = re.sub(r"\\x([0-9A-Fa-f]{2})", lambda m: chr(int(m.group(1), 16)), raw)
    raw = re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), raw)
    replacements = {
        r"\\n": "\n",
        r"\\r": "\r",
        r"\\t": "\t",
        r"\\'": "'",
        r'\\"': '"',
        r"\\\\": "\\",
    }
    for source, target in replacements.items():
        raw = raw.replace(source, target)
    return raw


def extract_js_string(page, prefix, quote):
    idx = page.find(prefix)
    if idx == -1:
        return None

    start = idx + len(prefix)
    while start < len(page) and page[start].isspace():
        start += 1
    if start >= len(page) or page[start] != quote:
        return None

    cursor = start + 1
    escaped = False
    while cursor < len(page):
        char = page[cursor]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == quote:
            return page[start + 1 : cursor]
        cursor += 1
    return None


def extract_detail_page(session, article):
    response = session.get(
        article["link"],
        headers={
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "user-agent": session.headers["user-agent"],
            "cookie": session.headers["cookie"],
        },
        timeout=60,
    )
    response.raise_for_status()
    page = response.text

    title_raw = extract_js_string(page, "var msg_title = ", "'")
    author_raw = extract_js_string(page, 'var nickname = htmlDecode(', '"')
    content_raw = extract_js_string(page, "content_noencode: JsDecode(", "'")

    title = decode_js_escapes(title_raw) if title_raw else article["title"]
    author = html.unescape(author_raw) if author_raw else article["author"]
    content_html = decode_js_escapes(content_raw) if content_raw else article.get("content_hint", "")

    if not content_html:
        raise RuntimeError(f"Failed to extract content_noencode for {article['link']}")

    return {
        "title": html.unescape(title).strip(),
        "author": html.unescape(author).strip() or article["author"],
        "link": article["link"],
        "content_html": html.unescape(content_html),
    }


def normalize_text(text):
    text = html.unescape(text or "")
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def section_is_leafish(node):
    block_descendants = node.xpath(".//*[self::p or self::section or self::pre or self::blockquote or self::h1 or self::h2 or self::h3 or self::h4 or self::h5 or self::h6 or self::img]")
    return len(block_descendants) == 0


def html_to_blocks(content_html):
    wrapper = lxml_html.fragment_fromstring(f"<div>{content_html}</div>", create_parent=True)
    blocks = []
    seen_images = set()

    for node in wrapper.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.lower()

        if tag == "img":
            url = node.get("data-src") or node.get("src")
            if url and url not in seen_images:
                seen_images.add(url)
                ratio = node.get("data-ratio")
                raw_width = node.get("data-w") or node.get("width")
                width = 420
                if raw_width:
                    try:
                        width = min(420, max(240, int(float(raw_width))))
                    except Exception:
                        width = 420
                height = 280
                if ratio:
                    try:
                        height = int(width * float(ratio))
                    except Exception:
                        height = 280
                blocks.append(
                    {
                        "type": "image",
                        "url": url,
                        "image_type": (node.get("data-type") or "jpg").lower(),
                        "alt": normalize_text(node.get("data-alt") or ""),
                        "width": width,
                        "height": height,
                    }
                )
            continue

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = normalize_text("".join(node.itertext()))
            if text:
                blocks.append({"type": "heading", "level": 1 if tag in {"h1", "h2"} else 2, "text": text})
            continue

        if tag in {"p", "pre", "blockquote", "li"}:
            text = normalize_text("".join(node.itertext()))
            if text:
                blocks.append({"type": "paragraph", "text": text})
            continue

        if tag == "section" and section_is_leafish(node):
            text = normalize_text("".join(node.itertext()))
            if text:
                blocks.append({"type": "paragraph", "text": text})

    deduped = []
    last_sig = None
    for block in blocks:
        sig = (block["type"], block.get("text") or block.get("url"))
        if sig == last_sig:
            continue
        deduped.append(block)
        last_sig = sig
    return deduped


def infer_extension(block, response):
    image_type = (block.get("image_type") or "").lower()
    if image_type in {"jpeg", "jpg", "png", "gif", "webp"}:
        return "jpg" if image_type == "jpeg" else image_type
    content_type = response.headers.get("content-type", "").split(";")[0].strip()
    guessed = mimetypes.guess_extension(content_type)
    if guessed:
        return guessed.lstrip(".")
    path = urlparse(block["url"]).path
    ext = Path(path).suffix.lstrip(".")
    return ext or "jpg"


def download_images(session, article_slug, blocks, assets_root):
    article_img_dir = assets_root / article_slug
    article_img_dir.mkdir(parents=True, exist_ok=True)

    image_index = 0
    for block in blocks:
        if block["type"] != "image":
            continue
        image_index += 1
        response = session.get(block["url"], timeout=60)
        response.raise_for_status()
        ext = infer_extension(block, response)
        image_path = article_img_dir / f"image_{image_index:03d}.{ext}"
        image_path.write_bytes(response.content)
        block["local_path"] = str(image_path)


def render_docx(manifest_path, output_path):
    script_path = Path(__file__).with_name("render_wechat_docx.js")
    subprocess.run(["node", str(script_path), str(manifest_path), str(output_path)], check=True)


def export_article(session, article, output_dir):
    detail = extract_detail_page(session, article)
    blocks = html_to_blocks(detail["content_html"])

    safe_name = sanitize_filename(detail["title"])
    assets_root = output_dir / ".assets"
    manifests_root = output_dir / ".manifests"
    assets_root.mkdir(parents=True, exist_ok=True)
    manifests_root.mkdir(parents=True, exist_ok=True)

    download_images(session, safe_name, blocks, assets_root)

    manifest = {
        "title": detail["title"],
        "author": detail["author"],
        "source_account": "粥左罗",
        "link": detail["link"],
        "blocks": blocks,
    }
    manifest_path = manifests_root / f"{safe_name}.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    output_path = output_dir / f"{safe_name}.docx"
    render_docx(manifest_path, output_path)
    return output_path


def main():
    args = parse_args()
    if not args.token or not args.cookie:
        print("WECHAT_TOKEN / WECHAT_COOKIE are required.", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    session = build_session(args.cookie)

    payload = fetch_publish_page(
        session=session,
        begin=args.begin,
        count=args.count,
        token=args.token,
        fakeid=args.fakeid,
        fingerprint=args.fingerprint,
    )

    articles = list(iter_articles(payload))
    print(f"Fetched {len(articles)} articles from begin={args.begin}")
    for idx, article in enumerate(articles, start=1):
        print(f"{idx:02d}. {article['title']} -> {article['link']}")

    if args.dry_run:
        return

    exported = []
    for article in articles:
        path = export_article(session, article, output_dir)
        exported.append(path)
        print(f"Exported {path}")

    print(f"Done. Exported {len(exported)} docx files to {output_dir}")


if __name__ == "__main__":
    main()
