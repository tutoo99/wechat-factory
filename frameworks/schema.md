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
```

## 字段说明

- `lane`：赛道，用于第一轮过滤
- `subtype`：结构类型，用于后续复盘
- `priority`：同分时的优先级
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

## 选择逻辑

推荐器不是直接定框架，而是：

1. 先按 `lane` 过滤
2. 再按 `goal` / `material_types` / `material_depth` 过滤
3. 最后结合 `topic` 和 `keywords` 做排序
