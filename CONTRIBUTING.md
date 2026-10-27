# 贡献指南

感谢有兴趣改进这个项目。它是一个**零依赖**的小工具（只用 Python 标准库），
请尽量保持这个特点 —— 不要把 requests / bs4 / lxml 加进来。

## 开发环境

```bash
git clone <your-fork>
cd nbw-digest
python -m unittest discover -s tests -v      # 26 个用例，全部离线
```

不需要 `pip install` 任何东西；`python -m nbwdigest --help` 就能跑。
（`pip install -e .` 可选，装了之后会有 `nbwdigest` / `nbwdigest-serve` 两个命令。）

## 代码结构

| 文件 | 职责 |
|---|---|
| `nbwdigest/core.py` | 抓取、解析、归纳、渲染（纯函数，尽量无副作用） |
| `nbwdigest/cli.py` | 增量对比、落盘、命令行入口 |
| `nbwdigest/webapp.py` | 手机版 HTTP 服务 + 离线单文件导出 |
| `nbwdigest/web/` | 前端（原生 JS，无构建步骤） |
| `tests/` | `unittest` 用例 + `fixtures/` 里的真实页面样本 |

## 加一个解析规则 / 修一个漏抓

1. 先把出问题的页面另存到 `tests/fixtures/`（**去掉 cookie 等个人信息**）。
2. 在 `tests/test_core.py` 里写一个会失败的用例。
3. 改 `core.py` 让它通过。
4. `python -m unittest discover -s tests -v` 全绿再提交。

这样以后站点改版时，至少能被测试挡一下。

## 适配其他学校 / 其他栏目

本项目解析的是**维赛思（VSB）CMS** 的 `list.jsp` 列表页与 `info/<栏目>/<id>.htm` 详情页。
同款 CMS 的站点通常只需改 `config.json`：

```json
{
  "base_url": "https://other.example.edu.cn",
  "list_path": "/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1234"
}
```

如果结构差异较大，请在 `core.py` 里加解析分支，而不是改死正则字符串。

## 提交规范

- 提交信息用中文或英文都行，一句话说清「改了什么、为什么」。
- 一个 PR 只做一件事，别把重构和修 bug 混在一起。
- 不要提交 `config.json`、`reports/`、`state/`、`logs/`（`.gitignore` 已排除，
  因为这些文件里会有校内公文内容和你的本地路径）。

## 关于抓取礼仪

- 默认 `request_interval` 是 0.6 秒，别调得太小。
- 只抓公开的列表页和详情页，不要尝试登录后的接口。
- 这个项目是给个人/小范围使用的，不要拿去做高频轮询或压力测试。
