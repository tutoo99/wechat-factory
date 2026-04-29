---
name: wechat-article-scraper
description: >
  从微信公众号文章链接抓取全文（标题、作者、正文）。微信文章页面默认不渲染正文内容，
  浏览器快照只能看到标题区，需要通过 JS 从 #js_content DOM 节点提取。
  TRIGGER when: user says "抓微信文章"、"提取公众号全文"、"爬这个微信链接的内容"、"拆这篇爆文" 
  and provides a mp.weixin.qq.com URL.
---

# 微信公众号文章全文抓取

## 问题背景

微信文章页面（mp.weixin.qq.com）正文区域 `#js_content` 依赖 JS 动态渲染，浏览器 accessibility snapshot 只能看到标题区和操作按钮，正文抓不到。需要用 `browser_console` 执行 JS 直接读取 DOM。

**但是 browser_navigate 经常超时**（微信页面资源多、体积大，通常 2-3MB），所以必须有 curl + Python 的 fallback 方案。实际经验：browser 路线大约 50% 概率超时，curl 路线稳定可用。

## 使用前提

- 文章 URL 格式：`https://mp.weixin.qq.com/s/xxx`

## 两种抓取方式

### 方式 A：Browser 路线（优先尝试，大概率超时）

### 1. 打开页面

```
browser_navigate(url="<文章URL>")
```

### 2. 用 JS 提取标题和作者

```
browser_console(expression="
  JSON.stringify({
    title: document.querySelector('#activity-name')?.textContent?.trim(),
    author: document.querySelector('#js_name')?.textContent?.trim(),
    date: document.querySelector('#publish_time')?.textContent?.trim(),
  })
")
```

### 3. 用 JS 提取正文全文

```
browser_console(expression="document.querySelector('#js_content')?.innerText || ''")
```

如果返回为空，尝试备选方案：

```
browser_console(expression="document.querySelector('.rich_media_content')?.innerText || ''")
```

### 方式 B：curl + Python fallback（browser 超时或返回空时使用）

当 `browser_navigate` 超时（报 Operation timed out）或正文提取为空时，直接用 curl 下载 HTML 再 Python 解析：

```bash
# Step 1: curl 下载 HTML
curl -sL -o /tmp/wx_article.html --max-time 15 "<文章URL>" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Step 2: Python 提取标题+作者+正文
python3 -c '
from html.parser import HTMLParser
import sys, json

class WxParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_content = False
        self.in_title = False
        self.in_author = False
        self.title = ""
        self.author = ""
        self.paragraphs = []
        self.current = ""
        self.in_section = False

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("id") == "activity-name":
            self.in_title = True
        elif d.get("id") == "js_name":
            self.in_author = True
        elif d.get("id") == "js_content":
            self.in_content = True
        elif tag in ("p", "br", "section") and self.in_content:
            if tag == "section":
                self.in_section = True
            if self.current.strip():
                self.paragraphs.append(self.current.strip())
                self.current = ""

    def handle_endtag(self, tag):
        if tag == "span" and self.in_title:
            self.in_title = False
        elif tag == "a" and self.in_author:
            self.in_author = False
        elif tag == "section" and self.in_section:
            self.in_section = False
            if self.current.strip():
                self.paragraphs.append(self.current.strip())
                self.current = ""
        elif tag == "p" and self.in_content:
            if self.current.strip():
                self.paragraphs.append(self.current.strip())
                self.current = ""

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        elif self.in_author:
            self.author += data
        elif self.in_content:
            self.current += data

with open("/tmp/wx_article.html", "r", encoding="utf-8") as f:
    html = f.read()

p = WxParser()
p.feed(html)
print(json.dumps({
    "title": p.title.strip(),
    "author": p.author.strip(),
    "paragraphs": p.paragraphs
}, ensure_ascii=False, indent=2))
'
```

**方式 B 的要点：**
- curl 用 `--max-time 15` 防卡死，实际 2-3MB 的页面 3-5 秒就能下完
- Python 标准库 `html.parser` 就够用，不需要装 BeautifulSoup
- 微信 HTML 的正文在 `#js_content` div 里，段落靠 `<p>` 和 `<section>` 标签分割
- 提取结果是 paragraphs 数组，每个元素是一个自然段，直接可拼接成 Markdown
- 末尾会有 JS 代码片段混入（微信页面底部的 script），在 paragraphs 列表尾部出现 `var first_sceen__time` 或 `window.img_popup` 时，从这里截断即可

### 判断截断位置

方式 B 提取的 paragraphs 尾部会混入微信页面底部的 JS 代码和 UI 文本，需要截断。判断信号：

```
# 遇到以下任一行时停止，不纳入正文：
var first_sceen__time
var
window.
预览时标签不可点
微信扫一扫
继续滑动看下一个
向上滑动看下一个
知道了
```

AI 在处理 paragraphs 列表时，自动识别并截断尾部噪声。

### 4. 保存为 Markdown 文件（两种方式通用）

将标题作为一级标题，正文紧跟其后，保存到框架拆解临时目录：

```
write_file(
  path="~/.hermes/skills/wechat-factory/wechat-article-pipeline/work/framework-extract/<日期_标题缩写>/article.md",
  content=<拼接后的 Markdown>
)
```

文件命名规则：`<YYYY-MM-DD>_<标题去特殊字符，最长30字>`

Markdown 格式规范：
- 标题用 `# ` 一级标题
- 章节编号（01、02、03）转为 `## 数字｜标题` 格式
- "写在最后"转为 `## 写在最后`
- 引用原文台词保留引号，不做特殊处理
- 段落间空一行

### 5. 后续衔接

抓取完成后，文件可直接传入 `framework_extract.py prepare`：

```bash
cd ~/.hermes/skills/wechat-factory
python3 wechat-article-pipeline/scripts/framework_extract.py prepare \
  --article <article.md路径> \
  --title "<标题>" \
  --source-url "<原始URL>" \
  --account "<作者>" \
  --lane auto
```

## 执行决策

1. 先尝试方式 A（browser_navigate），如果成功就用 JS 提取
2. 如果 browser_navigate 超时（Operation timed out），立即切换方式 B（curl + Python）
3. 如果 browser 成功打开但正文提取为空，也切换方式 B
4. 方式 B 的 curl 几乎不会失败（纯 HTTP GET，不需要 JS 渲染）

## 注意事项

- 微信页面可能有 stealth 警告（无住宅代理），但 curl 路线不受影响
- browser 路线的 `innerText` 会保留段落间的换行符，格式天然接近 Markdown
- 方式 B 的 HTML 体积 2-3MB，但 Python 解析很快，不需要担心性能
- 正文中的引用台词自带引号，不需要额外处理
- 小标题格式可能是纯数字（如 `01`、`02`），保存时转为 `## 数字｜` 格式
- 部分文章有阅读原文链接或图片，`innerText` 和 HTMLParser 都会丢失这些信息，但对框架拆解来说纯文本足够
- 方式 B 不需要安装任何第三方库，Python 标准库就够了

## 完整示例（方式 B fallback）

```bash
# Step 1: browser 超时，切换 curl
curl -sL -o /tmp/wx_article.html --max-time 15 "https://mp.weixin.qq.com/s/xxxxx" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# Step 2: Python 提取（完整脚本见上方）
python3 -c '<提取脚本>'

# Step 3: AI 拼接 Markdown，手动截断尾部噪声，保存
write_file(path="~/.hermes/skills/wechat-factory/wechat-article-pipeline/work/framework-extract/2026-04-29_天道什么是人脉/article.md", content="# 标题\n\n正文内容...")
```
