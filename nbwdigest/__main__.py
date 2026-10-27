# -*- coding: utf-8 -*-
"""python -m nbwdigest [digest|serve] ..."""
import sys

if __name__ == "__main__":
    # 支持 `python -m nbwdigest serve` 与 `python -m nbwdigest --pages 2` 两种写法
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        from .webapp import main
        sys.argv.pop(1)
    else:
        from .cli import main
    sys.exit(main())
