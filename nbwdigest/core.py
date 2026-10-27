# -*- coding: utf-8 -*-
"""
深圳技术大学「公文通」每日更新汇总工具
=======================================
访问 https://nbw.sztu.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029
抓取最新公文列表，与本地状态比对找出「本次新增」，抓详情页提炼要点，
生成 Markdown 日报（reports/YYYY-MM-DD.md），并维护去重状态。

用法：
    python nbw_digest.py                 # 正常执行一次（增量）
    python nbw_digest.py --test          # 只解析首页并打印，不写状态
    python nbw_digest.py --rebuild       # 清空状态，重新建立基线
    python nbw_digest.py --pages 3       # 最多翻 3 页列表
    python nbw_digest.py --no-detail     # 不抓详情页（快）
    python nbw_digest.py --dry-run       # 只打印，不落盘

仅依赖 Python 3 标准库。
"""

from __future__ import annotations

import argparse
import gzip
import html as htmllib
import io
import json
import os
import re
import ssl
import sys
import time
import traceback
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 数据目录（config / reports / state / logs）默认是仓库根目录，
# 也可用环境变量 NBW_HOME 指到别处（pip 安装后建议设置）。
DATA_DIR = Path(os.environ.get("NBW_HOME") or ROOT)
CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG = {
    "base_url": "https://nbw.sztu.edu.cn",
    "list_path": "/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029",
    # 空列表 = 全部类别；可填 ["教务", "科研", "学工", "行政", "校园"]
    "categories": [],
    "max_pages": 3,
    "fetch_detail": True,
    "timeout": 25,
    "retries": 3,
    "retry_wait": 2.0,
    "request_interval": 0.6,
    "deadline_warn_days": 7,
    "report_dir": "reports",
    "state_file": "state/seen.json",
    "archive_file": "state/archive.jsonl",
    "log_file": "logs/run.log",
    "state_keep_days": 400,
}

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


# --------------------------------------------------------------------------- #
# 标准输入输出兜底
# --------------------------------------------------------------------------- #
def ensure_stdio() -> None:
    """让 print 在两种环境下都不会崩：

    1. pythonw / 计划任务：没有控制台，sys.stdout 是 None；
    2. Windows 控制台默认 GBK / cp1252：打印中文会 UnicodeEncodeError。
    """
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 配置 / 日志
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            user = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(user, dict):
                cfg.update({k: v for k, v in user.items() if k in DEFAULT_CONFIG})
        except Exception as exc:  # 配置坏了也不能让定时任务崩掉
            print(f"[warn] config.json 解析失败，使用默认配置：{exc}")
    else:
        CONFIG_PATH.write_text(
            json.dumps(DEFAULT_CONFIG, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return cfg


def log(cfg: dict, msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    try:  # pythonw 下没有控制台，print 可能不可用
        print(line, flush=True)
    except Exception:
        pass
    try:
        p = DATA_DIR / cfg["log_file"]
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# 网络
# --------------------------------------------------------------------------- #
def fetch(url: str, cfg: dict, note: str = "") -> str:
    last = None
    for attempt in range(1, cfg["retries"] + 1):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Connection": "close",
            })
            with urllib.request.urlopen(req, timeout=cfg["timeout"],
                                        context=SSL_CTX) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    raw = gzip.decompress(raw)
                charset = "utf-8"
                m = re.search(r"charset=([\w-]+)", resp.headers.get("Content-Type", ""),
                              re.I)
                if m:
                    charset = m.group(1)
                return raw.decode(charset, "replace")
        except Exception as exc:
            last = exc
            if attempt < cfg["retries"]:
                time.sleep(cfg["retry_wait"] * attempt)
    raise RuntimeError(f"抓取失败 {note or url}: {last}")


# --------------------------------------------------------------------------- #
# HTML 工具
# --------------------------------------------------------------------------- #
TAG_RE = re.compile(r"<[^>]+>")
SCRIPT_RE = re.compile(r"(?is)<(script|style)[^>]*>.*?</\1>")
COMMENT_RE = re.compile(r"(?s)<!--.*?-->")


def strip_tags(fragment: str) -> str:
    s = SCRIPT_RE.sub(" ", fragment)
    s = COMMENT_RE.sub(" ", s)
    s = re.sub(r"(?i)<(br|/p|/div|/li|/tr|/h\d)\s*/?>", "\n", s)
    s = TAG_RE.sub("", s)
    return htmllib.unescape(s)


def normalize_cn(text: str) -> str:
    """清理排版噪声：&nbsp;、CJK 之间的空格、段内换行、多余空行。"""
    text = text.replace("\u3000", " ").replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    # 中文与数字/英文之间的空格（原文用 span 拆分数字，会留下 "2026 年 10 月"）
    text = re.sub(r"(?<=[\u4e00-\u9fff，。；：、（）“”《》])[ ]+(?=[\u4e00-\u9fff0-9A-Za-z])", "", text)
    text = re.sub(r"(?<=[0-9A-Za-z%）])[ ]+(?=[\u4e00-\u9fff，。；：、（）“”《》])", "", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    lines = [ln.strip() for ln in text.split("\n")]
    out, blank = [], 0
    for ln in lines:
        if ln:
            out.append(ln)
            blank = 0
        else:
            blank += 1
            if blank <= 1 and out:
                out.append("")
    return "\n".join(out).strip()


# --------------------------------------------------------------------------- #
# 列表页解析
# --------------------------------------------------------------------------- #
LI_RE = re.compile(r'(?is)<li[^>]*id="line_u6_\d+"[^>]*>(.*?)</li>')
RE_NUM = re.compile(r'(?is)class="pull-left width01[^"]*".*?<span[^>]*>\s*(\d+)\s*</span>')
RE_CAT = re.compile(r'(?is)class="pull-left width02[^"]*".*?<a[^>]*>(.*?)</a>')
RE_DEPT = re.compile(r'(?is)class="pull-left width03[^"]*".*?<a[^>]*>(.*?)</a>')
RE_TITLE = re.compile(r'(?is)class="pull-left width04[^"]*".*?<a\s+href="([^"]+)"([^>]*)>(.*?)</a>')
RE_ATTR_TITLE = re.compile(r'title="([^"]*)"')
RE_ATTACH = re.compile(r'(?is)class="pull-right width05[^"]*".*?<img')
RE_DATE = re.compile(r'(?is)class="pull-right width06[^"]*"[^>]*>\s*(\d{4}-\d{1,2}-\d{1,2})\s*<')
RE_TOTAL = re.compile(r"共\s*(\d+)\s*条")


def parse_list(page_html: str, page_url: str, cfg: dict) -> tuple[list[dict], int | None]:
    base = cfg["base_url"]
    items, seen_ids = [], set()
    for m in LI_RE.finditer(page_html):
        block = m.group(1)
        t = RE_TITLE.search(block)
        if not t:
            continue
        href = t.group(1)
        attrs = t.group(2) or ""
        at = RE_ATTR_TITLE.search(attrs)
        title = htmllib.unescape(at.group(1)).strip() if at and at.group(1).strip() \
            else normalize_cn(strip_tags(t.group(3))).replace("\n", " ").strip()
        title = re.sub(r"^\.\s*", "", title).strip()
        if not title:
            continue
        url = href if href.startswith("http") else urllib.request.urljoin(base, href)
        ident = re.sub(r"^.*/info/", "", url).replace(".htm", "")
        if not ident:
            ident = url
        if ident in seen_ids:
            continue
        seen_ids.add(ident)

        def grab(rx, default=""):
            mm = rx.search(block)
            return normalize_cn(strip_tags(mm.group(1))).replace("\n", " ").strip() if mm else default

        d = RE_DATE.search(block)
        items.append({
            "id": ident,
            "num": (RE_NUM.search(block).group(1) if RE_NUM.search(block) else ""),
            "category": grab(RE_CAT),
            "dept": grab(RE_DEPT),
            "title": title,
            "url": url,
            "list_date": d.group(1) if d else "",
            "has_attach": bool(RE_ATTACH.search(block)),
        })
    tm = RE_TOTAL.search(page_html)
    return items, (int(tm.group(1)) if tm else None)


def build_page_url(cfg: dict, page: int) -> str:
    url = cfg["base_url"].rstrip("/") + cfg["list_path"]
    if page <= 1:
        return url
    return f"{url}&PAGENUM={page}"


# --------------------------------------------------------------------------- #
# 详情页解析
# --------------------------------------------------------------------------- #
RE_D_TITLE = re.compile(r'(?is)<h1[^>]*class="article-title[^"]*"[^>]*>(.*?)</h1>')
RE_D_AUTHOR = re.compile(r"作者[：:]\s*([^<\n]{1,40})")
RE_D_TIME = re.compile(
    r"发布时间[：:]\s*([0-9]{4}年[0-9]{1,2}月[0-9]{1,2}日\s*[0-9]{1,2}[:：][0-9]{2})")
RE_D_ATTACH = re.compile(r'(?is)附件【\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>')


def parse_detail(page_html: str, url: str, cfg: dict) -> dict:
    base = cfg["base_url"]
    out = {"author": "", "publish_time": "", "body": "", "attachments": []}

    m = RE_D_TITLE.search(page_html)
    if m:
        out["detail_title"] = normalize_cn(strip_tags(m.group(1))).replace("\n", " ").strip()

    m = RE_D_AUTHOR.search(page_html)
    if m:
        out["author"] = m.group(1).strip()
    m = RE_D_TIME.search(page_html)
    if m:
        out["publish_time"] = m.group(1)

    # 正文区：#vsb_content 的标签之后开始；附件区（<UL class="fujian">）在 .article-link 之前
    anchor = page_html.find('id="vsb_content"')
    if anchor == -1:
        anchor = page_html.find('class="v_news_content"')
    if anchor != -1:
        gt = page_html.find(">", anchor)
        body_start = (gt + 1) if gt != -1 else anchor
        # 注意：附件区里含内联 <script>（下载计数），不能用 "<script" 当边界，
        # 否则只能抓到第一个附件。
        body_end = _first_pos(page_html, body_start, (
            '<div id="div_vote_id"', 'class="article-link"', '<UL class="fujian"',
            '<ul class="fujian"', "</form>", 'class="footer-list"'))
        att_end = _first_pos(page_html, body_start, (
            'class="article-link"', "</form>", 'class="footer-list"'))

        region = page_html[body_start:att_end]
        out["attachments"] = [
            {"name": re.sub(r"\s+", " ", htmllib.unescape(strip_tags(n))).strip(),
             "url": (h if h.startswith("http") else urllib.request.urljoin(base, h))}
            for h, n in RE_D_ATTACH.findall(region)
        ]
        body_html = page_html[body_start:body_end]
        body_html = re.sub(r"(?is)<span[^>]*id=\"nattach\d+\"[^>]*>.*?</span>", "", body_html)
        out["body"] = normalize_cn(strip_tags(body_html))
    return out


def _first_pos(text: str, start: int, markers: tuple) -> int:
    positions = [text.find(m, start) for m in markers]
    positions = [p for p in positions if p != -1]
    return min(positions) if positions else len(text)


# --------------------------------------------------------------------------- #
# 归纳
# --------------------------------------------------------------------------- #
TAGS = [
    ("讲座", ("讲座", "报告会", "报告")), ("会议", ("会议", "研讨会", "座谈会")),
    ("培训", ("培训", "研修", "课程")), ("申报", ("申报", "征集", "课题", "项目指南")),
    ("公示", ("公示", "拟", "名单")), ("报名", ("报名", "报名表")),
    ("招聘", ("招聘", "宣讲", "人才需求", "求职")), ("评选", ("评选", "比赛", "竞赛", "大赛")),
    ("考试", ("考试", "四六级", "等级考试")), ("后勤", ("停电", "停水", "维修", "施工")),
    ("放假", ("放假", "假期", "调休")), ("招标", ("招标", "采购", "询价")),
    ("考核", ("考核", "中期检查", "结题", "验收")), ("安全", ("安全", "消防", "演练")),
]
KEY_HINTS = ("时间", "日期", "地点", "对象", "范围", "截止", "请于", "需于", "报名",
             "申报", "提交", "报送", "联系", "电话", "邮箱", "费用", "要求", "名额",
             "安排", "条件", "流程", "网址", "链接", "方式", "地点")
BOILER = ("现将有关事项通知如下", "现将有关事宜通知如下", "现通知如下", "特此通知",
          "请遵照执行", "请认真贯彻执行", "现将有关事项通知", "具体通知如下")

FULL_DATE_RE = re.compile(r"(20\d{2})\s*[年\-/\.]\s*(\d{1,2})\s*[月\-/\.]\s*(\d{1,2})\s*日?")
MD_DATE_RE = re.compile(r"(?<![年\d])(\d{1,2})\s*月\s*(\d{1,2})\s*日")
RANGE_SEP = r"\s*(?:-|—|–|~|～|至|到)\s*"
RANGE_RE = re.compile(FULL_DATE_RE.pattern + RANGE_SEP + FULL_DATE_RE.pattern)
DEADLINE_HINTS = ("截止", "截至", "前完成", "前提交", "前将", "前报", "之前", "务于",
                  "请于", "须于", "应于", "需于", "不迟于", "前发送", "前反馈", "前报")
RANGE_HINTS = ("公示", "报名时间", "活动时间", "征稿", "投稿", "征集时间", "申报时间")
SENT_SPLIT = re.compile(r"[。；;！!？?\n]+")


def guesses_tags(title: str) -> list[str]:
    return [tag for tag, kws in TAGS if any(k in title for k in kws)]


def pick_sentences(body: str, limit: int = 6) -> list[str]:
    out = []
    for seg in SENT_SPLIT.split(body):
        seg = seg.strip(" 　\t:：、")
        if 8 <= len(seg) <= 120:
            out.append(seg)
        if len(out) >= limit:
            break
    return out


def to_date(y, mo, dd):
    try:
        return date(int(y), int(mo), int(dd))
    except ValueError:
        return None


def find_deadline(body: str, today: date, warn_days: int) -> str:
    """只把「带截止语义的日期」且落在近期窗口内的，才当成待办截止。"""
    if not body:
        return ""
    horizon = today + timedelta(days=warn_days)
    floor = today - timedelta(days=1)
    cands: list[date] = []
    consumed: list[tuple[int, int]] = []

    # 区间：公示期 2026年10月19日-2026年10月23日 → 取结束日
    for m in RANGE_RE.finditer(body):
        ctx = body[max(0, m.start() - 30): m.end() + 15]
        if not any(h in ctx for h in RANGE_HINTS):
            continue
        y2, m2, d2 = m.groups()[3], m.groups()[4], m.groups()[5]
        d = to_date(y2, m2, d2)
        if d and floor <= d <= horizon:
            cands.append(d)
        consumed.append((m.start(), m.end()))

    def deadline_after(m) -> bool:
        """日期后面紧跟「前 / 之前 / 以前 / 截止」等，是明确的截止表达。"""
        tail = body[m.end(): m.end() + 10].lstrip()
        return bool(re.match(r"(前|之前|以前|截止|止|为?止)", tail))

    for m in FULL_DATE_RE.finditer(body):
        if any(a <= m.start() < b for a, b in consumed):
            continue
        ctx = body[max(0, m.start() - 45): m.end() + 20]
        if not (deadline_after(m) or any(h in ctx for h in DEADLINE_HINTS)):
            continue
        d = to_date(*m.groups())
        if d and floor <= d <= horizon:
            cands.append(d)

    for m in MD_DATE_RE.finditer(body):
        if any(a <= m.start() < b for a, b in consumed):
            continue
        if FULL_DATE_RE.search(body[max(0, m.start() - 6): m.start()]):
            continue
        ctx = body[max(0, m.start() - 45): m.end() + 20]
        if not (deadline_after(m) or any(h in ctx for h in DEADLINE_HINTS)):
            continue
        d = to_date(today.year, m.group(1), m.group(2))
        if d and d < today - timedelta(days=60):  # 跨年（如 12 月发文写 1 月）
            d = to_date(today.year + 1, m.group(1), m.group(2))
        if d and floor <= d <= horizon:
            cands.append(d)

    return min(cands).isoformat() if cands else ""


def make_summary(item: dict, detail: dict, cfg: dict) -> dict:
    body = (detail.get("body") or "").strip()
    att_names = {a["name"].strip() for a in detail.get("attachments", [])}
    # 去掉正文里重复的附件名、套话
    def keep(s: str) -> bool:
        if any(b in s for b in BOILER):
            return False
        if any(n and n in s and len(s) <= len(n) + 6 for n in att_names):
            return False
        return True

    sents = [s for s in pick_sentences(body) if keep(s)]

    # 摘要：取最前面的信息量句子，凑够 ~130 字
    abstract, used = [], 0
    for s in sents:
        if used + len(s) > 140 and abstract:
            break
        abstract.append(s)
        used += len(s)

    key_points = []
    for s in pick_sentences(body, limit=40):
        if not any(h in s for h in KEY_HINTS):
            continue
        if not re.search(r"\d", s) and len(s) < 14:   # 纯标题行，如「一、停电作业时间」
            continue
        if not keep(s):
            continue
        if s not in key_points:
            key_points.append(s)
        if len(key_points) >= 4:
            break

    return {
        "abstract": "；".join(abstract)[:240],
        "key_points": key_points,
        "tags": guesses_tags(item["title"]),
        "deadline": find_deadline(body, date.today(), cfg["deadline_warn_days"]),
        "chars": len(body),
    }


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def load_state(cfg: dict) -> dict:
    p = DATA_DIR / cfg["state_file"]
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_state(cfg: dict, state: dict) -> None:
    p = DATA_DIR / cfg["state_file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    keep = date.today() - timedelta(days=cfg["state_keep_days"])
    pruned = {}
    for k, v in state.items():
        try:
            if date.fromisoformat(str(v.get("first_seen", ""))[:10]) >= keep:
                pruned[k] = v
        except Exception:
            pruned[k] = v
    p.write_text(json.dumps(pruned, ensure_ascii=False, indent=1), encoding="utf-8")


def append_archive(cfg: dict, records: list[dict]) -> None:
    if not records:
        return
    p = DATA_DIR / cfg["archive_file"]
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
CAT_ORDER = ["教务", "科研", "行政", "学工", "校园"]


HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ margin:0; padding:32px 18px 64px; background:#f6f7f9;
         font:16px/1.75 "Microsoft YaHei","PingFang SC",system-ui,sans-serif; color:#1f2328; }}
  main {{ max-width:820px; margin:0 auto; background:#fff; border-radius:12px;
          padding:34px 40px 46px; box-shadow:0 2px 12px rgba(0,0,0,.06); }}
  h1 {{ font-size:26px; margin:0 0 18px; padding-bottom:14px; border-bottom:2px solid #e6e8eb; }}
  h2 {{ font-size:20px; margin:34px 0 12px; padding-left:10px; border-left:4px solid #2f6fed; }}
  h3 {{ font-size:16px; margin:22px 0 8px; color:#111; }}
  ul {{ margin:8px 0 8px 4px; padding-left:20px; }}
  li {{ margin:3px 0; }}
  li.meta {{ color:#57606a; font-size:14px; }}
  a {{ color:#2f6fed; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
  hr {{ border:0; border-top:1px solid #e6e8eb; margin:32px 0 16px; }}
  blockquote {{ margin:12px 0; padding:8px 14px; background:#fff8e6; border-left:4px solid #f0a020; }}
  .foot {{ color:#8c959f; font-size:13px; }}
  @media (max-width:600px) {{ main {{ padding:22px 18px 30px; }} body {{ padding:14px 10px 40px; }} }}
</style></head><body><main>
"""

HTML_TAIL = "\n</main></body></html>\n"


def md_to_html(md: str, title: str) -> str:
    """把本程序生成的 Markdown 渲染成可直接双击打开的 HTML（无外部依赖）。"""
    def inline(s: str) -> str:
        s = htmllib.escape(s, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        # 先处理 Markdown 链接，再把剩下的裸 URL 变成链接（分片处理，避免二次替换 href）
        parts, pos = [], 0
        for m in re.finditer(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", s):
            parts.append(("txt", s[pos:m.start()]))
            parts.append(("html", f'<a href="{m.group(2)}" target="_blank" '
                                  f'rel="noreferrer">{m.group(1)}</a>'))
            pos = m.end()
        parts.append(("txt", s[pos:]))
        buf = []
        for kind, seg in parts:
            if kind == "html":
                buf.append(seg)
            else:
                buf.append(re.sub(r"(https?://[^\s<]+)",
                                  r'<a href="\1" target="_blank" rel="noreferrer">\1</a>', seg))
        return "".join(buf)

    out, in_ul = [HTML_HEAD.format(title=htmllib.escape(title, quote=False))], False
    for raw in md.split("\n"):
        line = raw.rstrip()
        if in_ul and not line.startswith("- "):
            out.append("</ul>")
            in_ul = False
        if not line.strip():
            continue
        if line.startswith("### "):
            out.append(f"<h3>{inline(line[4:])}</h3>")
        elif line.startswith("## "):
            out.append(f"<h2>{inline(line[3:])}</h2>")
        elif line.startswith("# "):
            out.append(f"<h1>{inline(line[2:])}</h1>")
        elif line.startswith("- "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            body = inline(line[2:])
            cls = ' class="meta"' if body.startswith(("发文单位", "发布：", "日期：")) else ""
            out.append(f"<li{cls}>{body}</li>")
        elif line.startswith("> "):
            out.append(f"<blockquote>{inline(line[2:])}</blockquote>")
        elif line.startswith("---"):
            out.append("<hr>")
        elif line.startswith("*") and line.endswith("*") and len(line) > 2:
            out.append(f'<p class="foot">{inline(line.strip("*"))}</p>')
        else:
            out.append(f"<p>{inline(line)}</p>")
    if in_ul:
        out.append("</ul>")
    out.append(HTML_TAIL)
    return "\n".join(out)


def render_report(run_dt: datetime, items: list[dict], stats: dict,
                  baseline: bool, total_known: int | None) -> str:
    L = []
    L.append("# 深圳技术大学「公文通」每日更新汇总")
    L.append("")
    L.append(f"- 生成时间：{run_dt:%Y-%m-%d %H:%M:%S}")
    L.append(f"- 数据来源：[公文通](https://nbw.sztu.edu.cn/list.jsp?urltype=tree.TreeTempUrl&wbtreeid=1029)")
    if total_known is not None:
        L.append(f"- 站内共 {total_known} 条公文")
    if baseline:
        L.append("- 说明：**首次运行，已建立基线**。以下为当前首页最新的一批公文，从明天起只列新增。")
    L.append(f"- 本次新增：**{len(items)} 条**" + ("（" + " · ".join(stats["by_cat"]) + "）" if items else ""))
    L.append("")

    if not items:
        L.append("> 今日无新增公文。")
        L.append("")
        return "\n".join(L)

    urgent = [it for it in items if it.get("deadline")]
    if urgent:
        L.append("## ⏰ 近期截止 / 需关注")
        L.append("")
        for it in sorted(urgent, key=lambda x: x["deadline"]):
            L.append(f"- **{it['deadline']}** · [{it['title']}]({it['url']}) — {it['dept']}")
        L.append("")

    order = [c for c in CAT_ORDER if c in stats["cats"]] + \
            [c for c in stats["cats"] if c not in CAT_ORDER]
    for cat in order:
        group = [it for it in items if it["category"] == cat]
        if not group:
            continue
        L.append(f"## {cat or '其他'}（{len(group)} 条）")
        L.append("")
        for it in group:
            L.append(f"### {it['title']}")
            L.append("")
            meta = [f"发文单位：{it['dept'] or '—'}"]
            if it.get("publish_time"):
                meta.append(f"发布：{it['publish_time']}")
            elif it.get("list_date"):
                meta.append(f"日期：{it['list_date']}")
            if it.get("tags"):
                meta.append("类型：" + "/".join(it["tags"]))
            if it.get("has_attach") or it.get("attachments"):
                meta.append("📎 有附件")
            L.append("- " + "　".join(meta))
            if it.get("abstract"):
                L.append(f"- 要点：{it['abstract']}")
            kp = [p for p in it.get("key_points", []) if p and p not in it.get("abstract", "")]
            if kp:
                L.append("- 关键信息：" + "；".join(kp[:3]))
            for att in it.get("attachments", [])[:4]:
                L.append(f"- 附件：[{att['name']}]({att['url']})")
            L.append(f"- 原文：{it['url']}")
            L.append("")
    L.append("---")
    L.append("")
    L.append("*本文件由 `nbw_digest.py` 自动生成。*")
    return "\n".join(L)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

__all__ = [
    "ensure_stdio",
    "load_config",
    "log",
    "fetch",
    "strip_tags",
    "normalize_cn",
    "parse_list",
    "build_page_url",
    "parse_detail",
    "_first_pos",
    "guesses_tags",
    "pick_sentences",
    "to_date",
    "find_deadline",
    "make_summary",
    "load_state",
    "save_state",
    "append_archive",
    "md_to_html",
    "render_report",
    "CONFIG_PATH",
    "DEFAULT_CONFIG",
    "UA",
    "SSL_CTX",
    "TAG_RE",
    "SCRIPT_RE",
    "COMMENT_RE",
    "LI_RE",
    "RE_NUM",
    "RE_CAT",
    "RE_DEPT",
    "RE_TITLE",
    "RE_ATTR_TITLE",
    "RE_ATTACH",
    "RE_DATE",
    "RE_TOTAL",
    "RE_D_TITLE",
    "RE_D_AUTHOR",
    "RE_D_TIME",
    "RE_D_ATTACH",
    "TAGS",
    "KEY_HINTS",
    "BOILER",
    "FULL_DATE_RE",
    "MD_DATE_RE",
    "RANGE_SEP",
    "RANGE_RE",
    "DEADLINE_HINTS",
    "RANGE_HINTS",
    "SENT_SPLIT",
    "CAT_ORDER",
    "HTML_HEAD",
    "HTML_TAIL",
]
