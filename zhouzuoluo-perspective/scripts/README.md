# scripts

当前 Skill 附带了一个安全同步脚本，用来把本地 `.claude` 版本同步到全局 `~/.codex/skills`，同时避免误删素材目录。

## `sync_skill_safe.sh`

默认行为：

- 默认只做 dry-run，不会真的写入
- 使用 `rsync --delete` 同步普通 skill 文件
- 默认保护以下素材目录，不会被空目录覆盖删除：
  - `references/sources/books/`
  - `references/sources/articles/`
  - `references/sources/transcripts/`

常用命令：

- 预览同步结果：
  - `./scripts/sync_skill_safe.sh`
- 真正执行安全同步：
  - `./scripts/sync_skill_safe.sh --apply`
- 如果你明确要连素材目录一起同步：
  - `./scripts/sync_skill_safe.sh --apply --with-sources`

说明：

- 推荐平时只用 `./scripts/sync_skill_safe.sh --apply`
- 不要再直接执行 `rsync -a --delete <skill>/ ~/.codex/skills/<skill>/`
- 除非你明确确认源目录里的 `books/`、`articles/`、`transcripts/` 也完整无误，否则不要加 `--with-sources`
