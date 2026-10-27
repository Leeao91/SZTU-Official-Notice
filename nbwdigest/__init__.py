# -*- coding: utf-8 -*-
"""深圳技术大学「公文通」每日汇总。

抓取公文列表 → 增量比对 → 抓详情页提炼要点 → 生成 Markdown / HTML / JSON 日报，
并可启动一个局域网手机版网页。

用法：
    python -m nbwdigest              # 增量抓取一次
    python -m nbwdigest --test       # 只解析列表
    python -m nbwdigest serve        # 启动手机版服务
"""

__version__ = "1.0.0"

from .core import ROOT, load_config  # noqa: F401

__all__ = ["__version__", "ROOT", "load_config"]
