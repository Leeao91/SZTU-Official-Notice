# -*- coding: utf-8 -*-
"""兼容入口：python nbw_digest.py（等价于 python -m nbwdigest）

保留此文件是为了让已有的 Windows 计划任务继续可用。
"""
import sys

from nbwdigest.cli import main

if __name__ == "__main__":
    sys.exit(main())
