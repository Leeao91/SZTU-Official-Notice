# -*- coding: utf-8 -*-
"""兼容入口：python serve.py（等价于 python -m nbwdigest serve）"""
import sys

from nbwdigest.webapp import main

if __name__ == "__main__":
    sys.exit(main())
