# Framework YAML Schema

每个框架文件使用 YAML，建议字段如下：

```yaml
id: tech_mistake_breakdown
name: 踩坑复盘型
lane: tech
subtype: mistake_breakdown
priority: 100
summary: 适合“旧做法低效 -> 踩坑 -> 修复 -> 方法沉淀”的技术内容
suitable_topics:
  - 系统升级
  - 自动化搭建
  - 工具切换
suitable_goals:
  - click
  - read_finish
material_types:
  - case
  - problem
material_depth:
  min: medium
keywords:
  - 踩坑
  - 重构
  - 升级
anti_keywords:
  - 榜单
required_materials:
  - 一个真实低效场景
  - 至少两个踩坑点
  - 一个关键修复动作
hook_pattern: 先给低效场景，再抛出“为什么一直绕”的反问
section_flow:
  - 旧做法为什么别扭
  - 关键坑点怎么暴露
  - 解决动作是什么
  - 最后沉淀成什么可复用方法
ending_pattern: 用一句可复用判断标准收尾
constraints:
  - 不要写成流水账
  - 不要只讲工具，不讲问题
not_for:
  - 纯概念趋势评论
  - 无真实案例支撑的观点文
title_pattern:
  original_title: 爆文原标题
  title_type: 反常识 / 结果前置 / 数字清单 / 冲突悬念 / 身份代入 / 痛点提醒
  hook_point: 标题最抓人的那个信息点
  reader_promise: 标题承诺给读者的收益、答案或情绪释放
  emotion_trigger: 激发的情绪，如焦虑、好奇、委屈、爽感、警醒、获得感
  information_gap: 标题制造的信息差或悬念
  formula: 可复用标题公式，如「看了 X，我才明白 Y」
  reusable_templates:
    - 可替换模板1
    - 可替换模板2
  variable_slots:
    - slot: X
      meaning: 被观察的事件、案例、数据或人群
    - slot: Y
      meaning: 读者最终获得的反常识结论或行动提醒
  constraints:
    - 不要照搬原标题关键词
    - 不要复用具体人物、数字、事件细节，除非是通用结构
source_article:
  url: https://mp.weixin.qq.com/...
  title: 爆文原标题
  account: 对标账号
  extracted_date: 2026-04-29
```

## 字段说明

- `lane`：赛道，用于第一轮过滤
- `subtype`：结构类型，用于后续复盘
- `priority`：同分时的优先级
- `title_pattern`：爆款标题结构，后续标题生成、选题分析或标题方法库会消费这个字段，不是备注
- `title_pattern.formula`：可复用标题公式，只保留结构，不照搬原文专属表达
- `title_pattern.variable_slots`：标题公式里的变量槽位，说明后续换题时每个变量应该替换成什么
- `suitable_goals`：目标集合，推荐值：
  - `click`
  - `read_finish`
  - `save`
  - `share`
  - `comment`
- `material_types`：素材形态，推荐值：
  - `story`
  - `problem`
  - `case`
  - `list`
  - `opinion`
- `material_depth.min`：最低素材完整度，推荐值：
  - `light`
  - `medium`
  - `heavy`

## 校验规则

`framework_extract.py validate` 会执行轻量校验：

- 必填字段：`id`、`name`、`lane`、`subtype`、`summary`、`suitable_topics`、`suitable_goals`、`material_types`、`material_depth`、`keywords`、`required_materials`、`hook_pattern`、`section_flow`、`ending_pattern`、`constraints`、`not_for`、`title_pattern`
- `lane` 只允许：`tech`、`emotion`、`common`
- `material_depth.min` 只允许：`light`、`medium`、`heavy`
- 列表字段必须是 list：`suitable_topics`、`suitable_goals`、`material_types`、`keywords`、`required_materials`、`section_flow`、`constraints`、`not_for`
- `title_pattern` 必须是对象，并至少包含：`original_title`、`title_type`、`hook_point`、`reader_promise`、`emotion_trigger`、`information_gap`、`formula`、`reusable_templates`、`constraints`
- `title_pattern.variable_slots` 是建议字段；缺失时 warning，不阻断
- 未知的 `suitable_goals` / `material_types` 只 warning，不阻断，兼容 `conversion`、`data`、`insight` 等扩展值

## 选择逻辑

推荐器不是直接定框架，而是：

1. 先按 `lane` 过滤
2. 再按 `goal` / `material_types` / `material_depth` 过滤
3. 最后结合 `topic` 和 `keywords` 做排序
