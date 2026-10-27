# 公文通 · 每日汇总（nbwdigest）

[![CI](https://github.com/your-name/nbw-digest/actions/workflows/ci.yml/badge.svg)](https://github.com/your-name/nbw-digest/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![Zero deps](https://img.shields.io/badge/dependencies-0-brightgreen)
![License](https://img.shields.io/badge/license-MIT-lightgrey)

把深圳技术大学「**公文通**」([nbw.sztu.edu.cn](https://nbw.sztu.edu.cn)) 变成一份
**每天自动生成、能按类型筛选、能标出截止日期**的日报 —— 命令行、Markdown、网页版、手机版全都有。

> 本质上它是一个 **维赛思（VSB）CMS 公文列表的通用抓取器 + 增量比对 + 规则式归纳**，
> 换个 `base_url` 就能用到别的同类站点上（见[适配其他站点](#适配其他站点)）。

---

## 它解决什么问题

学校公文通是一个 15000+ 条的滚动列表，一天更新十几条，混着「科研项目申报」「停电通知」
「奖学金公示」。想不漏掉跟自己有关的那几条，只能天天翻。

这个工具做三件事：

1. **只报增量** —— 记住抓过的公文，下次只输出新增的；同一天重复跑也不会重复报。
2. **帮你归纳** —— 抓详情页，摘出要点、关键信息（时间/地点/截止/联系人）、类型标签，
   并把 7 天内要截止的单独列在最上面。
3. **随处可看** —— 生成 Markdown / HTML / JSON，还能起一个局域网网页给手机看。

## 特性

- **零依赖**：只用 Python 标准库，不需要 requests / bs4 / lxml
- **增量不重不漏**：整页比对 + 水位线翻页，日常只发 1 个 HTTP 请求
- **真正的归纳**：正文提炼、套话过滤、附件识别、截止日期抽取（规则式，不联网调大模型）
- **三种产物**：`.md`（人看）、`.html`（双击看）、`.json`（程序用）
- **手机版网页**：自适应、深色模式、日期切换、分类筛选、搜索、只看近期截止
- **离线单文件**：把最近 N 天打包成一个 HTML，发到手机上断网也能看
- **可测试**：25 个离线单测 + 真实页面 fixtures，不依赖校园网

## 快速开始

```bash
git clone https://github.com/your-name/nbw-digest.git
cd nbw-digest

python -m nbwdigest          # 抓取一次（首次会建立基线，只取首页 20 条）
python -m nbwdigest serve    # 起手机版网页，按提示在手机上打开
```

产物都在 `reports/` 下：`2026-10-27.md` / `.html` / `.json`，以及 `latest.*` 副本。

> 没有装包也能跑，`python -m nbwdigest` 直接从仓库运行。
> 想装成命令：`pip install -e .`，之后可用 `nbwdigest` / `nbwdigest-serve`。

## 目录结构

```
nbw-digest/
├─ nbwdigest/
│   ├─ core.py          抓取 / 解析 / 归纳 / 渲染（纯函数为主）
│   ├─ cli.py           增量比对、落盘、命令行入口
│   ├─ webapp.py        手机版 HTTP 服务 + 离线单文件导出
│   └─ web/             前端：原生 JS + CSS，无构建步骤
├─ tests/
│   ├─ fixtures/        真实页面样本（离线测试用）
│   └─ test_core.py     25 个 unittest 用例
├─ scripts/
│   └─ install_cron.sh  Linux/macOS 定时任务
├─ config.example.json  配置样例
├─ nbw_digest.py        兼容入口（老计划任务用）
├─ serve.py             兼容入口
├─ install_task.ps1     Windows 计划任务注册
├─ 启动手机版.bat / 生成离线版.bat / run.bat / open_latest.bat
└─ pyproject.toml
```

运行产物（**不进版本库**）：`config.json`、`reports/`、`state/`、`logs/`。

## 命令行

```bash
python -m nbwdigest                 # 增量抓取 + 出报告
python -m nbwdigest --test          # 只解析列表打印成表格，不写文件
python -m nbwdigest --dry-run       # 抓取并归纳，报告只打印不落盘
python -m nbwdigest --no-detail     # 不抓详情页（快很多，没有要点）
python -m nbwdigest --pages 5       # 最多翻 5 页（默认 3）
python -m nbwdigest --rebuild       # 清空状态重建基线
python -m nbwdigest --categories 教务 科研    # 只关注部分类别

python -m nbwdigest serve           # 手机版服务，默认 8080
python -m nbwdigest serve --port 9000 --open
python -m nbwdigest serve --export  # 生成 reports/手机版-离线.html
python -m nbwdigest serve --export out.html --days 30
```

## 配置

`config.json` 首次运行自动生成，改完立即生效（不用改代码）。字段说明见
[`config.example.json`](config.example.json)：

| 键 | 默认 | 说明 |
|---|---|---|
| `base_url` / `list_path` | SZTU 公文通 | 抓哪个站点、哪个栏目 |
| `categories` | `[]` | 空 = 全部；填 `["教务","科研"]` 只报这些 |
| `max_pages` | `3` | 最多翻几页（每页 20 条） |
| `fetch_detail` | `true` | 是否抓详情页做摘要 |
| `timeout` / `retries` / `retry_wait` | `25` / `3` / `2.0` | 网络重试策略 |
| `request_interval` | `0.6` | 请求间隔秒数（**请勿调太小**） |
| `deadline_warn_days` | `7` | 多少天内的截止会被标 ⏰ |
| `state_keep_days` | `400` | 去重状态保留天数 |

数据目录默认是仓库根目录；想放到别处用环境变量 `NBW_HOME=/path/to/data`。

## 手机版

**局域网网页（数据实时）**

```bash
python -m nbwdigest serve        # 会打印 http://10.x.x.x:8080
```

手机连同一个 WiFi 后打开该地址 → Chrome 菜单「添加到主屏幕」→ 桌面多一个图标。
电脑需保持运行；想开机自启就把启动脚本的快捷方式放进启动文件夹。

**离线单文件（不依赖电脑）**

```bash
python -m nbwdigest serve --export
# 产出 reports/手机版-离线.html（含最近 14 天，全部数据内联）
```

把文件发到手机，用浏览器打开即可，断网也能翻历史。

> 限制：局域网版是 HTTP 明文，浏览器不会把它当完整 PWA ——
> 「添加到主屏幕」是快捷方式，Service Worker 离线缓存在非 HTTPS 下会被禁用。
> 真要离线请用离线单文件。

## 定时任务

**Windows**（注册每天 18:00 的计划任务，含错过补跑、失败重试）

```powershell
powershell -ExecutionPolicy Bypass -File .\install_task.ps1
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Time 08:30
powershell -ExecutionPolicy Bypass -File .\install_task.ps1 -Uninstall
```

**Linux / macOS**

```bash
bash scripts/install_cron.sh 18:00
```

**systemd（服务器常驻手机版服务）**

```ini
# /etc/systemd/system/nbwdigest.service
[Unit]
Description=nbwdigest mobile web
After=network.target

[Service]
WorkingDirectory=/opt/nbw-digest
ExecStart=/usr/bin/python3 -m nbwdigest serve --port 8080
Restart=always

[Install]
WantedBy=multi-user.target
```

## 工作原理

**增量（不重不漏）**

列表按发布时间倒序。程序抓第 1 页 → 逐条比对 `state/seen.json`：

- 不认识的 → 算新增；
- **整页都扫完**（所以新公文被插到页面中间也不会漏）；
- 只有当**本页最旧的一条也已经记录过**，才停止翻页 —— 一天新增超过 20 条时才用得上第 2 页。

**归纳（规则式）**

| 输出 | 规则 |
|---|---|
| 要点 | 正文前几句有效信息，剔除「现将有关事项通知如下」等套话和重复的附件名 |
| 关键信息 | 含「时间/地点/截止/报名/联系/电话」等关键词的句子 |
| 类型 | 标题关键词打标签：讲座 / 会议 / 培训 / 申报 / 公示 / 报名 / 招聘 / 考试 / 后勤 / 安全 … |
| ⏰ 截止 | 只认「××日前 / 截止 / 请于××前」这类明确表达，且落在窗口内；公示期取结束日 |

之所以不用大模型：稳定、可复现、零成本、离线可用。想要生成式摘要，
`core.make_summary()` 里已经拿到干净正文 `body`，接任意 LLM API 只需几行。

## 适配其他站点

本项目解析 VSB CMS 的两种页面：列表页 `list.jsp?...&wbtreeid=N` 和详情页 `info/<栏目>/<id>.htm`。
同类站点通常只改配置：

```json
{
  "base_url": "https://other.example.edu.cn",
  "list_path": "/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1234"
}
```

结构差异较大时，请按 [CONTRIBUTING.md](CONTRIBUTING.md) 的方式加解析分支 + fixtures 测试。

## 开发与测试

```bash
python -m unittest discover -s tests -v      # 25 个用例，全部离线
```

测试用 `tests/fixtures/` 里的真实页面（已脱敏，无 cookie），所以**不需要校园网**也能跑，
CI 在 Ubuntu / Windows × Python 3.10 / 3.12 / 3.13 上跑同一套。

## 常见问题

**抓不到数据？**
站点解析到内网地址 `10.1.12.148`，**必须在校内网或学校 VPN 下**。报 SSL 错误时程序已跳过
证书校验，若仍失败多半是被网关拦了。

**首次运行刷出 20 条「新增」？**
那是基线，属正常。第二天起只报增量。

**能不能只看某一类？**
`config.json` 的 `categories`，或 `--categories 教务 科研`。

**怎么清空重来？**
`python -m nbwdigest --rebuild`。

## 免责声明

本项目仅抓取站点上**公开可见**的列表页与详情页，用于个人减少信息筛选成本。
请遵守学校的网络使用规定与站点 robots 约定：**不要调低请求间隔、不要高频轮询、不要用于商业用途**。
站点改版会导致解析失效，届时按 issue 模板反馈即可。

## License

[MIT](LICENSE) © 2026 nbwdigest contributors
