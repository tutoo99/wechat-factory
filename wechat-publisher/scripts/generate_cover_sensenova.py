#!/usr/bin/env python3
"""
SenseNova 文生图 — 公众号封面生成兼容入口

推荐新入口：
  python3 generate_cover_ai.py final.md -o cover.jpg --prompt-file final.cover.prompt.md --provider sensenova

兼容旧入口：
  python3 generate_cover_sensenova.py final.md -o cover.jpg --prompt-file final.cover.prompt.md
"""

from generate_cover_ai import main


if __name__ == "__main__":
    main(default_provider="sensenova")
