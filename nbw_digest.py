# -*- coding: utf-8 -*-
"""兼容入口：python nbw_digest.py（等价于 python -m nbwdigest）

保留此文件是为了让已有的 Windows 计划任务继续可用。
计划任务里没有控制台，异常会被吞掉，所以这里把任何崩溃写到 logs/crash.log。
"""
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


def _crash(detail: str) -> None:
    try:
        logdir = HERE / "logs"
        logdir.mkdir(parents=True, exist_ok=True)
        with (logdir / "crash.log").open("a", encoding="utf-8") as fh:
            fh.write(detail.rstrip() + "\n")
    except Exception:
        pass


try:
    from nbwdigest.cli import main
except Exception:                      # 例如包被移动、Python 环境损坏
    _crash(traceback.format_exc())
    raise

if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        _crash(traceback.format_exc())
        raise
