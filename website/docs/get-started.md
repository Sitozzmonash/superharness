---
title: 快速上手
---

可安装的包基础已在阶段 0 中建立。公共的 `Agent` API 将在阶段 1 中提供。

对于贡献者的环境搭建，请克隆仓库，使用 Python 3.11 或更高版本，然后运行：

```bash
python -m pip install -e ".[dev]"
python -m ruff check .
python -m pyright
python -m pytest
```
