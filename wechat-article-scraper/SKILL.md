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

### 6. 沉淀到 strategy-material-engine（不可跳过）

当用户贴入微信公众号链接并完成全文解析后，除了沉淀写作框架和写入飞书，还要把同一篇文章导入 `~/.hermes/skills/strategy-material-engine`，让后续写作素材召回可以复用。

#### 6.1 导入原文 source

使用解析后保存的 `article.md` 作为输入，原文默认进入 `sources/materials/`：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/import_source_and_route.py \
  "<article.md路径>" \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --bucket materials \
  --source-type article \
  --title "<文章标题>" \
  --author "<公众号作者>" \
  --origin "微信公众号" \
  --date "<发布日期或抓取日期>" \
  --tags "wechat,公众号,爆文拆解" \
  --link "<原始微信公众号URL>" \
  --summary "<一句话摘要>"
```

导入后记录终端输出里的 source 路径，例如 `sources/materials/<slug>.md`，后续写素材时填入 `source_refs`。

#### 6.2 提取可复用原子素材

当前会话通读解析出的正文，只提取真正有复用价值的素材，不为了数量凑条目。参考密度：

- 干货型 3000-5000 字文章：通常提取 4-8 条
- 情绪文、观点短文、低密度文章：可只提 1-5 条
- 信息密度很低时：只导入 source 也可以，不强行生成素材

常见素材类型：

- `method`：结构、流程、写法、SOP、表达方法
- `insight`：反常识洞察、本质判断、认知翻转
- `story`：可复用但需改写的故事型素材
- `quote`：短句、金句、口语化表达
- `data`：数字、对比、可作为论据的信息
- `playbook`：带适用条件的具体打法

每条素材先创建草稿：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/new_material.py \
  "<素材标题>" \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --type method \
  --date "<YYYY-MM-DD>"
```

然后写入完整素材内容。必须补齐：

- `primary_claim`：素材核心主张
- `claims`：1-3 条可复用观点
- `tags`：文章主题、公众号、写作方向
- `source`：原文章标题
- `source_refs`：导入后的 `sources/materials/<slug>.md`
- `source_uid`：尽量沿用 source frontmatter 中的 `source_uid`
- `review_status`：默认 `draft`
- 正文：只保留可复用的抽象素材，避免整段照搬原文

边界规则：

- 原文可以完整保存在 `sources/materials/`
- `assets/materials/` 里不要复制整篇文章，不要长段搬运
- 对公众号观点文/情绪文默认不建 case
- 如果文章明显是实操复盘、项目拆解、商业打法，才提示可额外走 `extract_case.py`

#### 6.3 刷新索引并验证

原文和素材写入后刷新索引：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/flush_indexes.py \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --all
```

最后用文章核心关键词做一次写作素材搜索验证：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/search_knowledge.py \
  "<文章核心关键词>" \
  --mode writing \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --disable-query-rewrite
```

如果素材引擎入库或索引刷新失败，记录错误并继续保留已经完成的 `article.md`、框架拆解和飞书写入结果，不回滚前置步骤。

### 完成检查清单

每次处理微信公众号链接后，在结束前确认：

```
[ ] 1. 抓取 + Python/JS 提取正文 → 保存为 article.md
[ ] 2. framework_extract.py prepare 已可执行或已生成拆解提示词包
[ ] 3. 原文已导入 strategy-material-engine 的 sources/materials/
[ ] 4. 已按复用价值提取原子素材，或明确记录“只存 source，不提素材”的原因
[ ] 5. 已刷新 strategy-material-engine 索引
[ ] 6. 已用 search_knowledge.py 验证新内容可被召回
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
