# -*- coding: utf-8 -*-
"""命令行入口：python -m nbwdigest ..."""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from .core import (
    CAT_ORDER,
    DATA_DIR,
    append_archive,
    build_page_url,
    ensure_stdio,
    fetch,
    guesses_tags,
    load_config,
    load_state,
    log,
    make_summary,
    md_to_html,
    parse_detail,
    parse_list,
    render_report,
    save_state,
)


def collect(cfg: dict, state: dict, max_pages: int, logf) -> tuple[list[dict], int | None, bool]:
    """增量扫描列表页。

    列表按发布顺序倒序排列（新的在前）。策略：**整页逐条比对**，把不认识的条目都收进来；
    只有当这一页最旧的一条也还是陌生的，才继续翻下一页（说明这一天新增多于一页）。
    这样即便新公文被插到页面中间也不会漏，日常只花 1 次请求。
    返回 (新增条目, 站内总数, 是否因翻页上限截断)。
    """
    fresh: list[dict] = []
    total = None
    seen_page_ids: set[str] = set()
    truncated = False

    for page in range(1, max_pages + 1):
        url = build_page_url(cfg, page)
        page_html = fetch(url, cfg, note=f"列表第{page}页")
        items, tot = parse_list(page_html, url, cfg)
        if tot and total is None:
            total = tot
        if not items:
            break

        page_fresh = 0
        for it in items:
            if it["id"] in seen_page_ids:
                continue
            seen_page_ids.add(it["id"])
            if it["id"] not in state:
                fresh.append(it)
                page_fresh += 1
        logf(f"  第{page}页：{len(items)} 条，其中新增 {page_fresh} 条")

        # 本页最旧的一条已记录过 → 后面都是更早的，不必再翻
        if items[-1]["id"] in state:
            break
        if page_fresh == 0:
            break
        if page == max_pages:
            truncated = True
            logf(f"  [warn] 已达翻页上限 {max_pages} 页，可能还有更早的新条目未覆盖")
        time.sleep(cfg["request_interval"])

    return fresh, total, truncated


def item_record(it: dict) -> dict:
    """给手机端/接口用的结构化条目。"""
    return {
        "id": it["id"], "num": it.get("num", ""), "category": it.get("category", ""),
        "dept": it.get("dept", ""), "title": it.get("title", ""), "url": it.get("url", ""),
        "list_date": it.get("list_date", ""), "publish_time": it.get("publish_time", ""),
        "author": it.get("author", ""), "tags": it.get("tags", []),
        "deadline": it.get("deadline", ""), "abstract": it.get("abstract", ""),
        "key_points": it.get("key_points", []),
        "attachments": it.get("attachments", []),
        "has_attach": bool(it.get("has_attach")),
    }


def write_day_json(rdir: Path, run_dt: datetime, items: list[dict], cats: dict,
                   total: int | None, baseline: bool) -> None:
    """输出结构化 JSON（供手机端/后续 App 使用），同一天多次运行会合并。"""
    day = f"{run_dt:%Y-%m-%d}"
    path = rdir / f"{day}.json"
    data = None
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = None

    records = [item_record(it) for it in items]
    if data and isinstance(data.get("items"), list):
        # 同一天重复运行：按 id 覆盖（用最新一次解析结果），新 id 追加
        index = {x.get("id"): i for i, x in enumerate(data["items"])}
        for r in records:
            if r["id"] in index:
                data["items"][index[r["id"]]] = r
            else:
                data["items"].append(r)
                index[r["id"]] = len(data["items"]) - 1
        data["baseline"] = bool(data.get("baseline")) and baseline
    else:
        data = {"date": day, "baseline": baseline, "total_site": total, "items": records}
    data["generated_at"] = f"{run_dt:%Y-%m-%d %H:%M:%S}"
    data["count"] = len(data["items"])
    counts: dict[str, int] = {}
    for x in data["items"]:
        key = x.get("category") or "其他"
        counts[key] = counts.get(key, 0) + 1
    data["by_category"] = counts

    text = json.dumps(data, ensure_ascii=False, indent=1)
    path.write_text(text, encoding="utf-8")
    (rdir / "latest.json").write_text(text, encoding="utf-8")


def run(args) -> int:
    cfg = load_config()
    if args.pages:
        cfg["max_pages"] = args.pages
    if args.no_detail:
        cfg["fetch_detail"] = False
    if args.categories:
        cfg["categories"] = args.categories
    logf = lambda m: log(cfg, m)

    logf(f"===== 开始：{datetime.now():%Y-%m-%d %H:%M:%S} =====")
    state = {} if args.rebuild or args.test else load_state(cfg)
    baseline = not state
    if baseline and not args.pages:
        cfg["max_pages"] = 1  # 首次运行只取首页做基线，报告不至于太长

    scanned, total, truncated = collect(cfg, state, cfg["max_pages"], logf)
    fresh = scanned
    if cfg["categories"]:
        keep = set(cfg["categories"])
        fresh = [it for it in scanned if it["category"] in keep]
        logf(f"  按类别过滤 {sorted(keep)} 后剩 {len(fresh)} 条")

    logf(f"  新增合计 {len(fresh)} 条（站内共 {total if total else '?'} 条）")

    if args.test:
        print(f"\n{'序号':<4}{'类别':<6}{'发文单位':<22}{'日期':<12}标题")
        for it in scanned:
            print(f"{it['num']:<4}{it['category']:<6}{it['dept'][:20]:<22}{it['list_date']:<12}{it['title'][:48]}")
        print(f"\n解析到 {len(scanned)} 条，站内总数 {total}")
        return 0

    # 详情页 + 归纳
    for it in fresh:
        it.update({"abstract": "", "key_points": [], "tags": guesses_tags(it["title"]),
                   "deadline": "", "attachments": [], "publish_time": "", "author": ""})
        if not cfg["fetch_detail"]:
            continue
        try:
            dhtml = fetch(it["url"], cfg, note=f"详情 {it['title'][:20]}")
            detail = parse_detail(dhtml, it["url"], cfg)
            it["author"] = detail.get("author", "")
            it["publish_time"] = detail.get("publish_time", "")
            it["attachments"] = detail.get("attachments", [])
            it.update(make_summary(it, detail, cfg))
        except Exception as exc:
            logf(f"  [warn] 详情抓取失败（{it['title'][:24]}）：{exc}")
        time.sleep(cfg["request_interval"])

    if args.dry_run:
        print(render_report(datetime.now(), fresh, summary_stats(fresh), baseline, total))
        return 0

    # 落盘：报告
    run_dt = datetime.now()
    stats = summary_stats(fresh)
    report = render_report(run_dt, fresh, stats, baseline, total)
    rdir = DATA_DIR / cfg["report_dir"]
    rdir.mkdir(parents=True, exist_ok=True)
    rp = rdir / f"{run_dt:%Y-%m-%d}.md"

    if rp.exists() and not fresh:
        logf(f"  {rp.name} 已存在且本次无新增，保留原报告")
        return 0
    if rp.exists() and fresh:
        old = rp.read_text(encoding="utf-8")
        idx = report.find("\n## ")
        extra = report[idx:].split("\n---\n")[0].strip() if idx != -1 else ""
        report = (old.rstrip() + f"\n\n<!-- 追加于 {run_dt:%H:%M} -->\n\n" + extra + "\n")
    rp.write_text(report, encoding="utf-8")
    (rdir / "latest.md").write_text(report, encoding="utf-8")
    for md_path in (rp, rdir / "latest.md"):
        Path(str(md_path).replace(".md", ".html")).write_text(
            md_to_html(report, f"公文通日报 {run_dt:%Y-%m-%d}"), encoding="utf-8")
    write_day_json(rdir, run_dt, fresh, summary_stats(fresh)["cats"], total, baseline)
    logf(f"  报告已写入 {rp}（含同名 .html/.json）")

    # 落盘：状态（记录本次扫描到的全部未知条目，含被类别过滤掉的）
    now = datetime.now().isoformat(timespec="seconds")
    for it in scanned:
        if it["id"] not in state:
            state[it["id"]] = {
                "first_seen": now, "title": it["title"], "url": it["url"],
                "category": it["category"], "dept": it["dept"],
                "list_date": it["list_date"],
            }
    save_state(cfg, state)
    append_archive(cfg, [{
        "run": now, "id": it["id"], "title": it["title"], "category": it["category"],
        "dept": it["dept"], "list_date": it["list_date"], "url": it["url"],
        "tags": it.get("tags", []), "deadline": it.get("deadline", ""),
        "abstract": it.get("abstract", ""),
    } for it in fresh])
    logf(f"  状态已更新：共记录 {len(state)} 条")

    # 控制台摘要
    if fresh:
        print(f"\n本次新增 {len(fresh)} 条：" + " · ".join(stats["by_cat"]))
        for it in fresh:
            flag = f"  ⏰{it['deadline']}" if it.get("deadline") else ""
            print(f"  [{it['category']}] {it['title'][:44]}  ({it['dept']}){flag}")
    else:
        print("\n今日无新增。")
    logf(f"===== 结束：{datetime.now():%Y-%m-%d %H:%M:%S} =====")
    return 0


def summary_stats(items: list[dict]) -> dict:
    cats: dict[str, int] = {}
    for it in items:
        cats[it["category"] or "其他"] = cats.get(it["category"] or "其他", 0) + 1
    order = [c for c in CAT_ORDER if c in cats] + [c for c in cats if c not in CAT_ORDER]
    return {"cats": cats, "by_cat": [f"{c} {cats[c]}" for c in order]}


def main() -> int:
    ensure_stdio()

    ap = argparse.ArgumentParser(description="深圳技术大学公文通每日更新汇总")
    ap.add_argument("--pages", type=int, help="最多翻几页列表（默认取配置，3 页）")
    ap.add_argument("--no-detail", action="store_true", help="不抓详情页")
    ap.add_argument("--dry-run", action="store_true", help="只打印报告，不写状态")
    ap.add_argument("--rebuild", action="store_true", help="清空状态重建基线")
    ap.add_argument("--test", action="store_true", help="只解析并打印首页列表")
    ap.add_argument("--categories", nargs="*", help="只关注这些类别，如 --categories 教务 科研")
    args = ap.parse_args()

    try:
        return run(args)
    except Exception:
        log(load_config(), "[fatal] 运行失败：\n" + traceback.format_exc())
        return 1

