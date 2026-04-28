# 实现计划：大纲驱动 + 分节素材召回 + 独立观点约束

## 背景

当前流水线是"选框架 → 整体召回素材 → 一次性写初稿"。问题：

1. 素材在写稿前一次性全部注入，LLM 容易逐条搬用，缺乏独立思考
2. 素材和 section 没有对应关系，"案例型素材"可能被塞进"观点型小节"
3. 没有"先想清楚再写"的中间步骤，文章后半段容易飘

目标流程：选框架 → **生成大纲（含每节核心观点）** → **按节召回素材** → 写初稿（带独立观点约束）

## 当前流程 vs 目标流程

```
当前：topic → 框架推荐 → 编号选择 → 整体素材召回 → brief+prompt → 初稿 → 降AI → 违禁词 → 发布素材
目标：topic → 框架推荐 → 编号选择 → 整体素材召回(轻量) → 大纲生成 → 按节素材召回 → brief+prompt → 初稿 → 降AI → 违禁词 → 发布素材
```

新增两个步骤（大纲生成、按节素材召回），替换原来的整体素材召回。

## 实现步骤

### Step 1：大纲指令包生成功能（framework_flow.py 新增）

**目标**：在用户选择框架后，生成一个 `*.outline.prompt.md`，由当前 AI CLI 会话生成结构化大纲。脚本不默认调用 Codex / Claude / Hermes / 外部 API。

**新增函数**：`build_outline_prompt(brief, persona) -> str`

大纲结构：
```yaml
outline:
  sections:
    - index: 1
      title: "具体案例发生了什么"
      core_viewpoint: "发文时我把 final.md 当万能文件用，结果导语混进了正文"
      supporting_angles: ["story", "cost"]
      materials: []  # 后续由 Step 2 填充
    - index: 2
      title: "为什么不能只看表面"
      core_viewpoint: "问题不在文件数量，在于你有没有给每个产物划清边界"
      supporting_angles: ["insight", "mistake"]
      materials: []
    # ...
```

**生成方式**：
- `framework_flow.py --code N --prepare-outline` 只生成 outline prompt，不调用 LLM
- 当前 AI CLI 会话读取 `*.outline.prompt.md`，生成 `*.outline.yaml`
- 每个 section 必须有 core_viewpoint（一句话核心观点）
- 后续通过 `framework_flow.py --code N --outline-file <path>` 把大纲回传给脚本

**关键约束**：
- core_viewpoint 必须是独立判断，不能直接复制素材的 primary_claim
- 相邻 section 的 core_viewpoint 不能重复或同义反复
- 最后一个 section 必须是"收束/行动建议"型观点

**新增 CLI 参数**：
- `--prepare-outline`：只生成大纲指令包，不调用 LLM
- `--outline-file`：读取当前 AI CLI 已生成的 outline.yaml，并进入分节召回/写作 prompt 组装

**执行时机**：`framework_flow.py --code N` 之后，在 `--generate-draft` 之前

**产物**：
- `*.outline.yaml`：结构化大纲
- `*.outline.prompt.md`：给当前 AI CLI 生成大纲的指令包

### Step 2：按节素材召回（framework_flow.py 修改）

**目标**：根据大纲每个 section 的 core_viewpoint + supporting_angles 精准召回素材。

**修改函数**：`fetch_materials_for_outline_sections(outline, lane, limit_per_section=2) -> Dict`

**召回策略**：
- 每个独立召回 1 个 query：`section.core_viewpoint + angle_terms(supporting_angles[0])`
- 每个 section 最多召回 2 条素材（limit_per_section=2）
- 全局去重：同一个素材（按 primary_claim 判重）只能出现在 1 个 section
- 如果某个 section 召回为空，不硬塞，留空

**注入方式修改**：
- 不再在 prompt 的"补充素材"区域列出全部素材
- 改为每个 section 内嵌 1-2 条素材作为"可选参考"
- prompt 格式变更：

```
## 大纲 + 素材指引

### 第1节：具体案例发生了什么
核心观点：发文时我把 final.md 当万能文件用，结果导语混进了正文
可选参考：
- [story] 正文和发布素材混在一个文件里，最终很容易把导语摘要误发到正文

### 第2节：为什么不能只看表面
核心观点：问题不在文件数量，在于你有没有给每个产物划清边界
可选参考：
- [insight] 基础设施升级时，先做兼容层再迁移，能显著降低切换风险
```

**降级方案**：
- `--no-materials` 跳过所有素材召回，大纲中每节 materials 为空
- 素材库不可用时（search_materials.py 不存在），自动降级

### Step 3：独立观点约束（build_writing_prompt 修改）

**目标**：在写稿 prompt 中加入明确约束，防止 LLM 直接搬运素材。

**修改位置**：`build_writing_prompt()` 的输出模板

**新增约束条款**（加入"输出要求"区域）：

```
8. 每节必须围绕大纲给定的核心观点展开，用你自己的论证逻辑和案例去支撑
9. 大纲中的"可选参考"只是方向提示，不是要你复述的内容。你可以：
   - 借用它的论证方向，换一个自己的例子
   - 完全不用，用自己的经验推导
   - 取它的部分观点，补充相反或补充的判断
10. 禁止出现"正如XX所说""有人总结过""有篇文章提到过"这类引用句式
11. 如果某个 section 的可选参考与你的真实经验矛盾，以你的经验为准
```

### Step 4：SKILL.md 文档更新

**修改文件**：`wechat-factory/wechat-article-pipeline/SKILL.md`

**更新内容**：

1. 默认工作流"场景A：从零开始写"新增步骤 4.5（大纲生成）和步骤 5（按节素材召回）
2. 更新 framework_flow.py 命令示例，增加 `--prepare-outline` / `--outline-file` 用法
3. 更新 brief 产物说明，新增 `outline.yaml`
4. 更新演进路线描述：当前方案从 A(query扩写) 升级为 A+（大纲驱动分节召回），原计划的方案 C（两阶段）不再需要独立实施

### Step 5：降级与兼容

**原则**：所有新功能都是增量式的，不破坏现有流程。

1. `--prepare-outline` 只生成大纲指令包，不触发后续写稿
2. `--outline-file` 显式传入 outline.yaml 后，自动使用新版 prompt；如果没有传入，降级到旧版整体素材注入
3. 旧版 brief.yaml 中没有 outline 字段的，`build_writing_prompt` 自动识别并走旧逻辑
4. `--no-materials` 同时关闭整体召回和按节召回

## 修改文件清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `wechat-article-pipeline/scripts/framework_flow.py` | 修改 | 新增 build_outline_prompt()、load_outline_file()、fetch_materials_for_outline_sections()；修改 build_writing_prompt() |
| `wechat-article-pipeline/SKILL.md` | 修改 | 更新工作流文档 |
| `wechat-article-pipeline/references/workflow.md` | 修改 | 更新参考文档 |

不需要新增独立脚本文件。所有逻辑都在 framework_flow.py 内完成。

## 验证方式

1. 跑一次 `--prepare-outline` 确认 outline prompt 生成正确
2. 当前 AI CLI 生成 outline.yaml 后，跑一次 `--outline-file` 确认新版 prompt 中素材按节分布
3. 对比新旧 prompt，确认独立观点约束已加入
4. 跑一次 `--generate-draft` 确认完整链路可用
5. 跑一次 `--no-materials` 确认降级正常

## 风险与注意事项

1. **大纲质量依赖当前 AI CLI**：如果当前会话生成的 core_viewpoint 太泛或太偏，会影响后续所有步骤。对策：在大纲 prompt 中加入好的/差的 example，并让用户在 outline.yaml 阶段审阅。
2. **按节召回可能为空**：当前素材库只有 92 条，某些 section 可能召回不到。对策：留空不硬塞，LLM 自己也能写。
3. **整体耗时增加**：多了一轮当前 AI CLI 大纲生成。对策：大纲生成 prompt 保持短而结构化，脚本只负责校验和后续编排。
