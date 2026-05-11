---
name: wechat-article-pipeline
description: >
  公众号文章生产流水线工具。用于把“选题、写稿、降 AI 增人味、发布包装”串成一个完整流程，尤其适合情绪文、观点文、关系文、成长文和可传播的公众号长文。
  TRIGGER when: user asks to write a WeChat/public-account article end-to-end; asks for a complete公众号稿件 with title, summary, cover copy, and final polish; says “写一篇公众号文并处理成可发版”
  “串成完整公众号流程”“先写稿再降 AI 再出标题摘要封面”“做一套公众号成稿流水线”“公众号文从初稿到发布素材一起做”; also trigger when the user provides a draft and asks to complete the remaining publication pipeline.
---

# 公众号文章生产流水线

## Overview

这个 skill 用来把公众号文章做成一条完整流水线：

1. 选题定位
2. 初稿写作
3. 人味增强 / 降 AI 味
4. 违禁词排查（`banned-word-guard`）
5. 标题摘要封面等发布包装

如果是**情绪文 / 观点文 / 关系文**，优先采用：

- 前端写作：粥左罗式的传播结构
- 后端润色：`emotion-opinion-humanizer` 的后处理思路

如需完整流程模板与调用语句，读取 `references/workflow.md`。

## 适用任务

- 写一篇完整公众号文章
- 根据主题产出可发布成稿
- 已有初稿，补人味和发布素材
- 已有正文，补标题 / 摘要 / 封面 / 导语

## 素材边界

这个 skill 可以借鉴爆款文章的**结构**，但不能直接借其**素材**。  
默认遵循以下硬规则：

- 只学骨架，不抄标题
- 只学推进方式，不借故事细节
- 只学情绪节奏，不复用原文金句
- 只学案例递进，不搬用原文中的书籍引用、影视剧情、现实案例

如果用户提供了一篇爆文让你拆解，后续仿写时只能继承：

- 小节功能
- 叙事顺序
- 情绪推进
- 观点收束方式
- 标题公式、情绪按钮、信息差和变量槽位

不能继承：

- 原文小标题
- 原文标题的具体关键词、人物、数字、事件细节
- 原文名言名句
- 原文书籍引用
- 原文电视剧或现实案例
- 原文的核心比喻或高度相似的表达

## 爆文拆解沉淀框架（半自动）

当用户说"拆一下这篇爆文""拆解这篇，存到框架库""把这篇沉淀成框架"时，优先使用半自动 CLI，而不是只靠会话手工写 YAML。

### 第0步：抓取微信文章全文

**`browser_navigate` 打开微信文章会超时，必须用 curl 抓取再解析。**

```bash
curl -sL -o /tmp/wx_article.html --max-time 15 "https://mp.weixin.qq.com/s/xxx" \
  -H "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
```

然后用 Python HTML parser 提取标题、作者、正文（不要用 `wechat-article-scraper`，那个走浏览器自动化，会超时）：

```python
from html.parser import HTMLParser

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
        attrs_dict = dict(attrs)
        if attrs_dict.get("id") == "activity-name":
            self.in_title = True
        elif attrs_dict.get("id") == "js_name":
            self.in_author = True
        elif attrs_dict.get("id") == "js_content":
            self.in_content = True
        elif tag in ("p", "br", "section") and self.in_content:
            if tag == "section":
                self.in_section = True
            if self.current.strip():
                self.paragraphs.append(self.current.strip())
                self.current = ""

    def handle_endtag(self, tag):
        if tag in ("span",) and self.in_title:
            self.in_title = False
        elif tag in ("a",) and self.in_author:
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
print(f"标题: {p.title.strip()}")
print(f"作者: {p.author.strip()}")
for para in p.paragraphs:
    print(para)
```

提取后保存为 `article.md`（纯 Markdown 正文，去掉页面底部 JS 垃圾），再进入 prepare 步骤。

### 半自动 CLI 步骤

```bash
# 1. 生成拆解提示词包
python3 wechat-article-pipeline/scripts/framework_extract.py prepare \
  --article /path/to/article.md \
  --title "爆文标题" \
  --source-url "https://mp.weixin.qq.com/..." \
  --account "对标账号" \
  --lane auto

# 2. 当前会话 LLM 读取 extract.prompt.md，生成 draft.yaml

# 3. 校验草案
python3 wechat-article-pipeline/scripts/framework_extract.py validate \
  --draft wechat-article-pipeline/work/framework-extract/xxx/draft.yaml

# 4. 比较正文结构和标题结构，判断新建还是更新
python3 wechat-article-pipeline/scripts/framework_extract.py compare \
  --draft wechat-article-pipeline/work/framework-extract/xxx/draft.yaml

# 5. 用户确认后安装
python3 wechat-article-pipeline/scripts/framework_extract.py install \
  --draft wechat-article-pipeline/work/framework-extract/xxx/draft.yaml \
  --mode new

# 6. 写入飞书多维表格（不可跳过）
# 详见下方"完成检查清单"

# 7. 沉淀到 strategy-material-engine（不可跳过）
# 详见下方"完成检查清单"

# 8. 清理临时文件
rm -rf wechat-article-pipeline/work/framework-extract/xxx
rm -f /tmp/wx_article.html
```

### 完成检查清单（拆解完成后必须逐项确认）

每次爆文拆解完成后，在结束之前必须逐项确认以下清单。任何一项未完成，任务不算结束。

```
[ ] 1. curl 抓取 + Python 提取正文 → 保存为 article.md
[ ] 2. framework_extract.py prepare → 生成 extract.prompt.md + draft.yaml
[ ] 3. 读取 extract.prompt.md → 生成 draft.yaml（用 yaml.dump，不要手写）
[ ] 4. framework_extract.py validate → 校验通过
[ ] 5. framework_extract.py compare → 确认新建还是更新
[ ] 6. framework_extract.py install --mode new/update → 框架入库
[ ] 7. 写入飞书多维表格（record-upsert，按文章链接查重）
[ ] 8. 导入 strategy-material-engine：source 入库 + 按复用价值提取原子素材 + 刷新索引
[ ] 9. 清理临时文件（work/framework-extract/xxx + /tmp/wx_article.html）
```

**第7步飞书写入规范：**

读取 `wechat-topic-spy/references/feishu-config.yaml` 获取配置，按以下流程执行：

```bash
# 搜索是否已存在（用 URL 中 s/xxx 部分作为关键词）
EXISTING=$(lark-cli base +record-search \
  --base-token <base_token> \
  --table-id <table_id> \
  --json '{"keyword":"<URL唯一片段>","search_fields":["文章链接"]}' \
  -q '.data.items[0].record_id')

# 存在则更新，不存在则创建
if [ -n "$EXISTING" ]; then
  lark-cli base +record-upsert \
    --base-token <base_token> --table-id <table_id> \
    --record-id "$EXISTING" --json '<JSON对象>'
else
  lark-cli base +record-upsert \
    --base-token <base_token> --table-id <table_id> \
    --json '<JSON对象>'
fi
```

写入字段从 draft.yaml 中提取，映射关系见 feishu-config.yaml 的 field_mapping：
- `title` → 文章标题
- `source_article.account` → 公众号
- `source_article.url` → 文章链接
- `source_article.extracted_date` → 拆解日期
- `lane` → 赛道
- `id + name` → 使用框架
- `title_pattern.formula` → 标题公式
- `title_pattern.reusable_templates` → 可复用标题模板
- `hook_pattern` → Hook模式
- `title_pattern.emotion_trigger` → 情绪触发
- `section_flow` → 结构类型（用简短描述，如"时间线叙事+视角切换+归因翻转"）
- `suitable_topics` → 适合选题（数组）
- `lane` → 适合目标号
- 爆文级别 → 待填（用户回填或后续补充）
- `summary` 或 AI 判断 → 参考价值
- `extraction_notes` → 拆解备注
- 从原文摘取 2-3 条最有力的句子 → 金句摘录

**写入失败时打印错误但不中断流程，继续处理下一篇。每篇写入后打印：`✅ 已写入飞书：<文章标题>`**

**第8步素材/知识库沉淀规范：**

每篇文章完成框架入库和飞书写入后，必须把同一篇解析后的 `article.md` 导入 `~/.hermes/skills/strategy-material-engine`。素材入库失败时打印错误，但不回滚已经完成的框架入库和飞书写入。

### 1. 导入原文 source

使用绝对路径调用素材引擎，避免 `--root` 受当前工作目录影响：

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

导入后记录输出里的 source 路径，例如 `sources/materials/<slug>.md`，后续素材文件的 `source_refs` 填这个路径。

### 2. 提取可复用原子素材

当前会话通读正文后，只提取真正有复用价值的素材。素材数量不是验收硬指标：

- 干货型 3000-5000 字文章：通常提取 4-8 条
- 情绪文、观点短文、低密度文章：可只提 1-5 条
- 信息密度很低时：只导入 source，不强行凑素材

常见素材类型：

- `method`：结构、流程、写法、SOP、表达方法
- `insight`：反常识洞察、本质判断、认知翻转
- `story`：可复用但需改写的故事型素材
- `quote`：短句、金句、口语化表达
- `data`：数字、对比、可作为论据的信息
- `playbook`：带适用条件的具体打法

每条素材先用 `new_material.py` 创建草稿：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/new_material.py \
  "<素材标题>" \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --type method \
  --date "<YYYY-MM-DD>"
```

然后填充完整 frontmatter 和正文。必须补齐：

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

### 3. 刷新索引并验证

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/flush_indexes.py \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --all
```

刷新后用文章核心关键词验证新内容可以被写作素材搜索召回：

```bash
/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/search_knowledge.py \
  "<文章核心关键词>" \
  --mode writing \
  --root /Users/naipan/.hermes/skills/strategy-material-engine \
  --disable-query-rewrite
```

拆解必须同时包含两层资产：

- 正文结构框架：`hook_pattern`、`section_flow`、`ending_pattern`、`constraints` 等
- 爆款标题结构：`title_pattern`，包括 `formula`、`hook_point`、`reader_promise`、`emotion_trigger`、`information_gap`、`variable_slots`

`title_pattern` 是后续可复用资产，不是备注。它会用于后续标题生成、选题分析或标题方法库扩展；拆解时只保留标题结构和变量槽位，不照搬原标题。

## Channel 配置（先选频道，再加载人设）

**每次创作前，必须先确定这篇文章发到哪个 channel。**

channel 定义存放在 `wechat-factory/channels.yaml`，每个 channel 至少包含：

- `persona`：使用哪套内容约束
- `archive_account`：文章落到哪个归档目录
- `profile`：后续发布时使用哪个公众号登录态

所有人设文件存放在 `wechat-factory/persona-<标识>.yaml`，账号清单见 `wechat-factory/persona-README.md`。

当前已注册 channel / persona：

| channel | persona | 账号 | 读者画像 |
|---------|---------|------|---------|
| `emotion` | `auntie` | 情感号 | 45-65岁中老年 |
| `tech` | `tech` | 技术号 | 技术人员 |

**加载规则：**
1. 用户指定了 channel → 先读取 `channels.yaml` 中对应 channel
2. 用户没指定 → 主动询问“这篇要发到哪个 channel / 账号？”
3. 根据 channel 中的 `persona` 读取对应 `persona-<标识>.yaml`
4. 如果 channel 不存在 → 提示“这个 channel 还没有配置，需要先在 channels.yaml 里创建”
5. 如果 channel 存在但 persona 不存在 → 提示“这个 channel 绑定的人设还没有创建”

**读取人设后，严格遵循其中的：**
- 叙述者身份和视角
- 语气风格和用词习惯
- 例子体系（用什么场景、什么人物）
- 禁忌事项（什么不能写、什么句式不能用）

**开新矩阵号 / 新增赛道时：**

1. 复制一个现成的 `persona-*.yaml`，修改内容，文件名用新标识
2. 在 `channels.yaml` 里新增一个 channel，绑定新的 `persona`

这样无论后面新增多少种内容类型，只要补一份 persona 和一条 channel 映射，整条链路都能继续工作，不需要改 skill 代码。

## Framework 推荐（先给候选，再编号选择）

**写文章前，不建议直接人工在大框架库里盲选。**

推荐流程：

1. 先确定 `channel`
2. 根据 `channel` 得到 `lane`
3. 输入选题、传播目标、素材形态、素材完整度
4. 让推荐器先给出 `Top 3` 框架候选
5. 用户直接回复编号 `1/2/3`
6. 当前会话按已选框架的爆文标题样式先生成 3 个标题候选和置信度评分，让用户选择/重出/自填
7. 标题确认后，才能进入大纲准备

框架推荐脚本：

```bash
python3 wechat-article-pipeline/scripts/recommend_framework.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy
```

推荐 + 编号选择一体化脚本：

```bash
# 第一步：先看 Top 3
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy

# 第二步：直接选 1 号框架，先生成标题推荐指令包
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1

# 当前 AI CLI 读取生成的 *.title.prompt.md，输出 3 条标题和置信度；
# 用户回复 1/2/3、不满意重出，或直接给自己的标题。

# 第三步：传入用户确认的标题，默认只准备大纲生成指令包
# 注意：脚本不调用 LLM；在哪个 AI CLI 会话发起任务，就由当前会话读取 outline.prompt.md 生成 outline.yaml
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1

# 第四步：当前 AI CLI 生成 outline.yaml 后，回传给脚本做分节素材召回和新版 prompt
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --outline-file wechat-article-pipeline/work/framework-flow/xxx.outline.yaml

# 旧流程降级：显式跳过大纲，只做整体素材召回生成写作 prompt（不推荐）
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --legacy-brief-materials

# 已确认标题后（降级）：跳过素材召回，只能用于旧流程；不要和 --outline-file 混用
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --legacy-brief-materials \
  --no-materials

# 已回传 outline.yaml 后：如需直接生成初稿，追加 --generate-draft
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --outline-file wechat-article-pipeline/work/framework-flow/xxx.outline.yaml \
  --generate-draft
```

选中编号后，脚本会生成以下产物：

- `wechat-article-pipeline/work/framework-flow/*.title.prompt.md`：给当前 AI CLI 会话生成 3 个标题候选的指令包（选框架后、传入 `--title` 前生成）
- `wechat-article-pipeline/work/framework-flow/*.yaml`：brief；标题确认后会写入 `article_title`
- `wechat-article-pipeline/work/framework-flow/*.outline.prompt.md`：给当前 AI CLI 会话生成 outline.yaml 的指令包（标题确认后默认生成，也可显式传 `--prepare-outline`）
- `wechat-article-pipeline/work/framework-flow/*.prompt.md`：可直接用于写稿的 prompt 包（默认必须在 `--outline-file` 回传后生成；旧整体召回需显式传 `--legacy-brief-materials`）
- `wechat-article-pipeline/work/framework-flow/*.outline.yaml`：当前 AI CLI 生成的大纲文件；通过 `--outline-file` 回传给脚本消费
- `wechat-article-pipeline/work/framework-flow/*.draft.template.md`：本地可直接补写的半成稿模板
- `wechat-article-pipeline/work/framework-flow/*.theme.yaml`：排版主题推荐结果（结构化）
- `wechat-article-pipeline/work/framework-flow/*.theme.md`：排版主题推荐说明（人工可读）
- 如追加 `--generate-draft`，还会生成 `wechat-article-pipeline/work/framework-flow/*.draft.md`
- 如果本地 `codex exec` 失败，命令会直接失败；重新执行即可，不做额外回退

### 编号协议

- `1/2/3`：直接选择候选框架；如果未传 `--title`，进入“标题选择”状态，只生成 `*.title.prompt.md`
- 选择 `1/2/3` 后，必须先确认标题，并通过 `--title` 传入最终标题；标题确认后默认进入大纲准备，不直接写正文 prompt
- `8`：重推，偏点击
- `9`：重推，偏完读
- `10`：重推，偏收藏
- `11`：补充素材后再推荐
- `12`：现有框架都不合适，生成新框架草案

### 不满意时的回退顺序

如果第一轮候选都不满意，默认按这个顺序回退：

1. 补传播目标
2. 补素材形态
3. 改成多路推荐
4. 进入新框架草案模式

## 默认工作流

### 注意：降AI味和违禁词排查没有自动化脚本

`emotion-opinion-humanizer` 和 `banned-word-guard` 是手动检查清单/指南，没有可执行的 Python 脚本。

**降AI味（手动）**：读取 humanizer skill 的 patterns.md，对照初稿做 targeted patch。重点改后半段（总结区、方法区、结尾区），前半段故事区通常问题不大。常见修改：打乱过整齐的排比、删重复收尾句式、去说教感。

**违禁词排查（手动）**：读取 banned-word-guard 的 word-lists.md，逐类扫描。技术类文章主要检查绝对化用语（"最好""第一""首创"等），医疗健康类要额外扫五类红线。

**平台风控红线（写稿时必须遵守）**：文章正文中绝不能提"用自动化发公众号/流水线发布公众号/Agent自动发文/自动推送到草稿箱"等描述。微信算法会据此判定为批量自动化发布行为，导致限流甚至封号。举例时用测试自动化、数据处理、工作流提效等其他领域，不要拿公众号本身的自动化流程举例。此规则不限于技术号，所有 channel 均适用。

### 场景A：从零开始写

当用户只给一个主题或方向时：

1. **先定 channel**：确认这篇文章发到哪个 channel
2. **加载人设**：根据 channel 读取对应的人设配置文件
3. **推荐框架（不可跳过）**：必须跑 `recommend_framework.py` 或 `framework_flow.py`，从框架库中筛出 Top 3 候选，展示给用户选择。即使选题很明确、即使你觉得"肯定是某个框架"，也不能跳过这一步——让用户确认框架选择，保证过程可控
4. **编号选择**：优先让用户直接回复 `1/2/3`
5. **标题推荐与用户选择（大纲前强制执行）**：选框架后先跑 `framework_flow.py --code N`，脚本只生成 `*.title.prompt.md`，不调用 LLM。当前 AI CLI 会话读取这个 prompt，根据已选框架的爆文标题样式产出 3 条推荐标题和置信度评分，并按评分从高到低排序。
   - **必须让用户自己选**：输出 3 条标题后，让用户回复 `1/2/3`；用户也可以直接给一个自己的标题。
   - **用户不满意时**：如果用户给修改建议，当前会话按同一框架标题样式 + 用户建议重出 3 条不同标题；如果用户不给建议，只说不满意，也重出 3 条不同标题。只要用户仍不满意，就继续重复这一轮。
   - **标题确认后继续**：用户选择或自填标题后，后续命令必须追加 `--title "<最终标题>"`。没有 `--title` 时，脚本不允许进入大纲准备、正文 prompt 或 draft 生成。
6. **大纲准备（强制主路径）**：标题确认后跑 `framework_flow.py --code N --title "<最终标题>"`，脚本默认只生成 `*.outline.prompt.md`，不调用 LLM；在哪个 AI CLI 会话发起写作任务，就由当前会话读取这个 prompt 并生成 `*.outline.yaml`。也可以显式追加 `--prepare-outline`，效果相同。
   - **当前会话生成大纲**：Codex / Claude Code / Hermes 等当前 CLI 负责生成结构化大纲，脚本不写死具体模型。
   - **大纲文件回传**：生成 `outline.yaml` 后，用 `framework_flow.py --code N --title "<最终标题>" --outline-file <path>` 回传给脚本。脚本会校验 section 数量、标题、core_viewpoint、supporting_angles 等字段。
   - **大纲结构**：每节包含 `title / function / reader_question / core_viewpoint / evidence_need / supporting_angles / transition_to_next / materials`。其中 `materials` 保持空列表，后续由脚本填充。
   - **开头质量约束**：大纲第一节 title 不能照搬文章标题，也不能只是把标题稍微缩短或换几个字；必须写成承接开头的具体场景、动作或冲突。正文开头也必须先有 3-6 个自然段的无标题引入段，再进入第一个小标题。
7. **分节素材召回（大纲后、动笔前）**：传入 `--outline-file` 后，脚本根据每节的 `core_viewpoint + title + topic anchor + supporting_angles` 做分节召回，每节最多挂 1-2 条可选参考，并全局去重。召回结果只注入 `primary_claim`，不注入原文正文。
   - **Query 扩写**：无 outline 时，`fetch_materials_for_brief()` 仍按旧逻辑从 topic + section_flow + required_materials 提取核心语义片段，与 section 维度关键词组合生成多个 query。传入 outline 时，改用 `fetch_materials_for_outline_sections()` 做按节召回。
   - **类型软偏好**：不再用 `--type` 硬过滤（如 `material_types=['case']` 不再挡掉 method/insight）。material_types 转为 `--prefer-type` soft bonus，框架 required_materials 匹配的 prefer_type 优先级更高。这样高相关的非目标类型素材不会被排除。
   - **隐私防护（自动执行）**：同一来源最多召回 1 条（`--max-per-source 1`），防止整文还原导致抄袭风险。注入 brief 的只是观点方向，LLM 会用自己的表达重新阐述。
   - **素材库降级开关**：`framework_flow.py` 支持 `--no-materials` 参数。它只能和 `--legacy-brief-materials` 一起用于不回传 outline 的旧流程降级；`--outline-file` 回传阶段默认必须执行分节素材召回，不能同时传 `--no-materials`。脚本会在 brief、prompt 和终端输出中记录 `section_materials_recall` 状态，避免误以为已经带素材写稿。
   - 如果用户通过 `--extra-materials` 手动提供了素材，与自动召回的结果合并，手动素材优先
   - **兜底方案（无召回时）**：不硬塞不相关素材。brief 的 auto_materials 为空列表，写稿 prompt 标注"素材供参考，不适用可以不用"。LLM 本身有知识储备，没有外部素材也能写合格内容。素材库的作用是提升质量，不是救命。
   - 如需手动召回：`/opt/miniconda3/bin/python3 /Users/naipan/.hermes/skills/strategy-material-engine/scripts/search_materials.py "<query>" --root /Users/naipan/.hermes/skills/strategy-material-engine --limit 5 --max-per-source 1`
   - **演进路线**：当前方案升级为 A+（当前 AI CLI 生成大纲 → 脚本按节召回 → 写正文）。脚本不默认内置 `codex exec` 生成大纲；未来产品化后再把大纲生成替换为明确的大模型 API。
8. 判断文章类型：
   - 情绪文
   - 观点文
   - 情绪 + 观点混合文
9. 明确目标读者、情绪按钮、传播方向（必须与人设配置中的读者画像一致）
10. 先写正文初稿（必须以人设配置中的叙述者身份来写，将分节召回的素材自然嵌入正文）
11. 写完后自动执行一次"轻度降 AI + 增加人味"的后处理
12. 做违禁词排查（使用 `banned-word-guard`），发现违禁词自动替换为安全表达
13. 根据 `channel + framework + goal + 内容特征` 推荐排版主题（Top 3）
14. 最后补齐发布素材：
   - 封面风格选择（必须让用户从 `accent-bar` / `AI 文生图 - 火山引擎` / `AI 文生图 - SenseNova` 中选择；AI 文生图不再推荐风格，直接由当前会话 LLM 生成场景化提示词后用 `generate_cover_ai.py --provider <provider>` 调 API）
   - 标题备选（必须符合人设配置中的标题风格）
   - 摘要
   - 导语
   - 封面主标题 / 副标题
15. 发布分支：
   - 微信公众号长文：`final.md` → `article.html` → `cover.jpg` → `publish_wechat.py publish`
   - 小绿书贴图：准备多张图片后，直接用 `publish_wechat.py xls-publish --images ... --title ... --description ...`
   - 小绿书分支仍必须在正文完成、降 AI 味和违禁词扫描之后执行；标题和描述必须显式传参，不从 `final.md` 自动推断

### 场景B：已有初稿

当用户已经给出文章初稿时：

1. 判断是否需要重写，只在必要时重写
2. 默认先做轻度降 AI 和人味增强
3. 再补标题、摘要、封面文案

### 场景C：只要发布包装

当用户只说“补标题摘要封面”时：

1. 不重写正文
2. 根据正文内容给出：
   - 3 到 9 个标题备选
   - 1 到 3 个摘要
   - 1 到 2 个导语
   - 封面主标题 / 副标题

## 情绪文 / 观点文默认标准

### 初稿阶段

优先保证：

- 选题踩中痛点
- **正文开头必须是无标题引入段**：用场景/事件/悬念把读者拉进文章，禁止第一行就是跟文章标题重复的小标题（读者一进来就看到标题重复，会缺少"被拉进来"的感觉，直接推进论点显得突兀）
- 开头 3 句内有冲突
- 第一个正文小标题不能直接引用文章标题，也不能只是标题的轻微改写；它要承接开头里的具体情境、动作或冲突
- 故事有升级
- 后半段能从个案跳到共性
- 有可传播句，但不要过密
- 如果使用分节编号，默认采用“编号 + 语义小标题”格式，不要只写 `01`、`02`、`03`
- 如果参考过爆文拆解，生成时必须换掉标题系统、例子系统和比喻系统，避免出现洗稿感

### 小标题规则

公众号稿默认建议分成 3 到 6 个小节。小标题格式按账号区分：

**情感号（auntie）**：使用"编号 + 语义小标题"格式，制造阅读节奏。

- `## 01｜她以为只是随口一说`
- `## 02｜外甥登门，真正的目的露出来了`
- `## 03｜人到晚年，真正要守住的是边界`

不要写成：

- `## 01`
- `## 02`
- `## 03`

纯数字只有分段作用，没有信息增量。

**技术号（tech）**：直接使用语义小标题，不加编号前缀。

- `## 先定规则：什么样的需求值得记录`
- `## 采集层：从哪些市场捞数据`
- `## 实操节奏：第一周就能跑起来`

技术号读者扫读习惯强，小标题本身就能传达信息，编号是多余的噪音。

### 润色阶段

优先修正：

- 总结区太工整
- 解决方案太像模板
- 结尾太像标准答案
- 句式过于对称
- 金句密度过高

### 文末钩子（必须执行）

每篇文章末尾需要加两个钩子，写在正文最后的分割线之后：

**评论钩子**：问一个读者有经历、有情绪、能一句话说完的具体问题。
- 好："你在外包待了几年？有没有过类似的'突然醒过来'的时刻？"
- 好："你用AI工具最大的感受是什么——效率起飞了，还是活儿越来越多了？"
- 差："你怎么看这个现象？"（太宏大，没人想打字）
- 差："欢迎在评论区留言。"（没有具体问题，等于废话）
- 原则：问题要具体、跟文章内容直接相关、让读者觉得"我有话说"

**关注钩子**：跟文章内容有关联，让读者觉得"后面还有我想看的"。
- 好："这篇是'外包系列'第一篇，后面我会拆解外包经历怎么在简历上讲。关注这个号。"
- 好："我最近在用AI做几件事，踩了很多坑，会陆续写出来。想看技术人的AI实战记录，关注一下。"
- 差："喜欢请关注。"（没有信息量）
- 差："每天更新，精彩不容错过。"（广告味太重）
- 原则：给出一个具体的后续内容预告，而不是空洞的求关注

格式示例：
```
---

你现在用AI工具吗？用下来最大的感受是什么？评论区聊聊。

这篇是"技术人转型"系列的第一篇，后面我会写离职后踩的那些坑。关注这个号，别走丢了。
```

注意：评论钩子和关注钩子之间可以用空行分隔，不需要编号或标题。保持口语化，像号主跟读者说话的语气。

### 发布阶段

优先补齐：

- 高点击标题
- 稳妥标题
- 摘要
- 导语
- 封面文案

## 输出要求

默认按这个顺序交付：

1. 正文最终版（Markdown）
2. 标题备选
3. 摘要
4. 导语
5. 封面文案

如果用户只要其中一部分，就只输出那一部分。

### `final.md` 内容边界（重要）

`final.md` **只能保存正文终稿 + frontmatter**，不能把下面这些发布素材继续追加到同一个文件里：

- 标题备选
- 摘要
- 导语
- 封面文案

原因：`wechat-publisher` 会把 `final.md` 转成 `article.html` 并直接发布；如果把发布素材也塞进 `final.md`，这些内容就会进入公众号正文。

正确做法：

- `final.md`：只放正文终稿
- 会话回复：再单独列出标题/摘要/导语/封面文案
- 如需落盘：另存为 `publish-materials.md` 或结构化 JSON，但不要混入 `final.md`

### 产物保存规则（必须执行）

**流水线产出的 final.md 必须保存到统一目录，不能只输出到会话内存。**

保存路径规范：
```
~/.hermes/output/wechat/<account>/articles/<日期_标题>/final.md
```

- `account`：账号标识，情感号用 `emotion`，技术号用 `tech`
- `日期`：`YYYY-MM-DD` 格式
- `标题`：文章标题去掉特殊字符（`\/:*?"<>|` 替换为 `_`），最长50字

**执行时机**：流水线最后一步，用 `write_file` 把**仅包含正文终稿**的 Markdown 保存到上述路径。标题/摘要/封面文案可以继续在回复中给出，但不要追加进 `final.md`。

**示例**：
```
~/.hermes/output/wechat/emotion/articles/2026-04-15_人到晚年真正要守住的是边界/final.md
~/.hermes/output/wechat/tech/articles/2026-04-15_我用AI Agent搭了一条爆文生产线/final.md
```

**后续衔接**：`wechat-publisher` 发布时会自动读取这个目录，并在重新发布时自动版本归档。详见 `wechat-publisher` skill 的"产物归档规范"。

### 排版主题推荐（已接入）

`framework_flow.py` 在你选择框架后，会自动推荐一轮排版主题。

推荐依据：

- `channel -> lane / persona`
- `framework subtype`
- `goal`
- `material_types / material_depth`

如果追加了 `--generate-draft`，脚本还会再读取生成出来的 `draft.md`，自动分析：

- `contains_code`
- `contains_table`
- `article_length`
- `emotional_density`

然后刷新一次主题推荐结果。

输出文件：

- `*.theme.yaml`：结构化推荐结果
- `*.theme.md`：人工可读说明

正文定稿后，转 `article.html` 时优先使用其中的 `recommended_theme`。

如果你已经有 `final.md`，可以直接在框架流命令里补上：

```bash
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --final-md /path/to/final.md
```

脚本会继续复用刚生成的 `*.theme.yaml`，并自动输出 `article.html`。

### 正文排版默认要求

如果输出公众号版正文，默认遵循：

- 小节标题优先使用“编号 + 语义标题”
- 每个小节标题都要概括该节核心信息
- 不要出现只有编号、没有标题文字的小节
- 小标题语气要自然，避免太像 PPT 提纲
- 正文字号默认 15px
- 面向中老年读者的号，正文字号使用 17px
- 正文段落默认两端对齐：`text-align: justify`
- 正文段落默认首行缩进：`text-indent: 1.6em`
- 正文行间距默认：`line-height: 1.6`

中老年读者优先按 `audience_age=senior`、`persona=auntie`、`channel=emotion` 判断。

## 踩坑记录

### 个人经历叙述中的"转型链路"要补因果链
写作者本人的职业转型经历时，不能只列里程碑（功能测试→Java开发→自动化→AI），否则读起来像简历bullet points硬拼，跨度太大、不连贯。每个转折必须补上：
- 为什么能转到下一个岗位（平时有积累/领导知道/自学过基础）
- 为什么只做了一段时间就转走（项目结束/主动选择/发现自己更适合什么）
- 转折是主动选择还是被动接受（主动选择更真实可信）
- 下一个阶段的触发条件是什么（具体问题/项目需求/效率痛点）
用户反馈原话："比如你是功能测试，肯定你平时有积累，有学习，公司才会内部转岗。而且做一年Android开发，是基于什么条件回归的测试部门。这个转折要看起来真实可信。"
注意：如果开头引入段已经详细展开了转型链路，后面"经历拆解"节要精简或删掉，避免重复。

框架库 YAML 文件中的 `keywords` 字段可能混入 float 值（如未加引号的数字被 YAML 解析为 float），导致 `count_keyword_hits()` 报错 `AttributeError: 'float' object has no attribute 'lower'`。

已修复（2026.4.21）：在 `count_keyword_hits()` 中加了 `isinstance(word, str)` 过滤。如果未来重新遇到，检查框架库 YAML 里 `keywords` 列表是否有未加引号的纯数字。

### draft.yaml 手写 YAML 容易解析失败

用 `write_file` 手写 draft.yaml 时，YAML list item 中的引号、冒号、特殊符号经常导致 `yaml.safe_load` 解析失败（报 `expected <block end>, but found '<scalar>'`）。常见触发场景：constraints 列表里包含 `\"写在最后\"`、`（"不是A，而是B"）` 等嵌套引号。

**解决方案：用 Python `yaml.dump()` 生成 draft.yaml，不要手写。**

```python
import yaml
data = { ... }
with open("draft.yaml", "w") as f:
    yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
```

这样 Python 会自动处理所有引号转义和特殊字符，保证 YAML 合法。生成后再跑 validate 和 compare。

### 严禁 `--no-materials` 与 `--outline-file` 同时使用

2026.4.29 实际犯错：回传 outline.yaml 时顺手加了 `--no-materials`，导致所有 section 的素材召回全部跳过，每个 section 都是"无（素材库未找到可信匹配）"。文章变成纯靠 LLM 自己组织论证，没有经过素材库支撑。

**正确做法：**
- 传入 `--outline-file` 时，绝对不加 `--no-materials`。脚本会自动按节做素材召回。
- `--no-materials` 只用于"不回传 outline 的降级流程"（比如用户只要一个 quick brief，不需要分节素材）。
- 写稿前检查 prompt.md 里的"分节素材指引"部分，如果每个 section 都是"无"，说明素材召回被跳过了，需要重新跑一遍。

### 执行效率：素材读取过多导致上下文膨胀、推理变慢

2026.5.7 实际踩坑：在 framework_flow 流程中，素材准备阶段读入了过多大文件（一篇 1371 行的帖子全文、完整的 skill 文件、prompt 模板等），导致上下文膨胀到几万 token。后续每一步推理都要过一遍完整上下文，越往后越慢，用户反复催促"开始了么"。

**根因：**
- 大文件整文件灌入（应该只读需要的段落，用 offset+limit 控制）
- 同一关键词反复搜索（"原子拉片课"搜了三遍）
- 素材文件逐个 read_file 全文读取（应该 search_files 定位后再只读关键片段）

**正确做法：**
1. 先精确搜（search_files + context + limit 控制返回量），不要广撒网再筛选
2. 大文件只读需要的段落，不整文件灌入上下文
3. 素材召回一次到位，不要反复搜同一关键词
4. 标题选完直接跳到写稿，中间文件能不读就不读
5. 素材内容记在脑子里（已经读过的素材），不要反复回头 read_file
6. 如果素材已经在前面的上下文中出现，写稿时直接用，不要"为了确认"再去读一遍

**影响链：** 上下文膨胀 → 每轮推理时间增加 → 用户等待 → 反复催促 → 体验差。预防和治理同样重要。

### publish_wechat.py 封面图上传可能超时

封面图上传到微信服务器时，如果网络慢可能超过 60 秒超时。脚本会尝试继续操作（选中图片→点确认），但封面可能未真正上传成功。发布后建议手动在草稿箱确认封面是否正常。连续两篇文章（2026.4.29）都出现这个超时，大概率是网络/微信服务器侧的问题，不是偶发。

### publish_wechat.py Firefox 残留进程导致启动失败

如果上一次发布脚本异常退出（超时被kill、Ctrl+C中断等），Firefox/geckodriver 进程可能残留。下次启动时报错：`invalid session id: WebDriver session does not exist, or is not active`。

**解决方案：发布前清理残留进程**

```bash
pkill -f "firefox.*mp__qiaosan" 2>/dev/null
pkill -f "geckodriver" 2>/dev/null
sleep 2
```

注意 `mp__qiaosan` 是 profile 目录的特征字符串，只杀对应 profile 的 Firefox，不要 `pkill -9 firefox` 杀掉用户自己正在用的 Firefox。

## Invocation Hints

用户可以这样直接调用：

- “用 `wechat-article-pipeline` 做一篇完整公众号稿”
- “围绕 X 写一篇公众号情绪文，写完后自动降 AI，再补标题摘要封面”
- “先写稿，再做轻度降 AI，最后给我一套发布素材”
- “把这篇文章按公众号流水线处理成可发版”
- “做一整套：正文、人味润色、标题、摘要、封面”

更详细的流程说明与推荐话术，见 `references/workflow.md`。
