---
name: wechat-publisher
description: >
  微信公众号发布链路工具：Markdown → 公众号HTML排版 → 封面图生成 → ruyiPage自动发布到草稿箱。
  TRIGGER when: user asks to "排版" "发布" "publish" "推送到草稿箱" "转HTML" "生成封面";
  user says "把文章发到公众号" "排版成公众号格式" "生成封面图" "publish to wechat draft";
  also trigger when wechat-article-pipeline completes final.md and needs post-processing.
---

# 微信公众号发布工具

把 Markdown 终稿变成可以直接在微信公众号草稿箱里看到的成稿。

**支持个人订阅号**（无需微信认证，不走API，走 ruyiPage 浏览器自动化）。

## 前置条件

**Python依赖**（已安装）：
```bash
pip3 install mistune pygments pyyaml pillow ruyiPage
```

**首次使用需要扫码登录一次**：
```bash
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/publish_wechat.py \
  create-profile --slug qiaosan --display-name "乔三技术号"
```
之后复用同一个 profile 目录，无需重复登录。

**推荐先维护 `channels.yaml`**：

- 写文章前先选 channel
- channel 决定 `persona`
- 发布时由 channel 自动反查 `profile + archive_account`

查看当前 channel：
```bash
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/publish_wechat.py list-channels
```

## 三个发布节点

### 节点1：Markdown → 公众号HTML排版

```bash
CONVERTER="~/.hermes/skills/wechat-factory/wechat-publisher/scripts/md_to_styled_html.py"
RENDERER_V2="~/.hermes/skills/wechat-factory/wechat-publisher/scripts/render_wechat_article.py"

# 情感号（退休阿姨人设，暖色调大字号）
python3 $CONVERTER final.md -o article.html -t emotion-warm

# 技术号（简洁专业风格）
python3 $CONVERTER final.md -o article.html -t tech-clean

# 新入口（theme pack v1，推荐）
python3 $RENDERER_V2 final.md -o article.html -t tech-clean

# 按 framework_flow 的推荐主题自动渲染
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/render_with_recommended_theme.py \
  final.md \
  --theme-file ~/.hermes/skills/wechat-factory/wechat-article-pipeline/work/framework-flow/<xxx>.theme.yaml
```

| 主题 | 风格 | 适用 |
|------|------|------|
| `emotion-warm` | 暖橙渐变、大字号(17px)、亲切排版 | 情感号（退休阿姨） |
| `tech-clean` | 冷蓝灰调、代码高亮、编号分区 | 技术号 |
| `dense-note` | 信息更密、留白更克制、笔记感更强 | 技术号收藏型内容 |
| `magazine-soft` | 柔和面状标题、杂志专栏感 | 情感号观点/关系文 |

### 节点2：封面图生成（让用户选择样式）

**必须先问用户想用哪种封面风格，不要自行决定。** 向用户展示下表让其选择：

| 样式 | 说明 | 推荐场景 |
|------|------|---------|
| `accent-bar` | 深色底+红色强调条 | 技术号 |
| **火山引擎文生图** | 当前会话 LLM 生成场景化提示词，再调用火山 API | 需要高质量封面时 |

用户选择 `accent-bar` 本地风格时，走 Pillow 生成逻辑。

用户选择**火山引擎文生图**时，走以下流程：

1. 从 `final.md` 的 YAML frontmatter 读取 `channel`、`framework`（作为 article_type）、`title`、`cover_text`（封面短文案）
2. 当前 AI CLI 会话读取 `final.md` 的正文和 frontmatter，直接生成一个场景化完整生图提示词，保存为 `final.cover.prompt.md`
3. 用 `--prompt-file final.cover.prompt.md` 交给火山引擎生成图片
4. 下载图片保存为 `cover.jpg`

**重要：火山封面必须优先走“当前会话 LLM 生成完整提示词”模式。** 脚本只负责读取提示词和调用火山，不在脚本里内置 LLM 调用。

场景化封面提示词必须满足：

- 根据文章内容生成一个具体生活/工作场景，不能只写标题、抽象背景或通用办公桌
- 场景里要有目标读者能代入的人、动作、环境和情绪张力
- 画面要切中读者心理防线，例如焦虑、委屈、醒悟、逃避、失控、边界感、主动权丧失等
- 可见文字只允许出现 `cover_text` 或主标题这一组文字，不要出现其他说明词、风格名、公众号、封面、比例、构图等描述性文字
- 生图提示词里不要写 `2.35:1`、`900×383` 这类比例或尺寸字面量，避免模型把它们画进图片
- 提示词只描述横向宽幅公众号头图；具体比例由火山 API 的 `size` 参数强制要求
- 不做下载后裁剪/缩放；如果火山返回尺寸不符合请求尺寸，脚本直接报错
- 明确横版公众号封面约束：单张图、标题清晰可读、无水印、无 logo、无多余文字

```bash
VOLCENGINE="~/.hermes/skills/wechat-factory/wechat-publisher/scripts/generate_cover_volcengine.py"

# 第1步：当前会话 LLM 生成完整场景化提示词
# 输出文件：final.cover.prompt.md

# 第2步：用外部完整提示词生成，默认请求 1880x800（2.35:1）
python3 $VOLCENGINE final.md -o cover.jpg --prompt-file final.cover.prompt.md

# 如需手动指定尺寸，必须保持 2.35:1
python3 $VOLCENGINE final.md -o cover.jpg --prompt-file final.cover.prompt.md --size 1880x800

# 只检查最终提示词，不调用火山 API
python3 $VOLCENGINE final.md --prompt-file final.cover.prompt.md --dry-run
```

**环境变量**：`ARK_API_KEY`（火山引擎 API key，需在 shell 中 export）。`--dry-run` 不需要 API key。

**重要约束：生成封面图后不要调用视觉模型检查效果。** 脚本输出 `[ok] 封面已下载` 就说明成功了，让用户自己去文件夹看即可。

```bash
COVER="~/.hermes/skills/wechat-factory/wechat-publisher/scripts/generate_cover.py"

# 示例：用户选择本地 accent-bar 风格
python3 $COVER final.md -o cover.jpg -s accent-bar
```

**火山输出尺寸：默认 `1880x800`，比例严格为 2.35:1。** 这是 API 参数，不要写进生图提示词。



### 节点3：ruyiPage 自动发布到草稿箱

```bash
PUBLISHER="~/.hermes/skills/wechat-factory/wechat-publisher/scripts/publish_wechat.py"

# 发布到草稿箱（会打开Firefox浏览器）
python3 $PUBLISHER publish \
  --channel tech \
  --article article.html \
  --cover cover.jpg \
  --title "文章标题" \
  --author "作者名" \
  --digest "文章摘要"

# 兼容旧用法：手动指定 profile + archive_account
python3 $PUBLISHER publish \
  --user-dir ~/.hermes/skills/wechat-factory/wechat-publisher/data/profiles/mp__qiaosan \
  --account tech \
  --article article.html --cover cover.jpg \
  --title "文章标题" --author "作者名" --digest "文章摘要"

# 如需跳过重复发布保护（默认会拦截10分钟内相同稿件的重复发布）
python3 $PUBLISHER publish \
  --article article.html --cover cover.jpg \
  --title "文章标题" --author "作者名" --digest "文章摘要" \
  --force

# 管理账号profile
python3 $PUBLISHER list-channels
python3 $PUBLISHER list-profiles
python3 $PUBLISHER create-profile --slug auntie --display-name "情感号"
```

**多账号设计**：每个公众号一个 profile 目录（保存独立的登录cookie），20个号 = 20个 profile，切换目录即切换账号。

## 产物归档规范（重要）

**每次发布后，所有产物自动保存到统一目录，不再丢失。**

### 目录结构

```
~/.hermes/output/wechat/
├── tech/                          # 技术号
│   ├── articles/
│   │   └── 2026-04-15_爆文生产线/  # 每篇文章一个目录
│   │       ├── final.md           ← 永远是当前版
│   │       ├── article.html       ← 永远是当前版
│   │       ├── cover.jpg          ← 永远是当前版
│   │       ├── publish.json       ← 发布记录
│   │       └── versions/          ← 历史版本（自动管理）
│   │           ├── v1/
│   │           │   ├── final.md
│   │           │   ├── article.html
│   │           │   └── cover.jpg
│   │           └── v2/
│   │               └── ...
│   └── topics/                    # 选题记录
└── emotion/                       # 情感号（同结构）
    ├── articles/
    └── topics/
```

### 规则

1. **根目录永远是最新的** — `final.md`、`article.html`、`cover.jpg` 始终是当前版本，拿起来就能重新发布
2. **重新发布时自动版本归档** — 如果目录里已有旧产物，脚本自动把旧版复制到 `versions/vN/`
3. **publish.json 记录每次操作** — 版本号、时间、操作说明，可追溯
4. **7天自动清理** — 每次发布时自动清理超过7天的版本目录；也可手动触发 `cleanup` 命令

### 正文源文件边界（重要）

`publish_wechat.py` 发布的是 `article.html`，而 `article.html` 通常由 `final.md` 转换而来。

因此：

- `final.md` 应只包含正文终稿
- 标题备选 / 摘要 / 导语 / 封面文案不要混入 `final.md`

当前转换器已兼容：如果 `final.md` 尾部误带了典型的“发布素材”区块，会在生成 `article.html` 时自动剥离；但最佳实践仍然是从源头保持正文与发布素材分离。

### 新增参数

`publish` 命令推荐使用 `--channel`，并保留 `--source` / `--account` / `--user-dir` 兼容旧用法：

```bash
python3 $PUBLISHER publish \
  --channel tech \              # 推荐：自动解析 profile + archive_account
  --article article.html \
  --cover cover.jpg \
  --source final.md \           # 原始 Markdown，可选但建议传
  --title "文章标题" \
  --author "作者名" \
  --digest "文章摘要" \
  --account tech                # 账号标识：tech 或 emotion
```

推荐顺序：

1. 在 `channels.yaml` 中维护 channel
2. 写作时先选 channel
3. 发布时优先用 `--channel`

### 手动清理

```bash
# 清理所有账号超过7天的旧版本
python3 $PUBLISHER cleanup

# 自定义保留天数
python3 $PUBLISHER cleanup --days 14
```

## 一键发布完整流程

```bash
SKILL=~/.hermes/skills/wechat-factory/wechat-publisher

# Step 1: 排版（情感号）
python3 $SKILL/scripts/md_to_styled_html.py final.md -o article.html -t emotion-warm

# Step 2: 封面图
python3 $SKILL/scripts/generate_cover.py final.md -o cover.jpg -s accent-bar

# Step 3: 发布到草稿箱（首次需扫码登录）
python3 $SKILL/scripts/publish_wechat.py publish \
  --article article.html --cover cover.jpg \
  --source final.md \
  --account emotion \
  --title "从final.md提取" --author "作者" --digest "摘要"
```

## 文件位置

- 脚本目录：`~/.hermes/skills/wechat-factory/wechat-publisher/scripts/`
- 账号profiles：`~/.hermes/skills/wechat-factory/wechat-publisher/data/profiles/`
- 主题目录：`~/.hermes/skills/wechat-factory/wechat-publisher/scripts/themes/`
- 产物归档：`~/.hermes/output/wechat/<account>/articles/`

## Theme Pack v1（已迁移）

当前排版主题已从单个 `theme.yaml` 迁移到 theme pack v1 结构：

```text
themes/<theme-id>/
├── manifest.yaml
├── tokens.yaml
├── blocks.yaml
├── heuristics.yaml
└── preview.md
```

- `manifest.yaml`：主题元信息、适用赛道、人设和目标
- `tokens.yaml`：颜色、字号、间距等设计 token
- `blocks.yaml`：标题、引用、代码块、表格等区块变体
- `heuristics.yaml`：未来主题推荐器的偏好规则
- `preview.md`：预览与回归测试样例

兼容说明：

- `md_to_styled_html.py` 仍可继续使用
- 新渲染入口是 `render_wechat_article.py`
- 如果后续再新增老式 `theme.yaml` 主题，兼容 loader 仍能读取

批量渲染并校验所有主题预览：

```bash
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/render_theme_previews.py
```

主题推荐器：

```bash
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/recommend_theme.py \
  --channel tech \
  --article-subtype mistake_breakdown \
  --goal save --goal read_finish \
  --source final.md
```

终稿按推荐主题直接渲染：

```bash
python3 ~/.hermes/skills/wechat-factory/wechat-publisher/scripts/render_with_recommended_theme.py \
  ~/.hermes/output/wechat/tech/articles/<日期_标题>/final.md \
  --theme-file ~/.hermes/skills/wechat-factory/wechat-article-pipeline/work/framework-flow/<日期>_tech_<topic>.theme.yaml
```

- 推荐器会结合：
  - `channel -> lane/persona`
  - `article_subtype`
  - `goal`
  - `source` 自动分析出的 `contains_code / contains_table / article_length / emotional_density`

迁移说明见：`wechat-publisher/THEME_SCHEMA_V1_MIGRATION.md:1`

## mistune 3.x 排版引擎踩坑记录（已修复）

### 表格渲染：必须显式启用 table 插件

mistune 3.x 默认**不包含**表格支持（和 mistune 2.x 不同）。如果不启用 table 插件，`|col|col|` 格式的表格会被当成普通段落文本，原样包在 `<p>` 里输出。

**修复方法**：在 `create_markdown()` 时传入插件：

```python
from mistune.plugins.table import table as table_plugin
markdown = mistune.create_markdown(
    renderer=renderer,
    plugins=[table_plugin, "footnotes", "strikethrough", "mark"],
)
```

### 自定义 Renderer 的 table_cell 必须接收 head 参数

table 插件渲染表头时会传 `head=True`，自定义 `StyledRenderer` 的 `table_cell` 方法必须接收这个参数，用 `<th>` 或 `<td>` 区分：

```python
def table_cell(self, text: str, align=None, head=False, **attrs) -> str:
    tag = "th" if head else "td"
    ...
```

### 插件传参格式

`plugins` 列表里，第三方插件（如 `mistune.plugins.table`）需要 `import` 后直接传函数对象；mistune 内置插件（如 `footnotes`、`strikethrough`、`mark`）传字符串名称。不能传模块对象（如 `from mistune.plugins import formatting` 然后传 `formatting`），会报 `AttributeError: module has no attribute 'rsplit'`。

## 封面图生成踩坑

`generate_cover.py` **要求 Markdown 文件有 YAML frontmatter 且包含 `title` 字段**，否则报错"frontmatter 中未找到 title"。如果 final.md 没有 frontmatter，生成封面前必须先加上：

```markdown
---
title: 文章标题
---
```

### 火山引擎文生图：模型会把提示词描述性文字渲染到画面上

**现象**：生成的封面图中出现了提示词里的描述性文字，例如"公众号""封面图""2.35:1""构图"等，与主标题混在一起变成类似"外包科技公众号2.35:1"的错误内容。

**根因**：doubao-seedream-4 等文生图模型会将提示词中的所有文字信息视为"要在画面上渲染的文字"，无法区分"指令性描述"和"要显示的标题文字"。

**已修复**（2026.4.24）：
1. **当前会话 LLM 生成完整提示词**：不再走模板推荐和脚本内置风格，提示词由当前 AI CLI 会话结合正文生成。
2. **generate_cover_volcengine.py 的 sanitize_prompt() + size 校验**：调用火山前清理提示词里的比例/尺寸字面量；通过 API `size` 参数请求 `1880x800`；下载后只校验尺寸，不做裁剪/缩放。
3. **提示词约束**：只允许画面出现 `cover_text` 或主标题这一组文字，其他说明词、比例、尺寸、风格名都不要写成可被渲染的文字。

**教训**：给文生图模型写提示词时，任何不希望出现在画面上的文字都不要写进 prompt。比例和尺寸属于 API 参数约束，不应该让模型从自然语言里理解，更不能靠后处理裁剪补救。

### 火山引擎封面图上传超时

publish_wechat.py 上传封面图到微信后台时，如果图片较大（>1MB），上传可能超过30秒超时。脚本会尝试继续操作但封面可能未成功挂上。

**处理方式**：草稿保存成功后，用户需手动到草稿箱检查封面是否正确，必要时手动从图片库重新选择。

## ruyiPage 开发注意事项（踩坑记录）

### JS 语法限制

`page.run_js()` 执行 JS 代码时，**不能在顶层使用 `return`**（会报 `SyntaxError: return not in function`）。

两种解决方式：
1. 用 IIFE 包装：`(function() { ... return value; })()`
2. 用 `as_expr=True` 参数，把最后一行作为表达式返回

**必须使用 ES5 语法**（ruyiPage 的 JS 环境兼容性有限）：
- 用 `var`，不用 `const`/`let`
- 用 `for (var i = 0; i < arr.length; i++)`，不用 `for...of`
- 用 `str.indexOf('x') >= 0`，不用 `str.includes('x')`

示例（正确写法）：
```python
result = page.run_js("""
    var buttons = document.querySelectorAll('button');
    var found = null;
    for (var i = 0; i < buttons.length; i++) {
        if (buttons[i].textContent.indexOf('保存') >= 0) {
            buttons[i].click();
            found = 'clicked';
            break;
        }
    }
    found;
""", as_expr=True)
```

### 微信后台登录检测

微信后台首页 URL `https://mp.weixin.qq.com/` 同时是登录页，URL 中不包含 "login" 字样。
**不能通过 `url 中不包含 login` 来判断已登录**。

正确判断方式：
1. 管理后台 URL 包含 `/cgi-bin/` → 已登录
2. 检查页面是否有"内容与互动"、"创作"、"发表管理"等管理后台特征元素
3. 首页/登录页特征：页面文字包含"立即注册"、"微信扫一扫"、"登录"按钮

### Token 提取必须用 IIFE + return

`extract_token` 用 `run_js()` 提取 URL 中的 token 时，**不能用 `as_expr=True` + 顶层 if 语句**，因为 ES5 的 if 语句不返回值，`as_expr` 只取最后一个表达式。

错误写法（永远返回 null）：
```python
token = page.run_js(
    "var m = window.location.href.match(/token=(\\d+)/);"
    "if (m) { m[1]; } else { null; }",
    as_expr=True
)
```

正确写法（IIFE + return）：
```python
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
```

### 登录后页面跳转需要等待

扫码登录成功后，`wait_for_login` 检测到 URL 不含 login 就返回了，但此时页面可能还在跳转到 `/cgi-bin/` 的过程中。`extract_token` 此时提取不到 token。

**解决方案**：在 `navigate_to_editor` 中加延迟重试——首次提取失败后等 5 秒再试一次。如果用 token URL 直接进入编辑器后 URL 没变，再等 8 秒并重新尝试从页面链接提取 token。

### 微信后台编辑器实际可用选择器（2026.4.15 实测验证）

账号：乔三的AI效率工坊（个人订阅号，未认证），编辑器为2026年新版。

| 元素 | 选择器 | 操作方式 |
|------|--------|----------|
| 标题 | `textarea.js_title` | `el.click()` → `el.input(title)` |
| 作者 | `input#author` | 直接 `el.input(author)` |
| 正文 | `#js_editor` 或 `.ProseMirror` | `el.innerHTML = html` + dispatch input/change event |
| 封面上传 | 先点"从图片库选择"并上传文件，再选图后点「下一步」/「确定」完成 | 新版后台通常是两到三步 |
| 保存草稿 | `#js_submit` 或 JS查找文字"保存为草稿"的元素并click | 优先用 CSS 选择器 |
| 编辑器URL | `cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&token=TOKEN` | 直接get跳转 |

**正文注入关键**：必须用 ProseMirror 编辑器（新版后台），注入后需 dispatch `input` 和 `change` 事件让后台感知内容变化。

**封面图上传关键**：不能直接给 `input[type=file]` 设 value（浏览器安全限制），必须先打开图片库对话框，再用 ruyiPage 的 `ele.input(abs_path)` 注入路径。新版后台常见流程是：上传完成 → 选中图片 → 点「下一步」→ 如出现裁剪/确认页再点「确定」。

### replaceAllContent 不再正确解析 HTML（2026.4.26）

**现象**：`root.replaceAllContent(html)` 把 HTML 内容当成纯文本塞进编辑器，ProseMirror 内只有一个文本节点，没有 p/h2 等标签，导致编辑器里显示"一大坨文字"。

**根因**：微信后台更新后，Vue 内部的 `replaceAllContent` API 行为变化，不再自动解析 HTML 字符串。

**已修复**：在 `fill_body_html()` 中加入验证逻辑——调用 `replaceAllContent` 后检查 ProseMirror 内是否有 p 标签。如果检测到 "NO_P_TAGS"，自动回退到 `ProseMirror innerHTML` 方案。

验证日志：
```
[填写] replaceAllContent 未正确解析 HTML（无 p 标签），回退到 innerHTML 方案
[填写] 正文已注入到编辑器 (ProseMirror)
```

如果未来 `innerHTML` 方案也失效，可尝试 `document.execCommand('selectAll')` + `document.execCommand('insertHTML', false, html)` 方案。

### 推荐的两阶段发布流程

纯脚本全自动需要扫码登录（不可控），推荐拆成两阶段：

**阶段1：登录获取 token（需人工扫码，后台运行等用户操作）**
```python
from ruyipage import launch
import time, re

page = launch(user_dir=profile_dir, headless=False)
page.get("https://mp.weixin.qq.com/")
# 轮询等待用户扫码，检测 /cgi-bin/ 出现在URL中
for i in range(200):
    time.sleep(3)
    if "/cgi-bin/" in page.url:
        m = re.search(r'token=(\d+)', page.url)
        token = m.group(1) if m else None
        break
```

**阶段2：用 token 直接操作（全自动，无需人工）**
```python
editor_url = f"https://mp.weixin.qq.com/cgi-bin/appmsg?t=media/appmsg_edit&action=edit&type=77&token={token}"
page.get(editor_url)
# 然后依次填写标题、作者、正文、封面上传、保存草稿
```

如果 profile 已有有效登录态，阶段1会自动跳过（URL 直接就是 /cgi-bin/ 开头）。

### execute_code 中 read_file 的行号陷阱

**在 `execute_code` 中调用 `read_file()` 返回的内容带有行号前缀**（如 `   217|content`）。
如果把这个内容写回文件，文件会被行号前缀污染，导致语法错误。

**正确做法**：
- 在 `execute_code` 中读取文件用于搜索/分析是安全的（只要你不写回）
- 如果需要读取并修改文件内容，**用 `patch()` 工具**而不是 read+write
- 如果必须用 sed 清理：`sed -E 's/^[[:space:]]*[0-9]+\|//' file.py > file_clean.py`

## 与其他 Skill 的衔接

- **wechat-article-pipeline**：输出 final.md → 本 Skill 接收
- **emotion-opinion-humanizer**：输出 final.md → 本 Skill 接收
- **wechat-topic-spy**：提供选题 → pipeline → humanizer → 本 Skill

完整流水线：选题 → 写稿 → 降AI味 → 排版 → 封面 → 发布草稿箱
