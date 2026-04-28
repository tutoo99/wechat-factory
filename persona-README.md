# 人设配置目录

每个人设/内容约束一个独立的 yaml 文件，创作时按映射关系加载。

## 命名规则

`persona-<账号标识>.yaml`

## 和 channel / profile 的关系

- `persona-*`：只负责内容约束、人设、例子体系、禁忌事项
- `channel`：业务入口，决定“这篇文章发哪个号”
- `profile`：浏览器登录态，决定“最终发到哪个公众号后台”

推荐流程：

1. 先在 `channels.yaml` 里选择 channel
2. channel 决定要加载哪个 `persona-*`
3. 发布时再由 channel 反查绑定的 profile

也就是说，`persona` 不等于 `profile`，两者通过 `channels.yaml` 关联。

## 当前 persona

| 文件名 | 账号 | 人设 | 读者画像 |
|--------|------|------|---------|
| persona-auntie.yaml | 情感号 | 退休阿姨本人，第一人称 | 45-65岁中老年 |
| persona-tech.yaml | 技术号 | 乔三本人 | 技术人员（待完善） |

## 新增账号

开新矩阵号时，只需要：
1. 复制一个现成的yaml
2. 修改里面的叙述者身份、语气、读者画像、例子体系
3. 文件名用 `persona-<新标识>.yaml`
4. 在上面的表格里加一行
5. 在 `channels.yaml` 里新增或更新对应 channel，把它指向这个 persona

不需要改任何skill代码。
