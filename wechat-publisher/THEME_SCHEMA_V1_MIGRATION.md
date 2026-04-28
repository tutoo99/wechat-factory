# `theme.yaml` → schema v1 迁移方案（当前仓库已落地版）

这份文档不是抽象设想，而是当前仓库已经执行过一轮后的落地说明。目标只有一个：把“单文件主题”升级成“可扩展、可推荐、可演进”的主题包体系，同时不打断既有 CLI 用法。

## 迁移目标

- 保留旧入口：`md_to_styled_html.py`
- 新增新入口：`render_wechat_article.py`
- 主题结构从单个 `theme.yaml` 升级为 theme pack v1
- 为未来“多套排版风格 + 自动推荐 + 自动渲染”留出扩展位
- 现有发布链路继续可用，不强迫一次性重写所有脚本

## 阶段 1：盘点旧主题资产

旧模型的问题是：颜色、字号、标题样式、代码块样式、适用场景都挤在一个 `theme.yaml` 里。

这会带来 4 个直接问题：

- 元数据和设计 token 混在一起，不利于推荐器读取
- 主题只能“渲染”，很难“理解自己适合什么文章”
- 想新增 block 变体时，只能继续往单文件里堆字段
- 后续做 A/B 风格、多主题扩展、主题市场时不稳定

当前仓库已经完成的盘点结果：

- 旧主题能力被拆成 `manifest / tokens / blocks / heuristics`
- loader 保留了对旧 `theme.yaml` 的兼容读取

## 阶段 2：定义 schema v1

当前仓库的 schema v1 结构如下：

```text
themes/<theme-id>/
├── manifest.yaml
├── tokens.yaml
├── blocks.yaml
├── heuristics.yaml
└── preview.md
```

字段职责：

- `manifest.yaml`：主题 ID、显示名、适用赛道、人设、文章类型、传播目标、安全级别
- `tokens.yaml`：颜色、字号、间距、圆角、边框、阴影等设计 token
- `blocks.yaml`：标题、引用、代码块、表格、图片、分割线等区块变体
- `heuristics.yaml`：推荐器偏好、避让条件、作者提示
- `preview.md`：预览样例，也是回归校验样例

## 阶段 3：先做兼容层，再迁移主题

当前仓库采用的是“先兼容、再迁移”的做法，而不是“一次性切断旧格式”。

关键文件：

- `wechat-publisher/scripts/core/themes/loader.py:1`

loader 的策略是：

1. 优先读取 `manifest.yaml`
2. 如果不存在，就回退读取旧 `theme.yaml`
3. 把旧配置归一成 schema v1 内存结构
4. 渲染器统一只吃归一后的 theme object

这样做的好处是：

- 老命令不挂
- 新主题可以直接按 v1 新建
- 仓库可以分批迁移，而不是一次性迁完

## 阶段 4：迁移内置主题，并补足预览 / 推荐能力

当前仓库已完成：

- 已迁移旧主题：
  - `emotion-warm`
  - `tech-clean`
- 已新增 v1 主题：
  - `dense-note`
  - `magazine-soft`

关键文件：

- `wechat-publisher/scripts/themes/emotion-warm/manifest.yaml:1`
- `wechat-publisher/scripts/themes/tech-clean/manifest.yaml:1`
- `wechat-publisher/scripts/themes/dense-note/manifest.yaml:1`
- `wechat-publisher/scripts/themes/magazine-soft/manifest.yaml:1`

同时已补齐：

- 统一渲染入口：`wechat-publisher/scripts/render_wechat_article.py:1`
- 主题预览批量渲染：`wechat-publisher/scripts/render_theme_previews.py:1`
- 主题推荐器：`wechat-publisher/scripts/recommend_theme.py:1`

## 阶段 5：接入文章流水线闭环

当前仓库已完成的闭环：

1. `framework_flow.py` 选框架后自动生成 `*.theme.yaml`
2. 同时生成人工可读的 `*.theme.md`
3. 写作 prompt / brief 会注入推荐主题
4. 终稿阶段可直接按推荐主题渲染为 `article.html`

关键文件：

- `wechat-article-pipeline/scripts/framework_flow.py:1`
- `wechat-publisher/scripts/render_with_recommended_theme.py:1`

推荐的闭环命令：

```bash
# 1) 选择框架并生成主题推荐
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1

# 2) 正文定稿后，按推荐主题输出 article.html
python3 wechat-publisher/scripts/render_with_recommended_theme.py \
  /path/to/final.md \
  --theme-file wechat-article-pipeline/work/framework-flow/<xxx>.theme.yaml
```

也可以在框架流里直接做收口：

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

## 旧字段到新 schema 的映射

| 旧 `theme.yaml` | schema v1 目标位置 | 说明 |
|---|---|---|
| `name` | `manifest.id` | 主题唯一标识 |
| `display_name` | `manifest.display_name` | 人类可读名称 |
| `description` | `manifest.description` | 主题说明 |
| `colors.*` | `tokens.colors.*` | 设计 token |
| `typography.*` | `tokens.typography.*` | 字体、字号、行高 |
| `section_icons` | `blocks.section_title.icons` | 标题图标旋转策略 |
| `code_style` | `blocks.code_panel.variant` | 代码块视觉变体 |
| 适用场景说明 | `manifest.lane_fit / persona_fit / article_fit / goal_fit` | 给推荐器用 |
| 作者经验备注 | `heuristics.notes` | 给主题推荐和人工判断用 |

## 为什么长期方案要这样设计

长期不是“再多做几个 theme”，而是把主题从“样式配置”升级成“可组合的排版系统”。

schema v1 的价值在于：

- 可以继续新增 block 变体，不必改旧主题结构
- 可以让推荐器按文章特征自动选主题
- 可以做主题预览和回归校验
- 可以以后接入第三方主题包，甚至做主题市场
- 可以逐步演进到 schema v2，而不是重新推翻

## 下一步建议

如果要继续往长期方案走，优先顺序建议是：

1. 引入更多 block-level 变体，而不是只加颜色皮肤
2. 把“对标原文样式分析”沉淀成半结构化 token/block 提取流程
3. 给推荐器补更多内容特征
4. 在发布前增加一次主题 QA 截图比对

现阶段，这个仓库已经完成 schema v1 的最小可用迁移，并且形成了“推荐 → 渲染 → 发布”的基础闭环。
