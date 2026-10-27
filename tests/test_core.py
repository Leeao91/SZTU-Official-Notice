# -*- coding: utf-8 -*-
"""离线单元测试：不需要校园网，用 fixtures 里的真实页面做回归。

    python -m unittest discover -s tests -v
"""
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nbwdigest import cli, core  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
LIST_HTML = (FIXTURES / "list.html").read_text(encoding="utf-8")
DETAIL_HTML = (FIXTURES / "detail.html").read_text(encoding="utf-8")
CFG = core.load_config()


class TestNormalize(unittest.TestCase):
    def test_collapses_spaces_inside_chinese(self):
        raw = "拟于 2026 年 11 月下旬在广州举行"
        self.assertEqual(core.normalize_cn(raw), "拟于2026年11月下旬在广州举行")

    def test_keeps_paragraph_breaks(self):
        out = core.normalize_cn("第一段\n\n\n第二段")
        self.assertEqual(out, "第一段\n\n第二段")


class TestParseList(unittest.TestCase):
    def setUp(self):
        self.items, self.total = core.parse_list(LIST_HTML, core.build_page_url(CFG, 1), CFG)

    def test_returns_full_page(self):
        self.assertEqual(len(self.items), 20)
        self.assertIsNotNone(self.total)
        self.assertGreater(self.total, 1000)

    def test_fields_complete(self):
        for it in self.items:
            self.assertTrue(it["id"])
            self.assertTrue(it["title"])
            self.assertTrue(it["url"].startswith("https://"))
            self.assertRegex(it["list_date"], r"^\d{4}-\d{1,2}-\d{1,2}$")
            self.assertIn(it["category"], {"教务", "科研", "行政", "学工", "校园"})

    def test_ids_unique(self):
        ids = [it["id"] for it in self.items]
        self.assertEqual(len(ids), len(set(ids)))

    def test_title_has_no_leading_dot(self):
        self.assertFalse(any(it["title"].startswith(". ") for it in self.items))

    def test_pagination_url(self):
        self.assertNotIn("PAGENUM", core.build_page_url(CFG, 1))
        self.assertIn("PAGENUM=3", core.build_page_url(CFG, 3))


class TestParseDetail(unittest.TestCase):
    def setUp(self):
        self.d = core.parse_detail(DETAIL_HTML, "https://example.org/info/1018/52518.htm", CFG)

    def test_title(self):
        self.assertIn("南方教育年会", self.d["detail_title"])

    def test_meta(self):
        self.assertEqual(self.d["author"], "教务部")
        self.assertIn("2026年", self.d["publish_time"])

    def test_body_clean(self):
        body = self.d["body"]
        self.assertGreater(len(body), 80)
        self.assertNotIn("vsb_content", body)      # 标签残留
        self.assertNotIn("<", body)
        self.assertIn("广东省教育厅", body)

    def test_attachments(self):
        names = [a["name"] for a in self.d["attachments"]]
        self.assertEqual(len(names), 2)
        self.assertTrue(any("报名表" in n for n in names))
        for a in self.d["attachments"]:
            self.assertTrue(a["url"].startswith("https://"))
            self.assertIn("download.jsp", a["url"])


class TestDateAndDeadline(unittest.TestCase):
    TODAY = date(2026, 10, 19)

    def test_explicit_before(self):
        text = "请于2026年10月21日16:00前将意见发送至邮箱。"
        self.assertEqual(core.find_deadline(text, self.TODAY, 7), "2026-10-21")

    def test_yearless_month_day(self):
        text = "请于10月22日前提交材料。"
        self.assertEqual(core.find_deadline(text, self.TODAY, 7), "2026-10-22")

    def test_public_notice_range(self):
        text = "公示时间：2026年10月19日-2026年10月23日。"
        self.assertEqual(core.find_deadline(text, self.TODAY, 7), "2026-10-23")

    def test_no_deadline_wording(self):
        text = "会议将于2026年11月20日在图书馆举行。"
        self.assertEqual(core.find_deadline(text, self.TODAY, 7), "")

    def test_out_of_window(self):
        text = "请于2027年3月1日前完成。"
        self.assertEqual(core.find_deadline(text, self.TODAY, 7), "")


class TestSummarize(unittest.TestCase):
    def test_tags(self):
        self.assertIn("讲座", core.guesses_tags("关于举办学术讲座的通知"))
        self.assertIn("公示", core.guesses_tags("拟获奖名单公示"))
        self.assertEqual(core.guesses_tags("关于停电作业的通知"), ["后勤"])

    def test_summary_filters_boilerplate(self):
        from datetime import timedelta
        soon = date.today() + timedelta(days=2)
        cn_date = f"{soon.year}年{soon.month}月{soon.day}日"
        detail = {"body": "现将有关事项通知如下：\n"
                           f"请于{cn_date}前将材料交至行政楼。\n"
                           "联系人：张老师，电话：23256111。", "attachments": []}
        s = core.make_summary({"title": "关于报送材料的通知"}, detail, CFG)
        self.assertNotIn("现将有关事项通知如下", s["abstract"])
        self.assertEqual(s["deadline"], soon.isoformat())
        self.assertTrue(any("电话" in p for p in s["key_points"]))


class TestRender(unittest.TestCase):
    def _item(self, **kw):
        base = {"id": "1/2", "title": "关于测试的通知", "category": "教务", "dept": "教务部",
                "url": "https://example.org/info/1/2.htm", "list_date": "2026-10-19",
                "publish_time": "", "author": "", "tags": ["通知"], "deadline": "",
                "abstract": "测试要点。", "key_points": ["时间：10月20日"],
                "attachments": [], "has_attach": False}
        base.update(kw)
        return base

    def test_report_contains_sections(self):
        from datetime import datetime
        items = [self._item(deadline="2026-10-20"), self._item(id="1/3", category="科研")]
        md = core.render_report(datetime(2026, 10, 19, 18, 0), items,
                                cli.summary_stats(items), False, 15000)
        self.assertIn("公文通", md)
        self.assertIn("⏰", md)
        self.assertIn("## 教务", md)
        self.assertIn("## 科研", md)

    def test_empty_report(self):
        from datetime import datetime
        md = core.render_report(datetime(2026, 10, 19, 18, 0), [], cli.summary_stats([]), False, 1)
        self.assertIn("今日无新增", md)

    def test_html_links_not_nested(self):
        md = "# 标题\n\n- [链接](https://a.example/x) 和 https://b.example/y\n"
        html = core.md_to_html(md, "t")
        self.assertNotIn('href="<a', html)
        self.assertIn('href="https://a.example/x"', html)
        self.assertIn('href="https://b.example/y"', html)

    def test_item_record_keys(self):
        rec = cli.item_record(self._item())
        for key in ("id", "title", "url", "category", "tags", "deadline", "attachments"):
            self.assertIn(key, rec)


class TestStdioGuard(unittest.TestCase):
    """计划任务用 pythonw 跑，stdout 是 None —— 这里守住那个坑（曾经真炸过）。"""

    def test_none_stdout_is_replaced(self):
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = None
        try:
            core.ensure_stdio()
            self.assertIsNotNone(sys.stdout)
            self.assertIsNotNone(sys.stderr)
            print("这行不能崩")            # 关键：print 必须可用
        finally:
            sys.stdout, sys.stderr = old_out, old_err


class TestCollectWatermark(unittest.TestCase):
    """用假数据验证增量翻页策略，不联网。"""

    def _run(self, pages, state):
        calls = []

        def fake_fetch(url, cfg, note=""):
            calls.append(url)
            return ""

        def fake_parse(html, url, cfg):
            return pages[len(calls) - 1], 15397

        cfg = dict(CFG, request_interval=0)
        orig = (cli.fetch, cli.parse_list)
        cli.fetch, cli.parse_list = fake_fetch, fake_parse
        try:
            fresh, total, truncated = cli.collect(cfg, state, 3, lambda m: None)
        finally:
            cli.fetch, cli.parse_list = orig
        return fresh, calls

    @staticmethod
    def _page(*ids):
        return [{"id": i, "num": "1", "title": f"标题{i}", "url": "u", "category": "教务",
                 "dept": "教务部", "list_date": "2026-10-27", "has_attach": False} for i in ids]

    def test_stops_when_oldest_known(self):
        page1 = self._page("a", "b", "c", "d")
        fresh, calls = self._run([page1], {"d": {}})
        self.assertEqual([f["id"] for f in fresh], ["a", "b", "c"])
        self.assertEqual(len(calls), 1)          # 只请求 1 页

    def test_middle_insert_not_missed(self):
        page1 = self._page("a", "b", "c", "d")
        fresh, _ = self._run([page1], {"a": {}, "b": {}, "d": {}})
        self.assertEqual([f["id"] for f in fresh], ["c"])

    def test_goes_to_next_page_when_all_new(self):
        p1 = self._page("a", "b", "c", "d")
        p2 = self._page("e", "f")
        fresh, calls = self._run([p1, p2], {"f": {}})
        self.assertEqual([f["id"] for f in fresh], ["a", "b", "c", "d", "e"])
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
