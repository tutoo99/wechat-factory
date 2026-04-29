# Frameworks 框架库

这里存放“赛道内可复用的文章结构模板”，用于把：

- 爆文收集
- AI 拆解
- 人工复核
- 结构沉淀

变成可重复调用的生产资产。

## 分层关系

- `profile`：发到哪个公众号后台
- `channel`：当前发哪个业务账号
- `persona`：这个号长期怎么说话
- `framework`：这篇文章具体怎么组织结构

## 目录规则

- `frameworks/tech/`：技术赛道框架
- `frameworks/emotion/`：情感赛道框架
- `frameworks/common/`：跨赛道可复用框架

## 使用原则

1. 先根据 `channel` 拿到 `lane`
2. 从 `frameworks/<lane>/` 和 `frameworks/common/` 中筛候选
3. 根据选题、目标、素材形态做推荐
4. 默认返回 `Top 3`
5. 用户用编号 `1/2/3` 选择；不满意时走回退编号

## 推荐输出协议

默认输出：

- `1.` 候选框架1
- `2.` 候选框架2
- `3.` 候选框架3

回退操作：

- `8`：重推，偏点击
- `9`：重推，偏完读
- `10`：重推，偏收藏
- `11`：我补充素材，你再推荐
- `12`：现有框架都不合适，生成新框架草案

推荐与选择一体化脚本：

```bash
# 先给 Top 3 候选
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy

# 直接选 1 号框架，生成写作 brief
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1

# 直接选 1 号框架，并自动生成 draft.md
python3 wechat-article-pipeline/scripts/framework_flow.py \
  --channel tech \
  --topic "我把公众号发布系统重构成 channel 模型" \
  --goal click --goal save \
  --material-type case --material-type opinion \
  --material-depth heavy \
  --code 1 \
  --generate-draft
```

选中编号后，脚本会同时产出：

- `*.yaml`：结构化 brief
- `*.prompt.md`：可直接交给写稿链路的 prompt 包
- `*.draft.template.md`：本地可直接补写的半成稿模板
- `*.draft.md`：如果加了 `--generate-draft`，会直接调用本地 `codex exec` 产出初稿
- 如果 `codex exec` 失败，命令会直接失败；稍后重跑即可

## 拆爆文 → 沉淀框架（半自动 CLI 流程）

反向拆解爆文使用半自动 CLI：脚本负责生成拆解任务包、校验 YAML、和已有框架做去重比较、按确认结果安装；当前 AI CLI 会话负责真正的结构提炼。`framework_flow.py` 只负责从已有框架库推荐，不负责反向拆解。

### 触发词

用户说以下任意一种，即启动拆解流程：

- "拆一下这篇爆文"
- "把这篇沉淀成框架"
- "拆解这篇，存到框架库"
- "拆文" + 粘贴文章

用户可以指定赛道（"按 tech 拆"、"按 emotion 沉淀"），也可以不指定。

### 输入范围

v1 只支持本地 `.txt` / `.md` 或 stdin。文章链接和 DOCX 先由当前会话或其他工具提取成正文文本，再进入拆解流程。

### 标准步骤

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

# 5A. 新建框架
python3 wechat-article-pipeline/scripts/framework_extract.py install \
  --draft wechat-article-pipeline/work/framework-extract/xxx/draft.yaml \
  --mode new

# 5B. 更新已有框架
python3 wechat-article-pipeline/scripts/framework_extract.py install \
  --draft wechat-article-pipeline/work/framework-extract/xxx/draft.yaml \
  --mode update \
  --target frameworks/emotion/health_persuasion.yaml
```

`prepare --lane auto` 不由脚本判断赛道，只在提示词中要求当前会话 LLM 判断并写入 YAML 的 `lane`。如果用户传 `--lane tech/emotion/common`，提示词会要求使用用户指定 lane。

### 必须同时拆两层结构

1. **正文结构骨架**：`hook_pattern`、`section_flow`、`ending_pattern`、`constraints` 等。
2. **爆款标题结构**：`title_pattern`，这是后续标题生成、选题分析或标题方法库可消费的结构化资产，不是备注。

标题拆解必须说明：

- 为什么这个标题会被点开
- 标题承诺给读者什么收益、答案或情绪释放
- 哪个词负责制造冲突、悬念或信息差
- 标题公式里有哪些变量槽位，后续换题时怎么替换
- 哪些元素是可复用结构，哪些元素是原文专属素材，不能搬

### 多篇拆解的去重规则

拆多篇同类型文章时，不要每篇都新建 yaml。流程如下：

1. 拆第 1 篇 → 存 yaml
2. 拆第 2 篇 → 跟已有框架对比结构骨架（`section_flow`、`hook_pattern`、`ending_pattern`）和标题模式（`title_pattern`）
   - 正文结构相同或高度相似 → 提取共性，更新已有 yaml（不新建）
   - 正文结构有明显差异 → 新建一个 yaml，用不同的 subtype 区分
   - 正文不同但标题模式相似 → 可以新建正文框架，但标题模式应考虑合并或复用
3. 拆第 3 篇及之后 → 同理

判断标准：如果 `hook_pattern`、`section_flow` 的推进方式、`ending_pattern` 这三个核心要素基本一样，就算"结构相同"，只保留一个更完善的版本。只有推进逻辑有本质区别时才新建。

### 注意事项

- 拆解的是**结构骨架 + 标题公式**，不是素材（小标题、金句、案例不能直接搬）
- 标题拆解只保留公式、情绪按钮、信息差和变量槽位，不照搬原标题
- 新框架先沉淀为 yaml，连续验证 3-5 次有效后再考虑升级为 skill
- 如果用户提供了一篇爆文既想拆解又想仿写，拆解和仿写是两步：先拆完存框架，再基于框架写新稿

## 拆爆文 → 沉淀框架（旧对话流程）

旧流程仍可作为人工兜底，但优先使用上面的半自动 CLI。

### 触发词

用户说以下任意一种，即启动拆解流程：

- "拆一下这篇爆文"
- "把这篇沉淀成框架"
- "拆解这篇，存到框架库"
- "拆文" + 粘贴文章

用户可以指定赛道（"按 tech 拆"、"按 emotion 沉淀"），也可以不指定。

### 标准步骤

1. **自动判断赛道**：根据文章内容分析读者对象、内容类型、语言风格，判断应该放到哪个 lane（tech / emotion / common）
2. **告知用户判断结果**：把判断依据和结论告诉用户，例如"这篇读者是XX，内容偏向XX，建议放 tech 赛道。确认吗？"
3. **用户确认或纠正**：用户说"对"就继续，用户指定其他赛道就按用户的来
4. **提取结构**：按 `schema.md` 的字段格式，提取 hook_pattern、section_flow、ending_pattern、constraints、keywords 等
5. **存为 yaml**：保存到 `frameworks/<lane>/<subtype>.yaml`
6. **告知用户**：存储路径和简要说明

### 多篇拆解的去重规则

拆多篇同类型文章时，不要每篇都新建 yaml。流程如下：

1. 拆第 1 篇 → 存 yaml
2. 拆第 2 篇 → 跟已有框架对比结构骨架（section_flow、hook_pattern、ending_pattern）
   - 结构相同或高度相似 → 提取共性，更新已有 yaml（不新建）
   - 结构有明显差异 → 新建一个 yaml，用不同的 subtype 区分
3. 拆第 3 篇及之后 → 同理

判断标准：如果 hook_pattern、section_flow 的推进方式、ending_pattern 这三个核心要素基本一样，就算"结构相同"，只保留一个更完善的版本。只有推进逻辑有本质区别时才新建。

### 注意事项

- 拆解的是**结构骨架**，不是素材（小标题、金句、案例不能直接搬）
- 新框架先沉淀为 yaml，连续验证 3-5 次有效后再考虑升级为 skill
- 如果用户提供了一篇爆文既想拆解又想仿写，拆解和仿写是两步：先拆完存框架，再基于框架写新稿
