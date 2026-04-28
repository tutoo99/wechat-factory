#!/usr/bin/env python3
"""兼容入口：转发到 schema-v1 主题包渲染器。"""

from render_wechat_article import main


if __name__ == "__main__":
    raise SystemExit(main())
