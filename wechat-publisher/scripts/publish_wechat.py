#!/usr/bin/env python3
"""
微信公众号自动化发布脚本 (ruyiPage)

使用 ruyiPage (Firefox + WebDriver BiDi) 自动化操作微信公众号后台，
将文章推送到草稿箱。

用法:
    python3 publish_wechat.py publish --channel tech --article article.html \
        --cover cover.jpg --title "标题" --author "作者" --digest "摘要"

    python3 publish_wechat.py xls-publish --channel tech \
        --images pic1.jpg pic2.jpg --title "标题" --description "描述"

    python3 publish_wechat.py list-channels
    python3 publish_wechat.py list-profiles
    python3 publish_wechat.py create-profile --slug qiaosan --display-name "乔三技术号"
"""

import argparse
import hashlib
import os
import re
import shutil
import sys
import time
import json
from html.parser import HTMLParser
from pathlib import Path
from typing import Optional

# ── 常量 ──

WECHAT_MP_URL = "https://mp.weixin.qq.com"
EDITOR_URL_PATTERN = "cgi-bin/appmsg?t=media/appmsg_edit"
LOGIN_TIMEOUT = 120

DEFAULT_PROFILES_DIR = os.path.expanduser(
    "~/.hermes/skills/wechat-factory/wechat-publisher/data/profiles"
)
DEFAULT_SCREENSHOTS_DIR = os.path.expanduser(
    "~/.hermes/skills/wechat-factory/wechat-publisher/data/screenshots"
)
DEFAULT_OUTPUT_BASE = os.path.expanduser(
    "~/.hermes/output/wechat"
)
VERSION_RETENTION_DAYS = 7
DUPLICATE_PUBLISH_WINDOW_SECONDS = 10 * 60
RESERVED_PROFILE_DIR_NAMES = {"screenshots"}
CHANNEL_ACTIVE_STATUSES = {"active"}
SCRIPT_DIR = Path(__file__).resolve().parent
FACTORY_ROOT = SCRIPT_DIR.parent.parent
CHANNELS_CONFIG_PATH = FACTORY_ROOT / "channels.yaml"
PROFILE_META_FILENAME = "profile.json"


# ── 辅助函数 ──

def resolve_user_dir(user_dir=None):
    if user_dir:
        p = Path(user_dir)
        if not p.is_absolute():
            p = p.expanduser().resolve()
        return str(p)
    return os.path.join(DEFAULT_PROFILES_DIR, "mp__qiaosan")


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def load_yaml_file(path):
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def read_file_content(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        return f.read()


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        text = data.strip()
        if text:
            self.parts.append(text)


def html_to_plain_text(html_content):
    parser = _HTMLTextExtractor()
    parser.feed(html_content or "")
    return re.sub(r"\s+", " ", " ".join(parser.parts)).strip()


def normalize_text(text):
    return re.sub(r"\s+", "", text or "")


def body_sample_from_html(html_content, min_len=18, max_len=36):
    text = html_to_plain_text(html_content)
    normalized = normalize_text(text)
    if len(normalized) <= min_len:
        return normalized
    return normalized[:max_len]


def resolve_input_files(paths, label="文件"):
    if not paths:
        return []
    resolved = []
    for raw_path in paths:
        p = Path(raw_path).expanduser()
        if not p.is_absolute():
            p = p.resolve()
        if not p.exists():
            raise FileNotFoundError("%s不存在: %s" % (label, p))
        resolved.append(str(p))
    return resolved


def resolve_cover_path(cover=None):
    if not cover:
        return None
    p = Path(cover)
    if not p.is_absolute():
        p = p.expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError("封面图不存在: %s" % p)
    return str(p)


def compute_file_sha256(filepath):
    sha = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha.update(chunk)
    return sha.hexdigest()


def write_json_file(filepath, data):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_channels_config(config_path=CHANNELS_CONFIG_PATH):
    if not Path(config_path).exists():
        return {}
    data = load_yaml_file(config_path)
    channels = data.get("channels") or {}
    if not isinstance(channels, dict):
        raise ValueError("channels.yaml 格式错误：channels 必须是对象映射")
    return channels


def get_channel_config(channel_id, config_path=CHANNELS_CONFIG_PATH):
    channels = load_channels_config(config_path=config_path)
    if not channels:
        raise FileNotFoundError("未找到 channels.yaml，请先在 wechat-factory 根目录配置频道映射。")
    channel = channels.get(channel_id)
    if not channel:
        available = ", ".join(sorted(channels.keys()))
        raise KeyError("未找到 channel '%s'。可用 channel: %s" % (channel_id, available or "无"))
    if not isinstance(channel, dict):
        raise ValueError("channels.yaml 格式错误：channel '%s' 必须是对象" % channel_id)
    status = str(channel.get("status") or "active").strip().lower()
    channel["status"] = status
    return channel


def resolve_profile_dir(profile_name=None):
    if not profile_name:
        return None
    profile = Path(profile_name).expanduser()
    if profile.is_absolute():
        return str(profile)
    return str((Path(DEFAULT_PROFILES_DIR) / profile_name).resolve())


def get_persona_path(persona_id):
    if not persona_id:
        return None
    return FACTORY_ROOT / ("persona-%s.yaml" % persona_id)


def read_profile_meta(profile_dir):
    meta_path = Path(profile_dir) / PROFILE_META_FILENAME
    if not meta_path.exists():
        return {}
    try:
        return load_yaml_file(meta_path)
    except Exception:
        return {}


def write_profile_meta(profile_dir, data):
    meta_path = Path(profile_dir) / PROFILE_META_FILENAME
    write_json_file(meta_path, data)


def iter_profile_dirs():
    ensure_dir(DEFAULT_PROFILES_DIR)
    dirs = []
    for entry in os.scandir(DEFAULT_PROFILES_DIR):
        if not entry.is_dir():
            continue
        if entry.name.startswith("."):
            continue
        if entry.name in RESERVED_PROFILE_DIR_NAMES:
            continue
        dirs.append(entry)
    dirs.sort(key=lambda item: item.name)
    return dirs


def merge_channel_publish_args(args):
    if not args.channel:
        final_account = args.account or "tech"
        final_user_dir = resolve_user_dir(args.user_dir)
        return {
            "channel_id": None,
            "channel": None,
            "account": final_account,
            "user_dir": final_user_dir,
        }

    channel = get_channel_config(args.channel)
    if channel["status"] not in CHANNEL_ACTIVE_STATUSES:
        raise ValueError(
            "channel '%s' 当前状态为 %s，不能直接发布。"
            % (args.channel, channel["status"])
        )

    profile_name = channel.get("profile")
    if not profile_name:
        raise ValueError(
            "channel '%s' 还没有绑定 profile，请先在 channels.yaml 里补上 profile。"
            % args.channel
        )

    persona_id = channel.get("persona")
    if persona_id:
        persona_path = get_persona_path(persona_id)
        if not persona_path or not persona_path.exists():
            raise FileNotFoundError(
                "channel '%s' 配置的人设 persona-%s.yaml 不存在。"
                % (args.channel, persona_id)
            )

    channel_user_dir = resolve_profile_dir(profile_name)
    if not os.path.isdir(channel_user_dir):
        raise FileNotFoundError(
            "channel '%s' 绑定的 profile 目录不存在: %s"
            % (args.channel, channel_user_dir)
        )

    channel_account = channel.get("archive_account")
    if not channel_account:
        raise ValueError(
            "channel '%s' 缺少 archive_account 配置。"
            % args.channel
        )

    if args.user_dir:
        explicit_user_dir = resolve_user_dir(args.user_dir)
        if os.path.abspath(explicit_user_dir) != os.path.abspath(channel_user_dir):
            raise ValueError(
                "--channel %s 与 --user-dir 指向的 profile 不一致。"
                % args.channel
            )

    if args.account and args.account != channel_account:
        raise ValueError(
            "--channel %s 与 --account %s 不一致，channel 绑定的是 archive_account=%s。"
            % (args.channel, args.account, channel_account)
        )

    return {
        "channel_id": args.channel,
        "channel": channel,
        "account": channel_account,
        "user_dir": channel_user_dir,
    }


# ── 产物归档 ──

def sanitize_dirname(name, max_len=50):
    """把文章标题转成安全的目录名。"""
    s = re.sub(r'[\\/:*?"<>|\n\r]', '_', name.strip())
    s = re.sub(r'_+', '_', s).strip('_')
    return s[:max_len] if len(s) > max_len else s


def resolve_article_dir(account="tech", title="未命名"):
    """解析产物目录路径，格式：~/.hermes/output/wechat/<account>/articles/<日期_标题>/"""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    dir_name = "%s_%s" % (date_str, sanitize_dirname(title))
    article_dir = os.path.join(DEFAULT_OUTPUT_BASE, account, "articles", dir_name)
    ensure_dir(article_dir)
    return article_dir


def load_publish_json(article_dir):
    """加载发布记录，不存在则返回空模板。"""
    json_path = os.path.join(article_dir, "publish.json")
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "title": "",
        "account": "",
        "current_version": 0,
        "history": [],
    }


def save_publish_json(article_dir, data):
    """保存发布记录。"""
    json_path = os.path.join(article_dir, "publish.json")
    write_json_file(json_path, data)


def archive_current_version(article_dir):
    """把当前版本归档到 versions/vN/，返回新版本号。"""
    pub = load_publish_json(article_dir)
    new_ver = pub.get("current_version", 0) + 1
    ver_dir = os.path.join(article_dir, "versions", "v%d" % new_ver)
    ensure_dir(ver_dir)

    moved = []
    for entry in os.scandir(article_dir):
        if not entry.is_file():
            continue
        if entry.name == "publish.json":
            continue
        dst_path = os.path.join(ver_dir, entry.name)
        shutil.copy2(entry.path, dst_path)
        moved.append(entry.name)

    pub["current_version"] = new_ver
    save_publish_json(article_dir, pub)
    return new_ver, moved


def record_publish(article_dir, title, account, action):
    """在 publish.json 中追加一条发布记录。"""
    from datetime import datetime
    pub = load_publish_json(article_dir)
    pub["title"] = title
    pub["account"] = account
    pub["history"].append({
        "version": pub.get("current_version", 0),
        "time": datetime.now().isoformat(),
        "action": action,
    })
    save_publish_json(article_dir, pub)


def copy_artifacts(article_dir, article_html_path, cover_path, final_md_path=None, extra_sources=None):
    """把产物复制到归档目录。"""
    import os
    # 复制 HTML
    if article_html_path and os.path.exists(article_html_path):
        dst = os.path.join(article_dir, "article.html")
        if os.path.abspath(article_html_path) != os.path.abspath(dst):
            shutil.copy2(article_html_path, dst)
    # 复制封面
    if cover_path and os.path.exists(cover_path):
        dst = os.path.join(article_dir, os.path.basename(cover_path))
        if os.path.abspath(cover_path) != os.path.abspath(dst):
            shutil.copy2(cover_path, dst)
    # 复制 final.md
    if final_md_path and os.path.exists(final_md_path):
        dst = os.path.join(article_dir, "final.md")
        if os.path.abspath(final_md_path) != os.path.abspath(dst):
            shutil.copy2(final_md_path, dst)
    for src_path in extra_sources or []:
        if src_path and os.path.exists(src_path):
            dst = os.path.join(article_dir, os.path.basename(src_path))
            if os.path.abspath(src_path) != os.path.abspath(dst):
                shutil.copy2(src_path, dst)


def has_current_artifacts(article_dir):
    if not os.path.isdir(article_dir):
        return False
    for entry in os.scandir(article_dir):
        if entry.is_file() and entry.name != "publish.json":
            return True
    return False


def is_probable_duplicate_publish(
    article_dir,
    article_html_path=None,
    cover_path=None,
    final_md_path=None,
    extra_comparisons=None,
    window_seconds=DUPLICATE_PUBLISH_WINDOW_SECONDS,
):
    """判断是否是短时间内对同一篇稿件的重复发布调用。"""
    from datetime import datetime

    pub = load_publish_json(article_dir)
    history = pub.get("history") or []
    if not history:
        return False

    last = history[-1]
    last_time = last.get("time")
    if not last_time:
        return False

    try:
        delta = datetime.now() - datetime.fromisoformat(last_time)
    except ValueError:
        return False

    if delta.total_seconds() > window_seconds:
        return False

    comparisons = []
    if article_html_path:
        comparisons.append((article_html_path, os.path.join(article_dir, "article.html")))
    if cover_path:
        comparisons.append((cover_path, os.path.join(article_dir, os.path.basename(cover_path))))
    if final_md_path:
        comparisons.append((final_md_path, os.path.join(article_dir, "final.md")))
    if extra_comparisons:
        comparisons.extend(extra_comparisons)

    if not comparisons:
        return False

    for src, dst in comparisons:
        if not src or not os.path.exists(src) or not os.path.exists(dst):
            return False
        if compute_file_sha256(src) != compute_file_sha256(dst):
            return False

    return True


def cleanup_old_versions(article_dir, retention_days=VERSION_RETENTION_DAYS):
    """清理超过 retention_days 天的版本目录。"""
    import time
    ver_base = os.path.join(article_dir, "versions")
    if not os.path.isdir(ver_base):
        return 0

    now = time.time()
    cutoff = now - retention_days * 86400
    cleaned = 0

    for ver_name in os.listdir(ver_base):
        ver_path = os.path.join(ver_base, ver_name)
        if not os.path.isdir(ver_path):
            continue
        # 用目录修改时间判断
        mtime = os.path.getmtime(ver_path)
        if mtime < cutoff:
            shutil.rmtree(ver_path)
            cleaned += 1

    if cleaned > 0:
        print("[清理] 已清理 %d 个过期版本（超过 %d 天）" % (cleaned, retention_days))
    return cleaned


class AutomationStepError(RuntimeError):
    pass


def raise_automation_step_error(page, step_name, screenshot_dir, message):
    ensure_dir(screenshot_dir)
    safe_step = sanitize_dirname(step_name or "step", max_len=30) or "step"
    ss_path = os.path.join(screenshot_dir, "%s_%d.png" % (safe_step, int(time.time())))
    try:
        page.screenshot(ss_path)
    except Exception:
        ss_path = None

    print("[阻塞] %s" % step_name)
    print("[阻塞] %s" % message)
    print("[阻塞] 当前URL: %s" % getattr(page, "url", "-"))
    if ss_path:
        print("[阻塞] 截图: %s" % ss_path)
    raise AutomationStepError("%s: %s" % (step_name, message))


# ── 登录检测 ──

def wait_for_login(page):
    print("[登录] 请使用微信扫描二维码登录，最多等待 %d 秒..." % LOGIN_TIMEOUT)
    start = time.time()
    while time.time() - start < LOGIN_TIMEOUT:
        current_url = page.url
        if "login" not in current_url.lower():
            print("[登录] 登录成功!")
            time.sleep(2)
            return
        time.sleep(3)
    raise TimeoutError("登录超时（%d秒）。请重新运行脚本并扫码登录。" % LOGIN_TIMEOUT)


def check_already_logged_in(page):
    try:
        current_url = page.url
        if not current_url:
            page.get(WECHAT_MP_URL)
            time.sleep(8)
            current_url = page.url
        # 管理后台URL包含 cgi-bin，首页/登录页是 mp.weixin.qq.com/
        if "/cgi-bin/" in current_url:
            return True
        # 额外检查：页面是否有"首页"或管理后台特征元素
        has_dashboard = page.run_js(
            "var found = false;"
            "var items = document.querySelectorAll('a, span, div');"
            "for (var i = 0; i < items.length; i++) {"
            "var t = items[i].textContent.trim();"
            "if (t === '内容与互动' || t === '内容' || t === '创作' || t === '发表管理') {"
            "found = true; break;"
            "} } found;",
            as_expr=True
        )
        return bool(has_dashboard)
    except Exception:
        return False


# ── 进入编辑器 ──

def extract_token(page):
    try:
        token = page.run_js(
            "(function() {"
            "var m = window.location.href.match(/token=(\\d+)/);"
            "if (m) return m[1];"
            "var links = document.querySelectorAll('a[href*=token]');"
            "for (var i = 0; i < links.length; i++) {"
            "var m2 = links[i].href.match(/token=(\\d+)/);"
            "if (m2) return m2[1];"
            "}"
            "return null;"
            "})();"
        )
        return token
    except Exception:
        return None


def navigate_to_editor(page):
    print("[编辑] 正在进入图文消息编辑器...")

    # 等待页面加载完成，尝试提取 token
    time.sleep(3)
    token = extract_token(page)
    
    # 如果首页没 token，等页面跳转后再试
    if not token:
        time.sleep(5)
        token = extract_token(page)

    if token:
        editor_url = (
            "https://mp.weixin.qq.com/cgi-bin/appmsg"
            "?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN&token=%s" % token
        )
        page.get(editor_url)
        print("[编辑] 通过 token URL 进入编辑器")
    else:
        # JS 点击导航
        page.run_js(
            "var links = document.querySelectorAll('a, button, div[role=button], span');"
            "for (var i = 0; i < links.length; i++) {"
            "var text = links[i].textContent.trim();"
            "if (text.indexOf('图文') >= 0 || text.indexOf('发表') >= 0 || text.indexOf('创作') >= 0) {"
            "links[i].click(); break;"
            "} }"
        )
        print("[编辑] JS点击导航元素")

    time.sleep(5)

    # 验证是否进入编辑器，没进去再等一轮
    current_url = page.url
    if EDITOR_URL_PATTERN not in current_url:
        print("[警告] 当前URL: %s" % current_url)
        print("[警告] 等待页面跳转...")
        time.sleep(8)
        # 再试一次从页面链接中提取 token
        token = extract_token(page)
        if token:
            editor_url = (
                "https://mp.weixin.qq.com/cgi-bin/appmsg"
                "?t=media/appmsg_edit&action=edit&type=77&lang=zh_CN&token=%s" % token
            )
            page.get(editor_url)
            time.sleep(5)
            current_url = page.url
        if EDITOR_URL_PATTERN not in current_url:
            print("[警告] 未能进入编辑器页面，继续尝试操作...")

    time.sleep(3)


# ── 填写文章内容 ──

def fill_title(page, title):
    print("[填写] 标题: %s" % title)
    selectors = ["textarea.js_title", "#title", "input#title", "input[name='title']", ".title-input input"]

    # 先尝试写入编辑器根状态，确保保存时能拿到标题
    try:
        state_set = page.run_js(
            "(function(value) {"
            "var pm = document.querySelector('.ProseMirror');"
            "var root = pm && pm.parentElement && pm.parentElement.__vue__ ? pm.parentElement.__vue__.$root : null;"
            "if (root && root.body) {"
            "  root.body.title = value;"
            "  if (root.$forceUpdate) {"
            "    try { root.$forceUpdate(); } catch (e) {}"
            "  }"
            "  return true;"
            "}"
            "return false;"
            "})",
            title,
        )
        if state_set:
            print("[填写] 标题状态已同步到 root.body.title")
    except Exception:
        pass

    for sel in selectors:
        try:
            el = page.wait.ele("css:%s" % sel, timeout=5)
            if el and str(el) != "NoneElement":
                el.click()
                time.sleep(0.3)
                el.input(title, clear=True)
                page.run_js(
                    "(function() {"
                    "var el = document.querySelector('%s');"
                    "if (!el) return false;"
                    "el.dispatchEvent(new Event('input', {bubbles: true}));"
                    "el.dispatchEvent(new Event('change', {bubbles: true}));"
                    "try { el.blur(); } catch (e) {}"
                    "return true; })()" % sel.replace("'", "\\'")
                )
                time.sleep(1)

                # 再同步一次状态，避免只改了 DOM
                try:
                    page.run_js(
                        "(function(value) {"
                        "var pm = document.querySelector('.ProseMirror');"
                        "var root = pm && pm.parentElement && pm.parentElement.__vue__ ? pm.parentElement.__vue__.$root : null;"
                        "if (root && root.body) {"
                        "  root.body.title = value;"
                        "  if (root.$forceUpdate) {"
                        "    try { root.$forceUpdate(); } catch (e) {}"
                        "  }"
                        "}"
                        "})",
                        title,
                    )
                except Exception:
                    pass

                current_value = page.run_js(
                    "(function() {"
                    "var el = document.querySelector('%s');"
                    "return el ? (el.value || '').trim() : '';"
                    "})()" % sel.replace("'", "\\'"),
                    as_expr=True,
                )
                if current_value == title:
                    time.sleep(1)
                    print("[填写] 标题填写成功 (%s)" % sel)
                    return
        except Exception:
            continue
    raise RuntimeError("找不到标题输入框")


def fill_author(page, author):
    print("[填写] 作者: %s" % author)
    selectors = ["#author", "input#author", "input[name='author']", ".author-input input"]
    for sel in selectors:
        try:
            el = page.wait.ele("css:%s" % sel, timeout=5)
            if el and str(el) != "NoneElement":
                el.click()
                time.sleep(0.3)
                el.input(author)
                time.sleep(0.5)
                print("[填写] 作者填写成功 (%s)" % sel)
                return
        except Exception:
            continue

    # 尝试展开作者区域
    try:
        page.run_js(
            "var labels = document.querySelectorAll('label, span, div');"
            "for (var i = 0; i < labels.length; i++) {"
            "if (labels[i].textContent.trim() === '作者') {"
            "labels[i].click(); break; } }"
        )
        time.sleep(1)
        for sel in selectors:
            try:
                el = page.wait.ele("css:%s" % sel, timeout=3)
                if el and str(el) != "NoneElement":
                    el.input(author)
                    return
            except Exception:
                continue
    except Exception:
        pass
    print("[警告] 未能找到作者输入框，跳过作者填写")


def fill_body_html(page, html_content):
    print("[填写] 注入正文 HTML...")
    result = None
    expected_sample = body_sample_from_html(html_content)

    # 先定位真正的正文编辑器。微信后台新版页面里标题/封面/正文都可能出现
    # contenteditable/ProseMirror，不能再直接拿 document.querySelector('.ProseMirror')。
    try:
        payload = json.dumps({"html": html_content, "expected": expected_sample})
        api_result = page.run_js(
            "(function(payload) {"
            "var value = payload.html || '';"
            "var expected = payload.expected || '';"
            "function visible(el) {"
            "  if (!el || el.offsetParent === null) return false;"
            "  var rect = el.getBoundingClientRect();"
            "  return !!rect && rect.width > 80 && rect.height > 30;"
            "}"
            "function contextText(el) {"
            "  var bits = [];"
            "  var cur = el;"
            "  for (var i = 0; cur && i < 4; i++, cur = cur.parentElement) {"
            "    if (cur.id) bits.push(cur.id);"
            "    if (cur.className) bits.push(String(cur.className));"
            "    if (cur.getAttribute) {"
            "      bits.push(cur.getAttribute('placeholder') || '');"
            "      bits.push(cur.getAttribute('aria-label') || '');"
            "      bits.push(cur.getAttribute('data-placeholder') || '');"
            "    }"
            "    bits.push((cur.textContent || '').slice(0, 80));"
            "  }"
            "  return bits.join(' ');"
            "}"
            "function scoreEditor(el) {"
            "  var rect = el.getBoundingClientRect();"
            "  var ctx = contextText(el);"
            "  var score = rect.width * rect.height;"
            "  if (el.classList && el.classList.contains('ProseMirror')) score += 1000000;"
            "  if (ctx.indexOf('正文') >= 0 || ctx.indexOf('请输入正文') >= 0) score += 500000;"
            "  if (ctx.indexOf('标题') >= 0 || ctx.indexOf('作者') >= 0 || ctx.indexOf('摘要') >= 0 || ctx.indexOf('封面') >= 0 || ctx.indexOf('留言') >= 0 || ctx.indexOf('赞赏') >= 0 || ctx.indexOf('原创') >= 0) score -= 800000;"
            "  if (rect.height < 100) score -= 500000;"
            "  return score;"
            "}"
            "function findBodyEditor() {"
            "  var selectors = ['.ProseMirror', '#edui_body_container', '.edui-body-container', '#js_editor', '#js_canvas', '[contenteditable=true]'];"
            "  var seen = [];"
            "  var candidates = [];"
            "  for (var s = 0; s < selectors.length; s++) {"
            "    var nodes = document.querySelectorAll(selectors[s]);"
            "    for (var i = 0; i < nodes.length; i++) {"
            "      var el = nodes[i];"
            "      if (seen.indexOf(el) >= 0 || !visible(el)) continue;"
            "      seen.push(el);"
            "      candidates.push({el: el, score: scoreEditor(el)});"
            "    }"
            "  }"
            "  candidates.sort(function(a, b) { return b.score - a.score; });"
            "  return candidates.length ? candidates[0].el : null;"
            "}"
            "function vueChain(el) {"
            "  var chain = [];"
            "  for (var cur = el; cur; cur = cur.parentElement) {"
            "    if (cur.__vue__) {"
            "      chain.push(cur.__vue__);"
            "      if (cur.__vue__.$parent) chain.push(cur.__vue__.$parent);"
            "      if (cur.__vue__.$root) chain.push(cur.__vue__.$root);"
            "    }"
            "  }"
            "  return chain;"
            "}"
            "function normalizedText(el) {"
            "  return ((el && (el.innerText || el.textContent)) || '').replace(/\\s+/g, '');"
            "}"
            "function dispatchEditEvents(el) {"
            "  el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertHTML', data: null}));"
            "  el.dispatchEvent(new Event('change', {bubbles: true}));"
            "}"
            "function selectContents(el) {"
            "  var range = document.createRange();"
            "  range.selectNodeContents(el);"
            "  var sel = window.getSelection();"
            "  sel.removeAllRanges();"
            "  sel.addRange(range);"
            "}"
            "var editor = findBodyEditor();"
            "if (!editor) return 'NO_BODY_EDITOR';"
            "var chain = vueChain(editor);"
            "for (var i = 0; i < chain.length; i++) {"
            "  var vm = chain[i];"
            "  if (vm && typeof vm.replaceAllContent === 'function') {"
            "    try {"
            "      vm.replaceAllContent(value);"
            "      if (typeof vm.focus === 'function') { try { vm.focus(); } catch (e1) {} }"
            "      dispatchEditEvents(editor);"
            "      if (!expected || normalizedText(editor).indexOf(expected) >= 0) return 'vue.replaceAllContent';"
            "    } catch (e2) {}"
            "  }"
            "}"
            "try {"
            "  editor.focus();"
            "  selectContents(editor);"
            "  var dt = null;"
            "  try {"
            "    dt = new DataTransfer();"
            "    dt.setData('text/html', value);"
            "    dt.setData('text/plain', value.replace(/<[^>]+>/g, ' '));"
            "    editor.dispatchEvent(new ClipboardEvent('paste', {bubbles: true, cancelable: true, clipboardData: dt}));"
            "  } catch (e3) {}"
            "  if (expected && normalizedText(editor).indexOf(expected) < 0) {"
            "    selectContents(editor);"
            "    document.execCommand('insertHTML', false, value);"
            "  }"
            "  dispatchEditEvents(editor);"
            "  if (!expected || normalizedText(editor).indexOf(expected) >= 0) return 'contenteditable.insertHTML';"
            "} catch (e4) {}"
            "try {"
            "  editor.focus();"
            "  editor.innerHTML = value;"
            "  dispatchEditEvents(editor);"
            "  if (!expected || normalizedText(editor).indexOf(expected) >= 0) return 'contenteditable.innerHTML';"
            "} catch (e5) {}"
            "return 'BODY_INSERT_UNVERIFIED';"
            "})(%s)" % payload,
            as_expr=True,
        )
        if api_result and str(api_result) not in ("NO_BODY_EDITOR", "BODY_INSERT_UNVERIFIED"):
            result = str(api_result)
            print("[填写] 正文注入验证通过 (%s)" % result)
        else:
            result = None
            print("[填写] 正文注入未通过首轮验证 (%s)" % str(api_result))
    except Exception as e:
        result = None
        print("[填写] 正文注入首轮异常: %s" % e)

    # 兼容旧版编辑器：仅在正文编辑器定位失败时使用老选择器兜底。
    if not result:
        try:
            safe_html = json.dumps(html_content)
            result = page.run_js(
                "(function() {"
                "var selectors = ['#edui_body_container', '.edui-body-container', '#js_editor', '#js_canvas'];"
                "for (var i = 0; i < selectors.length; i++) {"
                "  var el = document.querySelector(selectors[i]);"
                "  if (el) {"
                "    el.focus();"
                "    el.innerHTML = %s;"
                "    el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertHTML'}));"
                "    el.dispatchEvent(new Event('change', {bubbles: true}));"
                "    try { el.blur(); } catch (e4) {}"
                "    return selectors[i];"
                "  }"
                "}"
                "return null; })()" % safe_html
            )
        except Exception:
            result = None

    if result:
        print("[填写] 正文已注入到编辑器 (%s)" % result)
    else:
        raise RuntimeError("找不到正文编辑区域")

    time.sleep(3)

    # 再次聚焦并失焦，确保编辑器把变更写回内部状态。
    page.run_js(
        "(function(){"
        "function visible(el){ if(!el || el.offsetParent === null) return false; var r=el.getBoundingClientRect(); return r && r.width>80 && r.height>30; }"
        "var nodes = document.querySelectorAll('.ProseMirror, #edui_body_container, .edui-body-container, #js_editor, #js_canvas, [contenteditable=true]');"
        "var best = null, bestScore = -1;"
        "for (var i=0; i<nodes.length; i++){"
        "  var el=nodes[i]; if(!visible(el)) continue;"
        "  var r=el.getBoundingClientRect();"
        "  var score=r.width*r.height + ((el.classList && el.classList.contains('ProseMirror')) ? 1000000 : 0);"
        "  if(r.height < 100) score -= 500000;"
        "  if(score > bestScore){ best=el; bestScore=score; }"
        "}"
        "if (best) {"
        "  best.focus();"
        "  best.dispatchEvent(new InputEvent('input', {bubbles:true, inputType:'insertHTML'}));"
        "  best.dispatchEvent(new Event('change', {bubbles:true}));"
        "  try { best.blur(); } catch (e) {}"
        "}"
        "})();"
    )
    time.sleep(1)


def validate_article_fields(page, title, html_content, screenshot_dir):
    expected_sample = body_sample_from_html(html_content)
    expected_len = len(normalize_text(html_to_plain_text(html_content)))
    if not expected_sample or expected_len < 50:
        return

    raw_state = page.run_js(
        "(function(expected){"
        "function visible(el){ if(!el || el.offsetParent === null) return false; var r=el.getBoundingClientRect(); return r && r.width>20 && r.height>10; }"
        "function norm(text){ return (text || '').replace(/\\s+/g, ''); }"
        "function contextText(el){"
        "  var bits=[];"
        "  for(var cur=el,i=0; cur && i<4; i++,cur=cur.parentElement){"
        "    if(cur.id) bits.push(cur.id);"
        "    if(cur.className) bits.push(String(cur.className));"
        "    if(cur.getAttribute){ bits.push(cur.getAttribute('placeholder') || ''); bits.push(cur.getAttribute('aria-label') || ''); bits.push(cur.getAttribute('data-placeholder') || ''); }"
        "    bits.push((cur.textContent || '').slice(0,80));"
        "  }"
        "  return bits.join(' ');"
        "}"
        "function scoreEditor(el){"
        "  var r=el.getBoundingClientRect();"
        "  var ctx=contextText(el);"
        "  var score=r.width*r.height;"
        "  if(el.classList && el.classList.contains('ProseMirror')) score += 1000000;"
        "  if(ctx.indexOf('正文')>=0 || ctx.indexOf('请输入正文')>=0) score += 500000;"
        "  if(ctx.indexOf('标题')>=0 || ctx.indexOf('作者')>=0 || ctx.indexOf('摘要')>=0 || ctx.indexOf('封面')>=0 || ctx.indexOf('留言')>=0 || ctx.indexOf('赞赏')>=0 || ctx.indexOf('原创')>=0) score -= 800000;"
        "  if(r.height < 100) score -= 500000;"
        "  return score;"
        "}"
        "var titleValues=[];"
        "var titleSelectors=['textarea.js_title','#title','input#title','textarea#title','input[name=\"title\"]','.title-input input','textarea[placeholder*=\"标题\"]','input[placeholder*=\"标题\"]'];"
        "for(var i=0;i<titleSelectors.length;i++){"
        "  var el=document.querySelector(titleSelectors[i]);"
        "  if(el){ titleValues.push(el.value || el.innerText || el.textContent || ''); }"
        "}"
        "var nodes=document.querySelectorAll('.ProseMirror,#edui_body_container,.edui-body-container,#js_editor,#js_canvas,[contenteditable=true]');"
        "var best=null,bestScore=-999999999;"
        "for(var j=0;j<nodes.length;j++){"
        "  var n=nodes[j]; if(!visible(n)) continue;"
        "  var sc=scoreEditor(n);"
        "  if(sc>bestScore){ best=n; bestScore=sc; }"
        "}"
        "var bodyText=best ? (best.innerText || best.textContent || '') : '';"
        "var bodyNorm=norm(bodyText);"
        "var pageText=document.body ? (document.body.innerText || '') : '';"
        "var m=pageText.match(/正文字数\\s*(\\d+)/);"
        "return JSON.stringify({"
        "  titleValues:titleValues,"
        "  titleNorm:norm(titleValues.join(' ')),"
        "  bodyNorm:bodyNorm,"
        "  bodyLen:bodyNorm.length,"
        "  bodyHasExpected: bodyNorm.indexOf(expected)>=0,"
        "  titleHasExpected: norm(titleValues.join(' ')).indexOf(expected)>=0,"
        "  editorScore:bestScore,"
        "  bodyCounter:m ? parseInt(m[1],10) : null"
        "});"
        "})(%s)" % json.dumps(expected_sample),
        as_expr=True,
    )

    try:
        state = json.loads(raw_state or "{}")
    except Exception:
        state = {}

    title_values = [v for v in state.get("titleValues", []) if v]
    title_has_body = bool(state.get("titleHasExpected"))
    body_has_expected = bool(state.get("bodyHasExpected"))
    body_len = int(state.get("bodyLen") or 0)
    body_counter = state.get("bodyCounter")

    if title_has_body:
        raise_automation_step_error(
            page,
            "校验标题正文",
            screenshot_dir,
            "检测到正文片段进入了标题输入框，已停止保存。标题值: %s" % " | ".join(title_values[:2]),
        )

    min_body_len = min(120, max(40, expected_len // 20))
    counter_ok = isinstance(body_counter, int) and body_counter >= min_body_len
    if not body_has_expected and body_len < min_body_len and not counter_ok:
        raise_automation_step_error(
            page,
            "校验正文内容",
            screenshot_dir,
            "正文没有成功进入正文编辑区（正文区域长度=%d，正文字数=%s），已停止保存。"
            % (body_len, body_counter if body_counter is not None else "-"),
        )

    print("[校验] 标题/正文位置校验通过（正文区域长度=%d，正文字数=%s）" % (
        body_len,
        body_counter if body_counter is not None else "-",
    ))


def upload_cover(page, cover_path):
    """上传封面图到微信公众号编辑器。

    微信编辑器封面上传的正确路径:
    点击封面「从图片库选择」(.js_imagedialog) → 弹出图片库对话框 →
    对话框内点击「上传文件」按钮触发 file input → 等上传完 → 选图 →
    点击「下一步」→ 如出现裁剪/确认页再点「确定」。

    关键: 页面有两个 input[type=file]:
      - 第1个: 编辑器工具栏的(在 .js_img_dropdown_menu 里)→ 绝不能碰!
      - 第2个: 图片库对话框的(在 .js_upload_btn_container 里)→ 这个才是封面的
    打开对话框后第2个才出现, 用 page.eles() 取最后一个即可。
    """
    print("[封面] 上传封面图: %s" % cover_path)
    abs_path = os.path.abspath(cover_path)
    if not os.path.exists(abs_path):
        raise FileNotFoundError("封面图不存在: %s" % abs_path)

    # ── Step 1: 打开图片库对话框 ──
    opened = page.run_js(
        "(function(){"
        "var btn=document.querySelector('#js_cover_area .js_imagedialog');"
        "if(btn){btn.click();return true;}"
        "return false;"
        "})();"
    )
    if not opened:
        print("[封面] 未找到封面图片库按钮，跳过。")
        return
    print("[封面] 已打开图片库对话框，等待加载...")
    time.sleep(3)

    # ── Step 2: 注入文件到对话框的上传 file input ──
    # 对话框打开后，页面会有 2 个 input[type=file]
    # 第1个是编辑器工具栏的(不能碰)，第2个是对话框的
    uploaded = False
    try:
        # 方法A: 用 ruyiPage 获取所有 file input, 取最后一个
        all_inputs = page.eles("css:input[type='file']")
        if all_inputs and len(all_inputs) >= 2:
            dialog_input = all_inputs[-1]
            print("[封面] 找到 %d 个 file input, 使用最后一个 (对话框的)" % len(all_inputs))
            dialog_input.input(abs_path)
            uploaded = True
            print("[封面] 文件已注入到图片库上传入口")
        elif all_inputs and len(all_inputs) == 1:
            # 只有一个? 可能对话框还没完全加载, 等3秒再试
            print("[封面] 只检测到1个 file input (可能是编辑器的), 等待对话框加载...")
            time.sleep(3)
            all_inputs = page.eles("css:input[type='file']")
            if all_inputs and len(all_inputs) >= 2:
                dialog_input = all_inputs[-1]
                dialog_input.input(abs_path)
                uploaded = True
                print("[封面] 重试成功，文件已注入")
            else:
                print("[封面] 仍然只有 %d 个 file input, 对话框可能未正确打开" % len(all_inputs))
        else:
            print("[封面] 未找到任何 file input")
    except Exception as e:
        print("[封面] ruyiPage 注入异常: %s, 尝试 JS 方式..." % e)

    # 方法B: 如果 ruyiPage 方式失败，直接用 JS 的 "上传文件" 按钮点击来触发
    if not uploaded:
        print("[封面] 尝试点击「上传文件」按钮触发上传...")
        try:
            # 点击 "上传文件" 按钮会触发 file input 的 click
            # 但 file input 的 click 在浏览器安全限制下只能由用户手势触发
            # 所以 ruyiPage 的 .input() 才是正确方式
            # 这里再试一次 ruyiPage，用更宽松的超时
            el = page.wait.ele("text:上传文件", timeout=5)
            if el and str(el) != "NoneElement":
                # 找到按钮后，找它旁边的 file input
                file_input = el.parent().ele("css:input[type='file']")
                if file_input and str(file_input) != "NoneElement":
                    file_input.input(abs_path)
                    uploaded = True
                    print("[封面] 通过「上传文件」按钮定位成功注入")
        except Exception as e2:
            print("[封面] 备用方式也失败: %s" % e2)

    if not uploaded:
        print("[警告] 未能自动上传封面图，请手动上传后点下一步/确定。")
        print("[封面] 等待60秒供手动操作...")
        time.sleep(60)
        _confirm_cover_dialog(page)
        return

    # ── Step 3: 等待上传完成 ──
    print("[封面] 等待图片上传到微信服务器...")
    upload_ok = _wait_for_upload(page)
    if not upload_ok:
        print("[警告] 上传超时，尝试继续...")

    time.sleep(2)

    # ── Step 4: 选中图片 ──
    selected = _select_first_image(page)
    if selected:
        print("[封面] 已选中图片")
    time.sleep(1)

    # ── Step 5: 下一步 / 确定 ──
    _confirm_cover_dialog(page)

    # ── Step 6: 验证 ──
    time.sleep(3)
    has_cover = page.run_js(
        "(function(){"
        "var area=document.querySelector('#js_cover_area');"
        "if(!area)return false;"
        "var img=area.querySelector('img');"
        "if(img&&img.src&&img.src.indexOf('data:')<0&&img.src.length>50)return true;"
        "return false;"
        "})();"
    )
    if has_cover:
        print("[封面] 封面设置成功!")
    else:
        print("[封面] 未能确认封面是否成功，请手动检查。")


def _wait_for_upload(page, max_wait=60):
    """等待图片库对话框内图片上传完成。返回 True/False。"""
    for i in range(max_wait // 2):
        time.sleep(2)
        r = page.run_js(
            "(function(){"
            "var dialogs=document.querySelectorAll('.weui-desktop-dialog');"
            "var dialog=null;"
            "for(var d=0;d<dialogs.length;d++){"
            "  if(dialogs[d].style.display!=='none'&&getComputedStyle(dialogs[d]).display!=='none'"
            "    &&dialogs[d].textContent.indexOf('选择图片')>=0){dialog=dialogs[d];break;}"
            "}"
            "if(!dialog)return 'no_dialog';"
            # 找图片缩略图或上传完成的标志
            "var imgs=dialog.querySelectorAll('img[src*=mmbiz]');"
            "if(imgs.length>0)return 'found_imgs';"
            # 检查有没有进度条
            "var uploading=dialog.querySelectorAll('[class*=uploading],[class*=progress]');"
            "var stillUploading=false;"
            "for(var u=0;u<uploading.length;u++){"
            "  if(getComputedStyle(uploading[u]).display!=='none')stillUploading=true;"
            "}"
            "if(stillUploading)return 'uploading';"
            # 有图片列表项 (可能是刚上传完还没加载 src)
            "var items=dialog.querySelectorAll('[class*=media_item],[class*=img_item],[class*=pic_item]');"
            "if(items.length>0)return 'found_items';"
            "return 'waiting';"
            "})();"
        )
        if r in ("found_imgs", "found_items"):
            print("[封面] 图片已上传完成")
            return True
        elif r == "no_dialog":
            print("[封面] 对话框已关闭")
            return True
        elif i % 3 == 2:
            print("[封面] 等待上传中... (%ds)" % ((i + 1) * 2))
    return False


def _select_first_image(page):
    """在图片库对话框中选中第一张图片。"""
    return page.run_js(
        "(function(){"
        "var dialogs=document.querySelectorAll('.weui-desktop-dialog');"
        "var dialog=null;"
        "for(var d=0;d<dialogs.length;d++){"
        "  if(dialogs[d].style.display!=='none'&&getComputedStyle(dialogs[d]).display!=='none'"
        "    &&dialogs[d].textContent.indexOf('选择图片')>=0){dialog=dialogs[d];break;}"
        "}"
        "if(!dialog)return false;"
        # 找图片项(兼容新版/旧版多种选择器)
        "var sels=['.media_list_item','.img_item','[class*=media_item]','[class*=pic_item]',"
        "'.weui-desktop-img-picker__item','[class*=picker] [class*=item]','li'];"
        "for(var s=0;s<sels.length;s++){"
        "  var items=dialog.querySelectorAll(sels[s]);"
        "  if(items.length>0){"
        "    var item=items[0];"
        "    item.scrollIntoView({block:'center'});"
        "    var target=item.querySelector('img,label,[role=button],.icon_mask,.js_list_checkbox')||item;"
        "    ['mouseenter','mousedown','mouseup','click'].forEach(function(evt){"
        "      try{target.dispatchEvent(new MouseEvent(evt,{bubbles:true,cancelable:true,view:window}))}catch(e){}"
        "    });"
        "    try{target.click()}catch(e){}"
        "    return true;"
        "  }"
        "}"
        "return false;"
        "})();"
    )


def _click_cover_dialog_action(page, labels):
    """点击当前可见封面对话框里的按钮，优先只点可用按钮。"""
    js_labels = json.dumps(list(labels), ensure_ascii=False)
    return page.run_js(
        "(function(labels){"
        "var dialogs=document.querySelectorAll('.weui-desktop-dialog');"
        "var dialog=null;"
        "for(var d=dialogs.length-1;d>=0;d--){"
        "  var candidate=dialogs[d];"
        "  if(candidate.style.display==='none'||getComputedStyle(candidate).display==='none')continue;"
        "  var text=(candidate.textContent||'').trim();"
        "  if(text.indexOf('选择图片')>=0||text.indexOf('裁剪')>=0||text.indexOf('封面')>=0){dialog=candidate;break;}"
        "}"
        "if(!dialog)return 'no_dialog';"
        "var btns=dialog.querySelectorAll('button,.weui-desktop-btn,[role=button]');"
        "function isDisabled(btn){"
        "  if(!btn)return true;"
        "  if(btn.disabled)return true;"
        "  if(btn.getAttribute('disabled')!==null)return true;"
        "  if(btn.getAttribute('aria-disabled')==='true')return true;"
        "  var cls=(btn.className||'').toString();"
        "  if(cls.indexOf('disabled')>=0)return true;"
        "  return false;"
        "}"
        "for(var l=0;l<labels.length;l++){"
        "  var label=labels[l];"
        "  for(var i=0;i<btns.length;i++){"
        "    var btn=btns[i];"
        "    var text=(btn.textContent||'').trim();"
        "    if(text!==label&&text.indexOf(label)<0)continue;"
        "    if(isDisabled(btn))return 'disabled:'+text;"
        "    btn.scrollIntoView({block:'center'});"
        "    try{btn.click()}catch(e){}"
        "    return 'clicked:'+text;"
        "  }"
        "}"
        "var texts=[];"
        "for(var j=0;j<btns.length;j++){"
        "  var name=(btns[j].textContent||'').trim();"
        "  if(name)texts.push(name+(isDisabled(btns[j])?'[disabled]':''));"
        "}"
        "return texts.length?'buttons:'+texts.join('|'):'no_buttons';"
        "})(%s);" % js_labels,
        as_expr=True
    )


def _cancel_cover_dialog(page):
    """兜底关闭封面对话框。"""
    page.run_js(
        "(function(){"
        "var btns=document.querySelectorAll('.weui-desktop-dialog .weui-desktop-btn_default, .weui-desktop-dialog button, .weui-desktop-dialog [role=button]');"
        "for(var i=btns.length-1;i>=0;i--){"
        "  var btn=btns[i];"
        "  var dialog=btn.closest('.weui-desktop-dialog');"
        "  if(!dialog)continue;"
        "  if(dialog.style.display==='none'||getComputedStyle(dialog).display==='none')continue;"
        "  var text=(btn.textContent||'').trim();"
        "  if(text==='取消'||text==='关闭'){"
        "    try{btn.click()}catch(e){}"
        "    break;"
        "  }"
        "}"
        "})();"
    )
    time.sleep(1)


def _confirm_cover_dialog(page, max_wait=20):
    """完成封面选择流程，兼容“下一步 → 确认/确定”和单步确认。"""
    actions = ("下一步", "确认", "确定", "完成", "使用")
    clicked_any = False

    for i in range(max_wait):
        result = _click_cover_dialog_action(page, actions)
        if result == "no_dialog":
            if clicked_any:
                print("[封面] 对话框已关闭")
            return clicked_any
        if result and str(result).startswith("clicked:"):
            label = str(result).split(":", 1)[1]
            print("[封面] 已点击 %s" % label)
            clicked_any = True
            time.sleep(2)
            continue
        if result and str(result).startswith("disabled:"):
            label = str(result).split(":", 1)[1]
            if label.find("下一步") >= 0 and i < max_wait - 1:
                _select_first_image(page)
            if i % 3 == 2:
                print("[封面] 按钮暂不可用，继续等待: %s" % label)
            time.sleep(1)
            continue
        if i % 3 == 2:
            print("[封面] 等待封面对话框动作可用: %s" % result)
        time.sleep(1)

    print("[警告] 未能自动完成封面对话框，尝试关闭。")
    _cancel_cover_dialog(page)
    return clicked_any


def fill_digest(page, digest):
    if not digest:
        print("[填写] 未提供摘要，跳过。")
        return
    print("[填写] 摘要: %s..." % digest[:30])

    # 点击展开摘要
    try:
        page.run_js(
            "var links = document.querySelectorAll('a, span, label, div');"
            "for (var i = 0; i < links.length; i++) {"
            "var text = links[i].textContent.trim();"
            "if (text === '填写摘要' || text.indexOf('摘要') >= 0) {"
            "links[i].click(); break; } }"
        )
        time.sleep(1)
    except Exception:
        pass

    selectors = ["#digest", "textarea#digest", "textarea[name='digest']", ".digest-input textarea"]
    for sel in selectors:
        try:
            el = page.wait.ele("css:%s" % sel, timeout=5)
            if el and str(el) != "NoneElement":
                el.click()
                time.sleep(0.3)
                el.input(digest)
                time.sleep(0.5)
                print("[填写] 摘要填写成功")
                return
        except Exception:
            continue
    print("[警告] 未能找到摘要输入框，跳过摘要填写")


# ── 保存草稿 ──

def save_draft(page, screenshot_dir="/tmp"):
    print("[保存] 正在保存草稿...")

    saved = False

    # 先触发一次失焦，让标题/摘要/正文的最近编辑状态提交
    try:
        page.run_js(
            "(function(){"
            "if(document.activeElement && document.activeElement.blur){"
            "  try{document.activeElement.blur()}catch(e){}"
            "}"
            "})();"
        )
        time.sleep(1)
    except Exception:
        pass

    # 优先点击底部真正的「保存为草稿」主按钮，避免误点其他“保存”
    exact_result = page.run_js(
        "(function(){"
        "function visible(el){"
        "  if(!el) return false;"
        "  if(el.disabled) return false;"
        "  if(el.getAttribute('disabled') !== null) return false;"
        "  if(el.getAttribute('aria-disabled') === 'true') return false;"
        "  if(el.offsetParent === null) return false;"
        "  var cls=(el.className||'').toString();"
        "  if(cls.indexOf('disabled')>=0) return false;"
        "  return true;"
        "}"
        "var btn=document.querySelector('#js_submit');"
        "if(btn && visible(btn)){btn.click();return 'clicked:#js_submit';}"
        "var buttons=document.querySelectorAll('button,a,span,div[role=button]');"
        "for(var i=0;i<buttons.length;i++){"
        "  var text=(buttons[i].textContent||'').replace(/\\s+/g,' ').trim();"
        "  if((text==='保存为草稿'||text==='保存草稿'||text==='保存') && visible(buttons[i])){"
        "    buttons[i].click();"
        "    return 'clicked:' + text;"
        "  }"
        "}"
        "return 'not_found';"
        "})();",
        as_expr=True
    )
    if exact_result and "clicked" in str(exact_result):
        saved = True
        print("[保存] 点击保存按钮 (%s)" % exact_result)

    # 兜底：尝试 CSS 选择器
    if not saved:
        save_selectors = [
            "#js_submit", "button.js_submit", "#js_send",
            ".btn-primary", ".weui-desktop-btn_primary",
        ]
        for sel in save_selectors:
            try:
                btn = page.wait.ele("css:%s" % sel, timeout=3)
                if btn and str(btn) != "NoneElement":
                    state = page.run_js(
                        "(function(){"
                        "var btn=document.querySelector('%s');"
                        "if(!btn) return false;"
                        "if(btn.disabled) return false;"
                        "if(btn.getAttribute('disabled') !== null) return false;"
                        "if(btn.getAttribute('aria-disabled') === 'true') return false;"
                        "if(btn.offsetParent === null) return false;"
                        "var cls=(btn.className||'').toString();"
                        "if(cls.indexOf('disabled')>=0) return false;"
                        "return true;"
                        "})()" % sel.replace("'", "\\'"),
                        as_expr=True,
                    )
                    if not state:
                        continue
                    btn.click()
                    saved = True
                    print("[保存] 点击保存按钮 (%s)" % sel)
                    break
            except Exception:
                continue

    if not saved:
        ss_path = os.path.join(screenshot_dir, "save_draft_failed.png")
        try:
            page.screenshot(ss_path)
        except Exception:
            pass
        raise RuntimeError("找不到保存按钮。")

    print("[保存] 等待保存完成...")
    time.sleep(5)

    # 检查是否有错误提示
    error_text = page.run_js(
        "var alerts = document.querySelectorAll('.weui-desktop-toast, .dialog, .alert, .error');"
        "var err = null;"
        "for (var i = 0; i < alerts.length; i++) {"
        "if (alerts[i].offsetParent !== null && alerts[i].textContent.indexOf('失败') >= 0) {"
        "err = alerts[i].textContent.trim(); break; } }"
        "err;",
        as_expr=True
    )
    if error_text:
        ss_path = os.path.join(screenshot_dir, "save_draft_error.png")
        try:
            page.screenshot(ss_path)
        except Exception:
            pass
        raise RuntimeError("保存时出现错误: %s" % error_text)

    print("[保存] 草稿保存成功!")


def build_xls_manifest(title, description, image_paths, channel_id=None):
    return {
        "kind": "xls-publish",
        "channel_id": channel_id or "",
        "title": title,
        "description": description,
        "images": [
            {
                "source": path,
                "basename": os.path.basename(path),
                "sha256": compute_file_sha256(path),
            }
            for path in image_paths
        ],
    }


def _count_xls_thumbnail_candidates(page):
    try:
        count = page.run_js(
            "(function(){"
            "var imgs = document.querySelectorAll('img');"
            "var count = 0;"
            "for (var i = 0; i < imgs.length; i++) {"
            "  var img = imgs[i];"
            "  var src = (img.currentSrc || img.src || '');"
            "  if (src.indexOf('mmbiz') >= 0 || src.indexOf('blob:') === 0 || src.indexOf('data:') === 0) {"
            "    count++;"
            "  }"
            "}"
            "return count;"
            "})();",
            as_expr=True,
        )
        return int(count or 0)
    except Exception:
        return 0


def _has_xls_progress_ratio(page, expected_count):
    try:
        return bool(
            page.run_js(
                "(function(){"
                "var body = document.body ? (document.body.innerText || '') : '';"
                "return body.indexOf('%s') >= 0;"
                "})();" % ("%d/%d" % (expected_count, expected_count)),
                as_expr=True,
            )
        )
    except Exception:
        return False


def _hover_text_contains(page, target_text, timeout=5):
    try:
        el = page.wait.ele("text:%s" % target_text, timeout=timeout)
        if el and str(el) != "NoneElement":
            el.hover()
            return True
    except Exception:
        pass

    try:
        return bool(
            page.run_js(
                "(function(target){"
                "function visible(el){"
                "  if(!el) return false;"
                "  if(el.offsetParent === null) return false;"
                "  var rect = el.getBoundingClientRect();"
                "  if(!rect || rect.width <= 0 || rect.height <= 0) return false;"
                "  return true;"
                "}"
                "var targetKey = target.replace(/\\s+/g, '');"
                "var nodes = document.querySelectorAll('*');"
                "for (var i = 0; i < nodes.length; i++) {"
                "  var el = nodes[i];"
                "  if (!visible(el)) continue;"
                "  var text = (el.textContent || '').replace(/\\s+/g, ' ').trim();"
                "  var textKey = text.replace(/\\s+/g, '');"
                "  if (text.indexOf(target) >= 0 || textKey.indexOf(targetKey) >= 0) {"
                "    var over = document.createEvent('MouseEvents');"
                "    over.initEvent('mouseover', true, true);"
                "    el.dispatchEvent(over);"
                "    var enter = document.createEvent('MouseEvents');"
                "    enter.initEvent('mouseenter', true, true);"
                "    el.dispatchEvent(enter);"
                "    return true;"
                "  }"
                "}"
                "return false;"
                "})(%s)"
                % json.dumps(target_text),
                as_expr=True,
            )
        )
    except Exception:
        return False


def _click_text_contains(page, target_text, timeout=5):
    try:
        el = page.wait.ele("text:%s" % target_text, timeout=timeout)
        if el and str(el) != "NoneElement":
            el.click()
            return True
    except Exception:
        pass

    try:
        return bool(
            page.run_js(
                "(function(target){"
                "function visible(el){"
                "  if(!el) return false;"
                "  if(el.offsetParent === null) return false;"
                "  var rect = el.getBoundingClientRect();"
                "  if(!rect || rect.width <= 0 || rect.height <= 0) return false;"
                "  return true;"
                "}"
                "var targetKey = target.replace(/\\s+/g, '');"
                "var nodes = document.querySelectorAll('*');"
                "for (var i = 0; i < nodes.length; i++) {"
                "  var el = nodes[i];"
                "  if (!visible(el)) continue;"
                "  var text = (el.textContent || '').replace(/\\s+/g, ' ').trim();"
                "  var textKey = text.replace(/\\s+/g, '');"
                "  if (text.indexOf(target) >= 0 || textKey.indexOf(targetKey) >= 0) {"
                "    try { el.click(); } catch (e) {}"
                "    return true;"
                "  }"
                "}"
                "return false;"
                "})(%s)"
                % json.dumps(target_text),
                as_expr=True,
            )
        )
    except Exception:
        return False


def _fill_text_field_by_keywords(page, field_name, value, selectors, keywords, screenshot_dir):
    def attempt():
        for sel in selectors:
            try:
                el = page.wait.ele("css:%s" % sel, timeout=4)
                if el and str(el) != "NoneElement":
                    el.click()
                    time.sleep(0.2)
                    el.input(value, clear=True)
                    time.sleep(0.5)
                    print("[填写] %s填写成功 (%s)" % (field_name, sel))
                    return True
            except Exception:
                continue

        try:
            result = page.run_js(
                "(function(value){"
                "function visible(el){"
                "  if(!el) return false;"
                "  if(el.offsetParent === null) return false;"
                "  var rect = el.getBoundingClientRect();"
                "  if(!rect || rect.width <= 0 || rect.height <= 0) return false;"
                "  return true;"
                "}"
                "function haystack(el){"
                "  var bits = [];"
                "  if (el.id) bits.push(el.id);"
                "  if (el.name) bits.push(el.name);"
                "  if (el.placeholder) bits.push(el.placeholder);"
                "  if (el.getAttribute && el.getAttribute('aria-label')) bits.push(el.getAttribute('aria-label'));"
                "  if (el.labels && el.labels.length) {"
                "    for (var i = 0; i < el.labels.length; i++) {"
                "      bits.push(el.labels[i].textContent || '');"
                "    }"
                "  }"
                "  var parent = el.parentElement;"
                "  if (parent) bits.push(parent.textContent || '');"
                "  if (parent && parent.parentElement) bits.push(parent.parentElement.textContent || '');"
                "  return bits.join(' ');"
                "}"
                "function setValue(el, text){"
                "  if (!el) return false;"
                "  if (el.isContentEditable) {"
                "    el.focus();"
                "    el.innerText = text;"
                "    el.dispatchEvent(new Event('input', {bubbles: true}));"
                "    el.dispatchEvent(new Event('change', {bubbles: true}));"
                "    try { el.blur(); } catch (e) {}"
                "    return true;"
                "  }"
                "  el.focus();"
                "  el.value = text;"
                "  el.dispatchEvent(new Event('input', {bubbles: true}));"
                "  el.dispatchEvent(new Event('change', {bubbles: true}));"
                "  try { el.blur(); } catch (e) {}"
                "  return true;"
                "}"
                "var keywords = %s;"
                "var els = document.querySelectorAll('input, textarea, [contenteditable=\"true\"]');"
                "for (var i = 0; i < els.length; i++) {"
                "  var el = els[i];"
                "  if (!visible(el)) continue;"
                "  var text = haystack(el);"
                "  for (var j = 0; j < keywords.length; j++) {"
                "    if (text.indexOf(keywords[j]) >= 0) {"
                "      if (setValue(el, value)) return 'matched:' + keywords[j];"
                "    }"
                "  }"
                "}"
                "return 'not_found';"
                "})(%s)"
                % (json.dumps(keywords), json.dumps(value)),
                as_expr=True,
            )
            if result and str(result).startswith("matched:"):
                print("[填写] %s填写成功 (%s)" % (field_name, result))
                return True
        except Exception:
            pass
        return False

    if attempt():
        return

    raise_automation_step_error(
        page,
        "定位%s输入框" % field_name,
        screenshot_dir,
        "没找到%s输入框。脚本已停止，请根据截图检查页面结构。" % field_name,
    )

    if attempt():
        return

    raise RuntimeError("找不到%s输入框" % field_name)


def navigate_to_xls_editor(page, screenshot_dir):
    print("[编辑] 正在进入小绿书贴图编辑器...")

    time.sleep(3)
    token = extract_token(page)
    if not token:
        time.sleep(5)
        token = extract_token(page)

    if not token:
        raise_automation_step_error(
            page,
            "获取token",
            screenshot_dir,
            "没拿到公众号后台 token，没法进入小绿书贴图编辑页。脚本已停止，请确认登录态或页面结构。",
        )
        token = extract_token(page)
        if not token:
            raise RuntimeError("无法获取公众号后台 token")

    editor_url = (
        "https://mp.weixin.qq.com/cgi-bin/appmsg"
        "?t=media/appmsg_edit_v2&action=edit&isNew=1&type=10&createType=8&token=%s&lang=zh_CN"
        % token
    )
    page.get(editor_url)
    print("[编辑] 已打开小绿书贴图编辑页")
    time.sleep(5)

    ready = _is_xls_editor_ready(page)
    if not ready:
        raise_automation_step_error(
            page,
            "确认小绿书编辑器",
            screenshot_dir,
            "已经打开页面，但没看到小绿书贴图编辑器的关键区域。脚本已停止，请根据截图检查页面结构。",
        )
        ready = _is_xls_editor_ready(page)

    if not ready:
        raise RuntimeError("未能进入小绿书贴图编辑器")

    print("[编辑] 已确认进入小绿书贴图编辑器")


def _is_xls_editor_ready(page):
    try:
        ready = page.run_js(
            "(function(){"
            "var body = document.body ? (document.body.innerText || '') : '';"
            "return body.indexOf('选择或拖拽图片到此处') >= 0 || body.indexOf('本地上传') >= 0 || body.indexOf('保存为草稿') >= 0 || window.location.href.indexOf('appmsg_edit_v2') >= 0;"
            "})();",
            as_expr=True,
        )
        return bool(ready)
    except Exception:
        return False


def upload_xls_images(page, image_paths, screenshot_dir):
    image_paths = resolve_input_files(image_paths, label="图片")
    baseline = _count_xls_thumbnail_candidates(page)
    print("[贴图] 当前可见图片候选数: %d" % baseline)

    selector_text = "选择或拖拽图片到此处"
    upload_text = "本地上传"

    def find_file_input(max_wait=0):
        tries = max(1, max_wait)
        for _ in range(tries):
            inputs = page.eles("css:input[type='file']")
            if inputs and len(inputs) > 0:
                return inputs[-1]
            time.sleep(1)
        return None

    def attempt_upload():
        file_input = find_file_input(max_wait=1)
        if file_input:
            file_input.input(image_paths)
            print("[贴图] 已通过现有 file input 注入 %d 张图片" % len(image_paths))
            return True

        if not _hover_text_contains(page, selector_text, timeout=4):
            return False
        time.sleep(1)

        file_input = find_file_input(max_wait=4)
        if not file_input:
            if _click_text_contains(page, upload_text, timeout=3):
                time.sleep(1)
                file_input = find_file_input(max_wait=6)
        if not file_input:
            return False

        file_input.input(image_paths)
        print("[贴图] 已注入 %d 张图片" % len(image_paths))
        return True

    if not attempt_upload():
        raise_automation_step_error(
            page,
            "上传贴图图片",
            screenshot_dir,
            "没能完成“悬停图片选择器 → 本地上传 → 选择本地图片”的步骤。脚本已停止，请根据截图检查页面结构。",
        )
        if not attempt_upload():
            raise RuntimeError("未能完成图片上传")

    expected_count = baseline + len(image_paths)
    for i in range(30):
        current = _count_xls_thumbnail_candidates(page)
        if current >= expected_count or _has_xls_progress_ratio(page, len(image_paths)):
            print("[贴图] 图片已正常展示 (%d/%d)" % (current, expected_count))
            return
        if i % 5 == 4:
            print("[贴图] 等待图片正常展示... 当前=%d 目标>=%d" % (current, expected_count))
        time.sleep(2)

    current = _count_xls_thumbnail_candidates(page)
    print("[贴图] 图片展示未完全确认，继续执行后续步骤 (%d/%d)" % (current, expected_count))


def fill_xls_title(page, title, screenshot_dir):
    _fill_text_field_by_keywords(
        page,
        "标题",
        title,
        [
            "textarea[placeholder*='标题']",
            "input[placeholder*='标题']",
            "textarea[name='title']",
            "input[name='title']",
            "#title",
            "textarea.js_title",
        ],
        ["标题", "题目", "名称"],
        screenshot_dir,
    )


def fill_xls_description(page, description, screenshot_dir):
    _fill_text_field_by_keywords(
        page,
        "描述信息",
        description,
        [
            "textarea[placeholder*='描述']",
            "input[placeholder*='描述']",
            "textarea[placeholder*='简介']",
            "textarea[name='description']",
            "textarea[name='desc']",
            "#description",
            "#digest",
            "textarea#digest",
        ],
        ["描述", "描述信息", "简介"],
        screenshot_dir,
    )


def save_xls_draft(page, screenshot_dir):
    try:
        save_draft(page, screenshot_dir=screenshot_dir)
        return
    except RuntimeError as exc:
        raise_automation_step_error(
            page,
            "保存草稿",
            screenshot_dir,
            "没能直接点到“保存为草稿”。脚本已停止，请根据截图检查保存按钮。",
        )
        save_draft(page, screenshot_dir=screenshot_dir)


def do_xls_publish(args):
    from ruyipage import launch

    manifest_tmp = None
    try:
        resolved = merge_channel_publish_args(args)
        user_dir = resolved["user_dir"]
        final_account = resolved["account"]
        ensure_dir(user_dir)
        print("[配置] 用户数据目录: %s" % user_dir)
        if resolved["channel_id"]:
            print(
                "[配置] 发布频道: %s (persona=%s, archive_account=%s)"
                % (
                    resolved["channel_id"],
                    resolved["channel"].get("persona") or "-",
                    final_account,
                )
            )

        image_paths = resolve_input_files(args.images, label="图片")
        if not image_paths:
            raise ValueError("请通过 --images 指定至少一张图片")

        article_dir = resolve_article_dir(account=final_account, title=args.title)
        manifest = build_xls_manifest(
            title=args.title,
            description=args.description,
            image_paths=image_paths,
            channel_id=resolved.get("channel_id"),
        )

        if not args.force:
            import tempfile

            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
                write_json_file(handle.name, manifest)
                manifest_tmp = handle.name
            extra_comparisons = [
                (src_path, os.path.join(article_dir, os.path.basename(src_path)))
                for src_path in image_paths
            ]
            extra_comparisons.append((manifest_tmp, os.path.join(article_dir, "xls_manifest.json")))
            if is_probable_duplicate_publish(
                article_dir,
                article_html_path=None,
                extra_comparisons=extra_comparisons,
            ):
                print("[跳过] 检测到 10 分钟内相同小绿书贴图已保存到草稿箱，跳过本次重复发布。")
                print("[跳过] 如需强制重新发布，请追加 --force。")
                try:
                    if manifest_tmp and os.path.exists(manifest_tmp):
                        os.unlink(manifest_tmp)
                except Exception:
                    pass
                return

        print("[启动] 正在启动 Firefox...")
        page = launch(user_dir=user_dir, headless=False)
        ss_dir = DEFAULT_SCREENSHOTS_DIR
        ensure_dir(ss_dir)

        print("[导航] 正在打开微信公众号后台首页...")
        page.get(WECHAT_MP_URL)
        time.sleep(3)

        if check_already_logged_in(page):
            print("[登录] 已登录（使用已保存的登录态）")
        else:
            print("[登录] 未登录，请扫描二维码...")
            wait_for_login(page)

        navigate_to_xls_editor(page, ss_dir)
        upload_xls_images(page, image_paths, ss_dir)
        fill_xls_title(page, args.title, ss_dir)
        fill_xls_description(page, args.description, ss_dir)

        ss_path = os.path.join(ss_dir, "xls_draft_%d.png" % int(time.time()))
        try:
            page.screenshot(ss_path)
            print("[截图] 操作完成截图: %s" % ss_path)
        except Exception as e:
            print("[警告] 截图失败: %s" % e)

        save_xls_draft(page, screenshot_dir=ss_dir)

        print("\n" + "=" * 50)
        print("小绿书贴图已保存到草稿箱。")
        print("用户目录: %s" % user_dir)
        print("[归档] 产物目录: %s" % article_dir)

        if has_current_artifacts(article_dir):
            new_ver, moved = archive_current_version(article_dir)
            print("[归档] 旧版已归档到 versions/v%d/ (%s)" % (new_ver, ", ".join(moved) if moved else "无文件"))

        copy_artifacts(
            article_dir,
            article_html_path=None,
            cover_path=None,
            final_md_path=None,
            extra_sources=image_paths,
        )
        write_json_file(os.path.join(article_dir, "xls_manifest.json"), manifest)
        print("[归档] 已保存: %s" % ", ".join([os.path.basename(p) for p in image_paths]))

        record_publish(article_dir, args.title, final_account, "小绿书贴图保存到草稿箱")
        print("[归档] publish.json 已更新")

        cleanup_old_versions(article_dir)
        print("=" * 50)
    finally:
        if manifest_tmp and os.path.exists(manifest_tmp):
            try:
                os.unlink(manifest_tmp)
            except Exception:
                pass


# ── 主流程 ──

def do_publish(args):
    from ruyipage import launch

    resolved = merge_channel_publish_args(args)
    user_dir = resolved["user_dir"]
    final_account = resolved["account"]
    ensure_dir(user_dir)
    print("[配置] 用户数据目录: %s" % user_dir)
    if resolved["channel_id"]:
        print(
            "[配置] 发布频道: %s (persona=%s, archive_account=%s)"
            % (
                resolved["channel_id"],
                resolved["channel"].get("persona") or "-",
                final_account,
            )
        )

    if not args.article:
        raise ValueError("请通过 --article 指定文章HTML文件")
    article_html = read_file_content(args.article)
    print("[配置] 文章文件: %s (%d 字符)" % (args.article, len(article_html)))

    cover_path = resolve_cover_path(args.cover)
    article_dir = resolve_article_dir(account=final_account, title=args.title)

    if not args.force and is_probable_duplicate_publish(
        article_dir,
        article_html_path=args.article,
        cover_path=cover_path,
        final_md_path=args.source,
    ):
        print("[跳过] 检测到 10 分钟内相同产物已发布到草稿箱，跳过本次重复发布。")
        print("[跳过] 如需强制重新发布，请追加 --force。")
        return

    # 启动浏览器
    print("[启动] 正在启动 Firefox...")
    page = launch(user_dir=user_dir, headless=False)

    try:
        # 1. 导航到微信公众号
        print("[导航] 正在打开微信公众号后台...")
        page.get(WECHAT_MP_URL)
        time.sleep(3)

        # 2. 检查登录状态
        if check_already_logged_in(page):
            print("[登录] 已登录（使用已保存的登录态）")
        else:
            print("[登录] 未登录，请扫描二维码...")
            wait_for_login(page)

        # 3. 进入编辑器
        navigate_to_editor(page)

        # 4. 填写标题
        if args.title:
            fill_title(page, args.title)

        # 5. 填写作者（优先 CLI 参数，fallback 到 channel default_author）
        author = args.author or resolved.get("channel", {}).get("default_author")
        if author:
            fill_author(page, author)

        # 6. 填写正文 HTML
        fill_body_html(page, article_html)

        # 7. 上传封面图
        if cover_path:
            upload_cover(page, cover_path)

        # 8. 填写摘要
        fill_digest(page, args.digest or "")

        # 9. 保存前校验，避免正文误进标题/封面标题后仍然保存草稿
        ss_dir = DEFAULT_SCREENSHOTS_DIR
        ensure_dir(ss_dir)
        validate_article_fields(page, args.title, article_html, ss_dir)

        # 10. 截图
        ss_path = os.path.join(ss_dir, "draft_%d.png" % int(time.time()))
        try:
            page.screenshot(ss_path)
            print("[截图] 操作完成截图: %s" % ss_path)
        except Exception as e:
            print("[警告] 截图失败: %s" % e)

        # 11. 保存到草稿箱
        save_draft(page, screenshot_dir=ss_dir)

        print("\n" + "=" * 50)
        print("发布完成! 文章已保存到草稿箱。")
        print("用户目录: %s" % user_dir)

        # ── 产物归档 ──
        print("[归档] 产物目录: %s" % article_dir)

        # 1. 备份当前版本（如果已有旧产物）
        has_existing = has_current_artifacts(article_dir)
        if has_existing:
            new_ver, moved = archive_current_version(article_dir)
            print("[归档] 旧版已归档到 versions/v%d/ (%s)" % (new_ver, ", ".join(moved) if moved else "无文件"))

        # 2. 复制新产物到归档目录
        copy_artifacts(
            article_dir,
            article_html_path=args.article,
            cover_path=cover_path,
            final_md_path=args.source,
        )
        print("[归档] 已保存: article.html%s%s" % (
            ", cover" if cover_path else "",
            ", final.md" if args.source else "",
        ))

        # 3. 写发布记录
        record_publish(article_dir, args.title, final_account, "发布到草稿箱")
        print("[归档] publish.json 已更新")

        # 4. 清理超过7天的旧版本
        cleanup_old_versions(article_dir)

        print("=" * 50)

    except Exception as e:
        print("\n[错误] 发布失败: %s" % e)
        try:
            ss_dir = DEFAULT_SCREENSHOTS_DIR
            ensure_dir(ss_dir)
            ss_path = os.path.join(ss_dir, "error_%d.png" % int(time.time()))
            page.screenshot(ss_path)
            print("[截图] 错误截图已保存: %s" % ss_path)
        except Exception:
            pass
        raise

    finally:
        print("\n浏览器将在 10 秒后关闭（按 Ctrl+C 立即关闭）...")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            pass
        page.quit()
        print("[退出] 浏览器已关闭。")


# ── 多账号管理 ──

def do_list_profiles(args):
    profiles = iter_profile_dirs()

    if not profiles:
        print("暂无 profile。目录: %s" % DEFAULT_PROFILES_DIR)
        print("使用 'create-profile' 命令创建新 profile。")
        return

    print("已有 profile（目录: %s）:" % DEFAULT_PROFILES_DIR)
    for i, entry in enumerate(profiles, 1):
        path = entry.path
        meta = read_profile_meta(path)
        file_count = sum(1 for _ in Path(path).rglob("*") if _.is_file())
        display_name = meta.get("display_name") or meta.get("mp_name") or "-"
        channel_id = meta.get("channel") or "-"
        print("  %d. %s  (%d 文件, channel=%s, name=%s)" % (i, entry.name, file_count, channel_id, display_name))


def do_list_channels(args):
    channels = load_channels_config()
    if not channels:
        print("未找到 channels.yaml。请先在 %s 创建频道配置。" % CHANNELS_CONFIG_PATH)
        return

    print("已有 channels（配置文件: %s）:" % CHANNELS_CONFIG_PATH)
    for channel_id in sorted(channels.keys()):
        channel = channels[channel_id] or {}
        display_name = channel.get("display_name") or "-"
        profile_name = channel.get("profile") or "-"
        profile_dir = resolve_profile_dir(profile_name) if profile_name != "-" else None
        profile_state = "missing"
        if profile_dir and os.path.isdir(profile_dir):
            profile_state = "ok"
        elif profile_name == "-":
            profile_state = "unbound"
        persona_id = channel.get("persona") or "-"
        persona_path = get_persona_path(persona_id) if persona_id != "-" else None
        persona_state = "ok" if persona_path and persona_path.exists() else ("-" if persona_id == "-" else "missing")
        print(
            "  - %s (%s) | status=%s | profile=%s (%s) | persona=%s (%s) | archive=%s"
            % (
                channel_id,
                display_name,
                channel.get("status") or "active",
                profile_name,
                profile_state,
                persona_id,
                persona_state,
                channel.get("archive_account") or "-",
            )
        )


def do_create_profile(args):
    name = args.name
    if args.slug:
        slug = args.slug.strip().lower()
        slug = re.sub(r"[^a-z0-9_]+", "_", slug).strip("_")
        if not slug:
            print("[错误] --slug 为空或不合法")
            sys.exit(1)
        name = "mp__%s" % slug

    if not name:
        print("[错误] 请通过 --name 或 --slug 指定 profile 名称")
        sys.exit(1)

    name = name.strip().replace(" ", "_").replace("/", "_")
    profile_dir = os.path.join(DEFAULT_PROFILES_DIR, name)

    if os.path.exists(profile_dir):
        print("[错误] Profile '%s' 已存在: %s" % (name, profile_dir))
        sys.exit(1)

    ensure_dir(profile_dir)
    meta = {
        "profile_id": name,
        "display_name": args.display_name or "",
        "mp_name": args.display_name or "",
        "channel": args.channel or "",
        "notes": args.notes or "",
    }
    write_profile_meta(profile_dir, meta)
    print("[创建] Profile '%s' 已创建: %s" % (name, profile_dir))
    if args.channel:
        print("[创建] 已写入 profile 元信息：channel=%s" % args.channel)
    print("使用方式:")
    print("  python3 publish_wechat.py publish --user-dir %s ..." % profile_dir)


def do_cleanup(args):
    """清理所有账号的过期版本归档。"""
    retention_days = args.days
    total_cleaned = 0

    if not os.path.isdir(DEFAULT_OUTPUT_BASE):
        print("产物目录不存在: %s" % DEFAULT_OUTPUT_BASE)
        return

    for account in os.listdir(DEFAULT_OUTPUT_BASE):
        articles_dir = os.path.join(DEFAULT_OUTPUT_BASE, account, "articles")
        if not os.path.isdir(articles_dir):
            continue
        for article_name in os.listdir(articles_dir):
            article_dir = os.path.join(articles_dir, article_name)
            if not os.path.isdir(article_dir):
                continue
            cleaned = cleanup_old_versions(article_dir, retention_days)
            total_cleaned += cleaned

    if total_cleaned > 0:
        print("[清理] 共清理 %d 个过期版本目录（超过 %d 天）" % (total_cleaned, retention_days))
    else:
        print("[清理] 没有需要清理的过期版本")


# ── CLI ──

def build_parser():
    parser = argparse.ArgumentParser(
        description="微信公众号自动化发布工具（ruyiPage）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    pub = subparsers.add_parser("publish", help="发布文章到草稿箱")
    pub.add_argument("--article", "-a", required=True, help="文章 HTML 文件路径")
    pub.add_argument("--cover", "-c", default=None, help="封面图片路径")
    pub.add_argument("--source", "-s", default=None, help="原始 Markdown 文件路径（final.md）")
    pub.add_argument("--title", "-t", required=True, help="文章标题")
    pub.add_argument("--author", "-A", default=None, help="作者名")
    pub.add_argument("--digest", "-d", default=None, help="文章摘要")
    pub.add_argument("--channel", default=None, help="频道标识（推荐；从 channels.yaml 自动解析 profile + persona + archive_account）")
    pub.add_argument("--account", default=None, help="归档账号标识（兼容旧用法；推荐改用 --channel）")
    pub.add_argument("--user-dir", "-u", default=None, help="Firefox 用户数据目录")
    pub.add_argument("--force", action="store_true", help="忽略短时间重复发布保护，强制再次发布")

    xls = subparsers.add_parser("xls-publish", help="发布小绿书贴图到草稿箱")
    xls.add_argument("--images", "-i", nargs="+", required=True, help="小绿书贴图图片路径，支持一次传多张")
    xls.add_argument("--title", "-t", required=True, help="贴图标题")
    xls.add_argument("--description", "-d", required=True, help="贴图描述信息")
    xls.add_argument("--channel", default=None, help="频道标识（推荐；从 channels.yaml 自动解析 profile + persona + archive_account）")
    xls.add_argument("--account", default=None, help="归档账号标识（兼容旧用法；推荐改用 --channel）")
    xls.add_argument("--user-dir", "-u", default=None, help="Firefox 用户数据目录")
    xls.add_argument("--force", action="store_true", help="忽略短时间重复发布保护，强制再次发布")

    subparsers.add_parser("list-profiles", help="列出已有的账号 profile")
    subparsers.add_parser("list-channels", help="列出 channels.yaml 里的频道映射")

    cp = subparsers.add_parser("create-profile", help="创建新的账号 profile")
    cp.add_argument("--name", "-n", default=None, help="profile 名称（兼容旧用法）")
    cp.add_argument("--slug", default=None, help="profile 英文标识；会自动创建为 mp__<slug>")
    cp.add_argument("--display-name", default=None, help="profile 展示名称/公众号名称")
    cp.add_argument("--channel", default=None, help="可选：这个 profile 默认关联的 channel")
    cp.add_argument("--notes", default=None, help="可选：备注")

    cln = subparsers.add_parser("cleanup", help="清理所有账号的过期版本归档")
    cln.add_argument("--days", "-d", type=int, default=VERSION_RETENTION_DAYS,
                     help="保留天数（默认 %d）" % VERSION_RETENTION_DAYS)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    if args.command == "publish":
        do_publish(args)
    elif args.command == "xls-publish":
        do_xls_publish(args)
    elif args.command == "list-profiles":
        do_list_profiles(args)
    elif args.command == "list-channels":
        do_list_channels(args)
    elif args.command == "create-profile":
        do_create_profile(args)
    elif args.command == "cleanup":
        do_cleanup(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
