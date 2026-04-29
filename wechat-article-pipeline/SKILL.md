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

当用户说“拆一下这篇爆文”“拆解这篇，存到框架库”“把这篇沉淀成框架”时，优先使用半自动 CLI，而不是只靠会话手工写 YAML。

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

# 第三步（质量增强）：传入用户确认的标题，只准备大纲生成指令包
# 注意：脚本不调用 LLM；在哪个 AI CLI 会话发起任务，就由当前会话读取 outline.prompt.md 生成 outline.yaml
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --prepare-outline

# 第四步（质量增强）：当前 AI CLI 生成 outline.yaml 后，回传给脚本做分节素材召回和新版 prompt
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --outline-file wechat-article-pipeline/work/framework-flow/xxx.outline.yaml

# 已确认标题后（降级）：跳过素材库召回，brief 中 auto_materials 为空
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --no-materials

# 已确认标题后：如需直接生成初稿，追加 --generate-draft
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --title "我把公众号发布系统重构成 channel 模型，终于不再发错号了" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --generate-draft
```

选中编号后，脚本会生成以下产物：

- `wechat-article-pipeline/work/framework-flow/*.title.prompt.md`：给当前 AI CLI 会话生成 3 个标题候选的指令包（选框架后、传入 `--title` 前生成）
- `wechat-article-pipeline/work/framework-flow/*.yaml`：brief；标题确认后会写入 `article_title`
- `wechat-article-pipeline/work/framework-flow/*.prompt.md`：可直接用于写稿的 prompt 包
- `wechat-article-pipeline/work/framework-flow/*.outline.prompt.md`：给当前 AI CLI 会话生成 outline.yaml 的指令包（仅 `--prepare-outline` 生成）
- `wechat-article-pipeline/work/framework-flow/*.outline.yaml`：当前 AI CLI 生成的大纲文件；通过 `--outline-file` 回传给脚本消费
- `wechat-article-pipeline/work/framework-flow/*.draft.template.md`：本地可直接补写的半成稿模板
- `wechat-article-pipeline/work/framework-flow/*.theme.yaml`：排版主题推荐结果（结构化）
- `wechat-article-pipeline/work/framework-flow/*.theme.md`：排版主题推荐说明（人工可读）
- 如追加 `--generate-draft`，还会生成 `wechat-article-pipeline/work/framework-flow/*.draft.md`
- 如果本地 `codex exec` 失败，命令会直接失败；重新执行即可，不做额外回退

### 编号协议

- `1/2/3`：直接选择候选框架；如果未传 `--title`，进入“标题选择”状态，只生成 `*.title.prompt.md`
- 选择 `1/2/3` 后，必须先确认标题，并通过 `--title` 传入最终标题，才能进入大纲准备/写作准备
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
6. **大纲准备（质量增强，推荐）**：标题确认后优先跑 `framework_flow.py --code N --title "<最终标题>" --prepare-outline`。脚本只生成 `*.outline.prompt.md`，不调用 LLM；在哪个 AI CLI 会话发起写作任务，就由当前会话读取这个 prompt 并生成 `*.outline.yaml`。
   - **当前会话生成大纲**：Codex / Claude Code / Hermes 等当前 CLI 负责生成结构化大纲，脚本不写死具体模型。
   - **大纲文件回传**：生成 `outline.yaml` 后，用 `framework_flow.py --code N --title "<最终标题>" --outline-file <path>` 回传给脚本。脚本会校验 section 数量、标题、core_viewpoint、supporting_angles 等字段。
   - **大纲结构**：每节包含 `title / function / reader_question / core_viewpoint / evidence_need / supporting_angles / transition_to_next / materials`。其中 `materials` 保持空列表，后续由脚本填充。
   - **开头质量约束**：大纲第一节 title 不能照搬文章标题，也不能只是把标题稍微缩短或换几个字；必须写成承接开头的具体场景、动作或冲突。正文开头也必须先有 3-6 个自然段的无标题引入段，再进入第一个小标题。
7. **分节素材召回（大纲后、动笔前）**：传入 `--outline-file` 后，脚本根据每节的 `core_viewpoint + title + topic anchor + supporting_angles` 做分节召回，每节最多挂 1-2 条可选参考，并全局去重。召回结果只注入 `primary_claim`，不注入原文正文。
   - **Query 扩写**：无 outline 时，`fetch_materials_for_brief()` 仍按旧逻辑从 topic + section_flow + required_materials 提取核心语义片段，与 section 维度关键词组合生成多个 query。传入 outline 时，改用 `fetch_materials_for_outline_sections()` 做按节召回。
   - **类型软偏好**：不再用 `--type` 硬过滤（如 `material_types=['case']` 不再挡掉 method/insight）。material_types 转为 `--prefer-type` soft bonus，框架 required_materials 匹配的 prefer_type 优先级更高。这样高相关的非目标类型素材不会被排除。
   - **隐私防护（自动执行）**：同一来源最多召回 1 条（`--max-per-source 1`），防止整文还原导致抄袭风险。注入 brief 的只是观点方向，LLM 会用自己的表达重新阐述。
   - **素材库降级开关**：`framework_flow.py` 支持 `--no-materials` 参数。传入后跳过整体召回和分节召回；如果同时传 `--outline-file --no-materials`，仍生成大纲驱动 prompt，但每节 materials 为空。
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
   - 封面风格选择（必须让用户从 `accent-bar` / `火山引擎文生图` 中选择；火山引擎不再推荐风格，直接由当前会话 LLM 生成场景化提示词后调 API）
   - 标题备选（必须符合人设配置中的标题风格）
   - 摘要
   - 导语
   - 封面主标题 / 副标题

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

### publish_wechat.py 封面图上传可能超时

封面图上传到微信服务器时，如果网络慢可能超过 30 秒超时。脚本会尝试继续操作（选中图片→点确认），但封面可能未真正上传成功。发布后建议手动在草稿箱确认封面是否正常。

## Invocation Hints

用户可以这样直接调用：

- “用 `wechat-article-pipeline` 做一篇完整公众号稿”
- “围绕 X 写一篇公众号情绪文，写完后自动降 AI，再补标题摘要封面”
- “先写稿，再做轻度降 AI，最后给我一套发布素材”
- “把这篇文章按公众号流水线处理成可发版”
- “做一整套：正文、人味润色、标题、摘要、封面”

更详细的流程说明与推荐话术，见 `references/workflow.md`。
