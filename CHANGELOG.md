# 更新日志

## 1.0.0 — 2026-10-27

首个可发布版本。

**抓取与归纳**

- 抓取公文列表（维赛思 VSB CMS 的 `list.jsp`），自动翻页，站点共 15000+ 条
- 增量策略：整页比对 + 「本页最旧一条已记录则停止翻页」，日常只发 1 个请求，
  且新公文即使被插到页面中间也不会漏
- 详情页解析：正文、发文单位、发布时间、附件下载链接
- 规则式归纳（不依赖大模型）：要点摘录、关键信息句、类型标签、⏰ 近期截止
  （只认「××日前 / 截止 / 请于××前」这类明确表达，7 天窗口）

**输出**

- `reports/YYYY-MM-DD.md`：Markdown 日报
- `reports/YYYY-MM-DD.html`：同一份的网页版
- `reports/YYYY-MM-DD.json`：结构化数据（供 App / 二次开发）
- `reports/latest.*`：最新一份的固定路径副本

**手机版**

- `python -m nbwdigest serve`：局域网 HTTP 服务，手机浏览器访问，
  支持添加到主屏幕、日期切换、分类筛选、搜索、只看近期截止
- `--export`：把最近 N 天数据内联成单个 HTML，发到手机离线看

**工程**

- 零第三方依赖（仅标准库），`requires-python >= 3.10`
- 26 个离线单元测试（含真实页面 fixtures），不依赖校园网
- GitHub Actions：Ubuntu / Windows × Python 3.10 / 3.12 / 3.13
- 兼容入口 `nbw_digest.py`、`serve.py`，老的计划任务不用改
