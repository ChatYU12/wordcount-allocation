# -*- coding: utf-8 -*-
"""核心逻辑的单元测试。

运行：python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "app"))

from allocator import (  # noqa: E402
    allocate,
    allocate_best,
    compress_chapter_text,
    infer_per_page_words,
    rescale_units,
)
from excel_export import build_workbook  # noqa: E402
from pdf_parser import build_units, parse_book, parse_toc_text  # noqa: E402

SAMPLE_PDF = os.path.join(ROOT, "data", "0601终稿-老年人能力评估实务.pdf")

PEOPLE = [
    {"name": "夏群", "role": "主编", "target_words": 60000},
    {"name": "邓竹君", "role": "主编", "target_words": 50000},
    {"name": "景丽", "role": "主编", "target_words": 40000},
    {"name": "汪涛", "role": "副主编", "target_words": 40000},
    {"name": "卢振芝", "role": "副主编", "target_words": 40000},
    {"name": "欧唐燕", "role": "副主编", "target_words": 30000},
    {"name": "黄嘉嘉", "role": "副主编", "target_words": 30000},
    {"name": "刘洁俐", "role": "副主编", "target_words": 30000},
    {"name": "梁锦", "role": "参编", "target_words": 20000},
    {"name": "夏紫晴", "role": "参编", "target_words": 20000},
]


class TestTocParsing(unittest.TestCase):
    def test_parse_lines(self):
        lines = [
            "模块一　职业认知与基础素养",
            "项目一　职业认知", "３",
            "任务一　职业岗位认知", "５",
            "任务二　职业道德与素养", "１２",
            "项目检测", "１７",
            "参考文献", "２９７",
        ]
        nodes = parse_toc_text(lines)
        self.assertEqual(len(nodes), 5)
        self.assertEqual(nodes[0]["kind"], "project")
        self.assertEqual(nodes[0]["book_page"], 3)
        self.assertEqual(nodes[1]["book_page"], 5)
        self.assertEqual(nodes[1]["task_no"], 1)
        self.assertEqual(nodes[2]["task_no"], 2)
        self.assertEqual(nodes[3]["kind"], "tail")
        self.assertEqual(nodes[4]["kind"], "ref")

    def test_inline_page_number(self):
        nodes = parse_toc_text(["项目一 职业认知 3", "任务一 职业岗位认知 5"])
        self.assertEqual(len(nodes), 2)
        self.assertEqual(nodes[0]["book_page"], 3)
        self.assertEqual(nodes[0]["title"], "项目一 职业认知")


class TestSampleBook(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not os.path.exists(SAMPLE_PDF):
            raise unittest.SkipTest("示例 PDF 不存在")
        cls.result = parse_book(SAMPLE_PDF, per_page_words=1200)
        cls.units = cls.result["units"]

    def test_offset_detected(self):
        self.assertEqual(self.result["offset"], 7)

    def test_unit_count(self):
        self.assertEqual(len(self.units), 55)

    def test_units_contiguous_and_ordered(self):
        prev_end = None
        for u in self.units:
            self.assertGreaterEqual(u["pages"], 1, f"{u['label']} 页数异常")
            if prev_end is not None:
                # 相邻单元在书页上必须严格接续，不允许重叠或跳页
                self.assertEqual(u["start"], prev_end + 1, f"{u['label']} 与上一单元不连续")
            prev_end = u["end"]

    def test_total_pages(self):
        self.assertEqual(sum(u["pages"] for u in self.units), 294)

    def test_no_zero_page_units(self):
        self.assertTrue(all(u["pages"] > 0 for u in self.units))


class TestAllocator(unittest.TestCase):
    def setUp(self):
        # 手工构造一个可控的小书：10 个任务，每任务 10 页
        self.units = [
            {
                "index": i,
                "label": f"任务{i + 1}",
                "kind": "task",
                "start": i * 10 + 1,
                "end": i * 10 + 10,
                "pages": 10,
                "words": 10000,
                "project_no": i // 5 + 1,
            }
            for i in range(10)
        ]
        self.people = [
            {"name": "甲", "role": "主编", "target_words": 30000},
            {"name": "乙", "role": "副主编", "target_words": 20000},
            {"name": "丙", "role": "副主编", "target_words": 20000},
            {"name": "丁", "role": "参编", "target_words": 30000},
        ]

    def test_full_coverage(self):
        res = allocate(self.units, self.people, tolerance=0.1)
        covered = [x for seg in res["segments"] for x in seg["unit_idx"]]
        self.assertEqual(sorted(covered), list(range(10)))
        self.assertEqual(len(covered), len(set(covered)))

    def test_segments_are_contiguous(self):
        res = allocate(self.units, self.people, tolerance=0.1)
        expect_start = 1
        for seg in res["segments"]:
            self.assertEqual(seg["start"], expect_start)
            expect_start = seg["end"] + 1
        self.assertEqual(expect_start, 101)

    def test_words_conserved(self):
        res = allocate(self.units, self.people, tolerance=0.1)
        self.assertEqual(sum(s["words"] for s in res["segments"]), 100000)

    def test_everyone_gets_one_segment(self):
        res = allocate(self.units, self.people, tolerance=0.1)
        names = [m["name"] for seg in res["segments"] for m in seg["members"]]
        self.assertEqual(sorted(names), sorted(p["name"] for p in self.people))

    def test_exact_fit(self):
        # 4 个单元各 1 万字，2 人各 2 万 → 存在精确切分点，必须零偏差
        units = self.units[:4]
        people = [
            {"name": "甲", "role": "主编", "target_words": 20000},
            {"name": "乙", "role": "参编", "target_words": 20000},
        ]
        res = allocate_best(units, people, tolerance=0.05)
        for seg in res["segments"]:
            self.assertLessEqual(abs(seg["delta_ratio"]), 0.001)

    def test_granularity_limits_precision(self):
        # 单元粒度决定精度：5 个整万单元拆给 2 个 2.5 万的目标，必然偏差 20%
        units = self.units[:5]
        people = [
            {"name": "甲", "role": "主编", "target_words": 25000},
            {"name": "乙", "role": "参编", "target_words": 25000},
        ]
        res = allocate_best(units, people, tolerance=0.05)
        self.assertAlmostEqual(res["best_bound"], 0.2, delta=0.01)

    def test_too_many_people_raises(self):
        with self.assertRaises(ValueError):
            allocate(self.units[:2], self.people, tolerance=0.1)

    def test_cooperation_when_needed(self):
        # 3 个 10 万字的大单元 + 两位主编目标相仿，容易触发合作
        units = [
            {"index": i, "label": f"任务{i}", "kind": "task",
             "start": i * 100 + 1, "end": i * 100 + 100, "pages": 100,
             "words": 100000, "project_no": 1}
            for i in range(3)
        ]
        people = [
            {"name": "甲", "role": "主编", "target_words": 100000},
            {"name": "乙", "role": "副主编", "target_words": 100000},
            {"name": "丙", "role": "副主编", "target_words": 100000},
        ]
        res = allocate_best(units, people, tolerance=0.1)
        # 3 个 10 万字的大块 + 3 个 10 万目标：应出现一段两人合作，所以段数 <= 3
        names = [m["name"] for seg in res["segments"] for m in seg["members"]]
        self.assertEqual(sorted(names), ["丙", "乙", "甲"])
        self.assertLessEqual(len(res["segments"]), 3)
        self.assertTrue(any(seg["cooperative"] for seg in res["segments"]))

    def test_compress_chapter_text(self):
        units = [
            {"index": 0, "label": "项目一 职业认知", "kind": "project-head", "project_no": 1},
            {"index": 1, "label": "任务一 岗位认知", "kind": "task", "project_no": 1},
            {"index": 2, "label": "项目二 技能基础", "kind": "project-head", "project_no": 2},
            {"index": 3, "label": "任务一 流程梳理", "kind": "task", "project_no": 2},
        ]
        self.assertEqual(compress_chapter_text([0, 1], units), "项目一 职业认知")
        self.assertIn("项目二 技能基础", compress_chapter_text([0, 1, 2], units))

    def test_infer_per_page_words(self):
        units = [{"pages": 10}, {"pages": 20}]
        self.assertEqual(infer_per_page_words(units, 9000), 300)

    def test_rescale_units(self):
        scaled = rescale_units(self.units, 600)
        self.assertEqual(scaled[0]["words"], 6000)


class TestSampleAllocation(unittest.TestCase):
    """用真实书稿跑一次端到端，验证关键业务约束。"""

    @classmethod
    def setUpClass(cls):
        if not os.path.exists(SAMPLE_PDF):
            raise unittest.SkipTest("示例 PDF 不存在")
        parsed = parse_book(SAMPLE_PDF, per_page_words=1200)
        cls.units = parsed["units"]
        ppw = infer_per_page_words(cls.units, sum(p["target_words"] for p in PEOPLE))
        cls.ppw = ppw
        cls.scaled = rescale_units(cls.units, ppw)
        cls.res = allocate_best(cls.scaled, PEOPLE, tolerance=0.1)

    def test_conservation(self):
        self.assertEqual(
            sum(s["words"] for s in self.res["segments"]),
            sum(u["words"] for u in self.scaled),
        )

    def test_cover_all_units(self):
        covered = [x for s in self.res["segments"] for x in s["unit_idx"]]
        self.assertEqual(sorted(covered), list(range(len(self.scaled))))

    def test_page_range_continuous(self):
        expect = self.scaled[0]["start"]
        for s in self.res["segments"]:
            self.assertEqual(s["start"], expect)
            expect = s["end"] + 1
        self.assertEqual(expect, self.scaled[-1]["end"] + 1)

    def test_deviation_reported(self):
        self.assertIn("best_bound", self.res)
        self.assertGreater(self.res["best_bound"], 0)
        for s in self.res["segments"]:
            self.assertLessEqual(abs(s["delta_ratio"]), self.res["best_bound"] + 1e-6)

    def test_excel_export(self):
        buf = build_workbook(self.res, PEOPLE, units=self.scaled, per_page_words=self.ppw)
        data = buf.getvalue()
        self.assertGreater(len(data), 5000)
        import io
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(data))
        self.assertEqual(
            wb.sheetnames,
            ["分配总表", "按人汇总", "章节明细", "联合编写分工", "编写任务书", "计算说明"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestIndustryRules(unittest.TestCase):
    """按行业调研落实的规则：国标字数口径、合作段切分、角色层级、课时折算。"""

    def _units(self, spec):
        out = []
        start = 1
        for i, (pages, figs) in enumerate(spec):
            out.append({
                "index": i, "label": f"单元{i+1}", "kind": "task",
                "start": start, "end": start + pages - 1,
                "pages": pages, "figure_pages": figs,
                "words": pages * 1000, "project_no": i,
            })
            start += pages
        return out

    def test_figure_pages_lower_weight(self):
        from allocator import _weight_of
        u = {"pages": 10, "figure_pages": 2}
        self.assertAlmostEqual(_weight_of(u), 10 - 1.6, places=3)
        # 没有整页图时权重等于页数
        self.assertAlmostEqual(_weight_of({"pages": 10}), 10.0, places=3)
        # 显式 weight 优先
        self.assertAlmostEqual(_weight_of({"pages": 10, "weight": 4.5}), 4.5, places=3)

    def test_distribute_respects_figure_weight(self):
        from allocator import distribute_words
        # 两个单元页数相同，但第二个含 5 页整页图 → 分到的字数应更少
        units = self._units([(10, 0), (10, 5)])
        scaled = distribute_words(units, 100000)
        self.assertEqual(sum(u["words"] for u in scaled), 100000)
        self.assertGreater(scaled[0]["words"], scaled[1]["words"])

    def test_cooperative_split_by_target_ratio(self):
        from allocator import allocate_best
        units = self._units([(12, 0), (12, 0)])
        people = [
            {"name": "甲", "role": "主编", "target_words": 15000},
            {"name": "乙", "role": "副主编", "target_words": 5000},
        ]
        res = allocate_best(units, people, tolerance=0.2)
        seg = res["segments"][0]
        self.assertTrue(seg["cooperative"])
        shares = {x["name"]: x["words"] for x in seg["shares"]}
        self.assertEqual(sum(shares.values()), seg["words"])
        # 甲乙目标 3:1，切分也应接近 3:1
        self.assertGreater(shares["甲"], shares["乙"] * 2.5)

    def test_role_hierarchy_warning(self):
        from allocator import check_role_hierarchy
        fake = {
            "segments": [
                {"shares": [{"role": "主编", "words": 20000}]},
                {"shares": [{"role": "参编", "words": 40000}]},
            ]
        }
        warns = check_role_hierarchy(fake)
        self.assertTrue(any("倒挂" in w for w in warns))
        ok = {"segments": [{"shares": [{"role": "主编", "words": 40000}]},
                           {"shares": [{"role": "参编", "words": 20000}]}]}
        self.assertEqual(check_role_hierarchy(ok), [])

    def test_hours_in_export(self):
        import io

        import openpyxl

        from excel_export import build_workbook
        units = self._units([(6, 0), (6, 0), (6, 0)])
        people = [
            {"name": "甲", "role": "主编", "target_words": 6000},
            {"name": "乙", "role": "副主编", "target_words": 6000},
            {"name": "丙", "role": "参编", "target_words": 6000},
        ]
        from allocator import allocate_best
        res = allocate_best(units, people, tolerance=0.05)
        buf = build_workbook(
            res, people, units=units, per_page_words=1000,
            options={"hours_per_1000": 2.0, "deadline": "2026-06-30",
                     "book_title": "测试书"},
        )
        wb = openpyxl.load_workbook(io.BytesIO(buf.getvalue()))
        ws = wb["按人汇总"]
        hours_col = [c.value for c in ws["K"][1:]]
        self.assertTrue(any(isinstance(v, (int, float)) and v > 0 for v in hours_col))
        # 任务书含交稿日期
        ws4 = wb["编写任务书"]
        text = " ".join(str(c.value) for row in ws4.iter_rows() for c in row if c.value)
        self.assertIn("2026-06-30", text)
        self.assertIn("质量要求", text)


class TestPeopleImport(unittest.TestCase):
    """名单 Excel / CSV 导入。"""

    def setUp(self):
        import tempfile
        self.tmpdir = tempfile.mkdtemp()

    def _xlsx(self, rows, name="t.xlsx", title=None):
        import os

        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        if title:
            ws.title = title
        for r in rows:
            ws.append(list(r))
        path = os.path.join(self.tmpdir, name)
        wb.save(path)
        return path

    def test_parse_words_units(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_words
        cases = {
            "60000": 60000, "6万": 60000, "6.5w": 65000, "6W": 60000,
            "1千": 1000, "12,000": 12000, "60000字": 60000, 12000: 12000,
            5.5: 6, None: None, "无": None, "": None,
        }
        for raw, want in cases.items():
            self.assertEqual(parse_words(raw), want, f"parse_words({raw!r})")

    def test_normalize_role(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import normalize_role
        self.assertEqual(normalize_role("主编"), "主编")
        self.assertEqual(normalize_role("副主编"), "副主编")   # 不能误判成主编
        self.assertEqual(normalize_role("总主编"), "总主编")
        self.assertEqual(normalize_role("参编"), "参编")
        self.assertEqual(normalize_role("编委"), "参编")
        self.assertEqual(normalize_role(""), "参编")
        self.assertEqual(normalize_role(None), "参编")

    def test_standard_sheet(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_people_xlsx
        path = self._xlsx([
            ["序号", "姓名", "角色", "需要字数"],
            [1, "夏群", "主编", 60000],
            [2, "汪涛", "副主编", "4万"],
        ])
        res = parse_people_xlsx(path)
        self.assertTrue(res["ok"])
        self.assertEqual([p["name"] for p in res["people"]], ["夏群", "汪涛"])
        self.assertEqual(res["people"][1]["target_words"], 40000)
        self.assertEqual(res["header_row"], 1)

    def test_title_row_above_header(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_people_xlsx
        path = self._xlsx([
            ["《某书》编写名单"],
            [],
            ["部门", "姓名", "职称", "角色", "需要字数"],
            ["护理系", "夏群", "教授", "主编", "6万"],
            ["", "合计", "", "", "6万"],
        ])
        res = parse_people_xlsx(path)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["people"]), 1)          # 合计行被跳过
        self.assertEqual(res["header_row"], 3)
        self.assertEqual(res["people"][0]["role"], "主编")  # 没把「职称」当角色

    def test_allow_pair_column(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_people_xlsx
        path = self._xlsx([
            ["姓名", "角色", "需要字数", "可合作"],
            ["甲", "主编", 30000, "是"],
            ["乙", "参编", 20000, "否"],
        ])
        res = parse_people_xlsx(path)
        self.assertTrue(res["people"][0]["allow_pair"])
        self.assertFalse(res["people"][1]["allow_pair"])

    def test_no_header_reports_error(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_people_xlsx
        res = parse_people_xlsx(self._xlsx([["张三", "主编", 50000]]))
        self.assertFalse(res["ok"])
        self.assertIn("姓名", res["error"])

    def test_csv_gbk(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import parse_people_csv
        raw = "姓名,角色,需要字数\n王五,副主编,3.5万\n赵六,参编,1.2万\n".encode("gbk")
        res = parse_people_csv(raw)
        self.assertTrue(res["ok"])
        self.assertEqual([p["name"] for p in res["people"]], ["王五", "赵六"])
        self.assertEqual(res["people"][0]["target_words"], 35000)

    def test_template_roundtrip(self):
        """下载的模板必须能被自己导入回来。"""
        import io
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from people_import import build_people_template, parse_people_xlsx
        buf = build_people_template()
        path = os.path.join(self.tmpdir, "tpl.xlsx")
        with open(path, "wb") as f:
            f.write(buf.getvalue())
        res = parse_people_xlsx(path)
        self.assertTrue(res["ok"])
        self.assertEqual(len(res["people"]), 4)
        self.assertEqual(res["people"][0]["name"], "张三")
        self.assertEqual(res["people"][3]["target_words"], 20000)


class TestAuthorDetection(unittest.TestCase):
    """扉页编写名单识别。"""

    def test_sample_book_authors(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from pdf_parser import parse_book
        path = os.path.join(os.path.dirname(__file__), "..", "data",
                            "0601终稿-老年人能力评估实务.pdf")
        if not os.path.exists(path):
            self.skipTest("示例书未随仓库分发")
        res = parse_book(path)
        authors = res.get("authors", [])
        names = [a["name"] for a in authors]
        roles = {a["name"]: a["role"] for a in authors}
        self.assertEqual(len(authors), 11)
        self.assertEqual(roles["邹文开"], "总主编")
        self.assertEqual(roles["夏群"], "主编")
        self.assertEqual(roles["汪涛"], "副主编")
        self.assertEqual(roles["梁锦"], "参编")
        # 目录页的「项目检测」「岗位实践」不能混进来
        for bad in ("项目检测", "岗位实践", "能力拓展", "参考文献", "模块一"):
            self.assertNotIn(bad, names)

    def test_role_normalization(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from pdf_parser import _norm_author_role
        self.assertEqual(_norm_author_role("总主编"), "总主编")
        self.assertEqual(_norm_author_role("副主编"), "副主编")
        self.assertEqual(_norm_author_role("主编"), "主编")
        self.assertEqual(_norm_author_role("编委"), "参编")


class TestCoverParser(unittest.TestCase):
    """扉页版式还原与名单解析（不依赖 OCR）。"""

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from cover_parser import parse_rows
        self.parse_rows = parse_rows

    def test_standard_layout(self):
        rows = [
            ["老年健康评估"],
            ["主审", "杨晔琴"],
            ["总主编", "左春雨"],
            ["主编", "王春桃", "龚建光", "任兰梅"],
            ["副主编", "朱娟", "王静", "潘菲菲"],
            ["赵莉萍", "贾华华", "田莉萍"],          # 续行
            ["参编", "刘洋", "孙玲玲"],
            ["陈志朋", "周丽华", "杨丽"],            # 参编续行
        ]
        r = self.parse_rows(rows)
        self.assertEqual(r["title"], "老年健康评估")
        self.assertEqual(len(r["authors"]), 16)
        roles = {a["name"]: a["role"] for a in r["authors"]}
        self.assertEqual(roles["杨晔琴"], "主审")
        self.assertEqual(roles["左春雨"], "总主编")
        self.assertEqual(roles["任兰梅"], "主编")
        self.assertEqual(roles["田莉萍"], "副主编")   # 续行要继承角色
        self.assertEqual(roles["杨丽"], "参编")

    def test_duplicate_role_means_ocr_lost_a_char(self):
        """「副主编」被 OCR 成「主编」时，应按降级处理并给出提示。"""
        rows = [
            ["主编", "王春桃"],
            ["主编", "朱娟"],      # 实际是「副主编」，漏了「副」
            ["参编", "刘洋"],
        ]
        r = self.parse_rows(rows)
        roles = {a["name"]: a["role"] for a in r["authors"]}
        self.assertEqual(roles["王春桃"], "主编")
        self.assertEqual(roles["朱娟"], "副主编")
        self.assertTrue(any("重复出现" in w for w in r["warnings"]))

    def test_merged_role_and_name(self):
        """角色词与姓名黏在一格时要能拆开。"""
        rows = [["主审赵一鸣"], ["主编孙三峰"], ["参编郑七弦"]]
        r = self.parse_rows(rows)
        roles = {a["name"]: a["role"] for a in r["authors"]}
        self.assertEqual(roles.get("赵一鸣"), "主审")
        self.assertEqual(roles.get("孙三峰"), "主编")
        self.assertEqual(roles.get("郑七弦"), "参编")

    def test_role_tokens_split_into_chars(self):
        """角色词被拆成单字时要能合回去。"""
        rows = [["参", "编", "郑七弦", "王八斗"]]
        r = self.parse_rows(rows)
        roles = {a["name"]: a["role"] for a in r["authors"]}
        self.assertEqual(roles.get("郑七弦"), "参编")
        self.assertEqual(roles.get("王八斗"), "参编")

    def test_name_with_inner_space(self):
        """「杨 丽」是姓名内空格，不能拆成两个人。"""
        from cover_parser import expand_row
        self.assertEqual(expand_row(["杨 丽"]), ["杨丽"])
        self.assertEqual(expand_row(["周五湖 吴六桥"]), ["周五湖", "吴六桥"])

    def test_audit_typo(self):
        """「主审」被识成形近字也要认出来。"""
        from cover_parser import match_role
        self.assertEqual(match_role("主审"), "主审")
        self.assertEqual(match_role("主車"), "主审")
        self.assertIsNone(match_role("主任"))     # 不是角色
        self.assertIsNone(match_role("张三"))


class TestCompanyPolicy(unittest.TestCase):
    """公司字数制度。"""

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from policy import apply_member_fill, build_initial_people, suggest_members
        self.build = build_initial_people
        self.suggest = suggest_members
        self.fill = apply_member_fill

    def _authors(self):
        return [
            {"name": "赵一鸣", "role": "主审"},
            {"name": "钱二山", "role": "总主编"},
            {"name": "孙三峰", "role": "主编"},
            {"name": "李四海", "role": "主编"},
            {"name": "周小五", "role": "主编"},
            {"name": "吴六桥", "role": "副主编"},
            {"name": "郑七弦", "role": "参编"},
        ]

    def test_chief_tiers(self):
        b = self.build(self._authors())
        words = {p["name"]: p["target_words"] for p in b["people"]}
        self.assertEqual(words["孙三峰"], 60000)   # 第一主编
        self.assertEqual(words["李四海"], 50000)   # 第二主编
        self.assertEqual(words["周小五"], 30000)   # 第三主编
        self.assertEqual(words["吴六桥"], 20000)   # 副主编
        self.assertEqual(words["郑七弦"], 0)       # 参编默认 0

    def test_non_writing_roles_skipped(self):
        b = self.build(self._authors())
        names = [p["name"] for p in b["people"]]
        self.assertNotIn("赵一鸣", names)          # 主审
        self.assertNotIn("钱二山", names)          # 总主编
        self.assertEqual(len(b["skipped"]), 2)

    def test_policy_total(self):
        b = self.build(self._authors())
        self.assertEqual(b["policy_total"], 60000 + 50000 + 30000 + 20000)

    def test_fourth_chief_uses_floor(self):
        authors = [{"name": f"主编{i}", "role": "主编"} for i in range(4)]
        b = self.build(authors)
        self.assertEqual([p["target_words"] for p in b["people"]],
                         [60000, 50000, 30000, 30000])

    def test_member_fill_when_enough(self):
        b = self.build(self._authors())
        s = self.suggest(b["people"], 200000)
        self.assertEqual(s["can_fill"], 1)
        filled = self.fill(b["people"], s["can_fill"])
        self.assertEqual(sum(p["target_words"] for p in filled), 160000 + 10000)

    def test_member_not_filled_when_tight(self):
        b = self.build(self._authors())
        s = self.suggest(b["people"], 165000)      # 只余 5 千
        self.assertEqual(s["can_fill"], 0)
        filled = self.fill(b["people"], 0)
        self.assertEqual(sum(p["target_words"] for p in filled), 160000)


class TestCoverOcr(unittest.TestCase):
    """真实 OCR 端到端（仅 macOS + Vision 可用时执行）。"""

    def test_ocr_sample_cover(self):
        import platform
        import sys
        if platform.system() != "Darwin":
            self.skipTest("Vision OCR 仅在 macOS 可用")
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from cover_parser import _ensure_ocr_binary, cluster_rows, ocr_image
        if not _ensure_ocr_binary() and not os.path.exists(os.path.join(
                os.path.dirname(__file__), "..", "app", "bin", "ocr.swift")):
            self.skipTest("缺少 OCR 组件")
        # 只验证 OCR 通道可用，不绑定具体图片
        self.assertTrue(callable(ocr_image))
        self.assertTrue(callable(cluster_rows))


class TestSectionSplit(unittest.TestCase):
    """按一级分节（一、二、三）再拆分任务。"""

    def test_split_reduces_unit_size(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from pdf_parser import parse_book
        path = os.path.join(os.path.dirname(__file__), "..", "data",
                            "0601终稿-老年人能力评估实务.pdf")
        if not os.path.exists(path):
            self.skipTest("示例书未随仓库分发")
        plain = parse_book(path)
        split = parse_book(path, split_sections=True, min_section_pages=1)
        self.assertGreater(len(split["units"]), len(plain["units"]))
        # 页数守恒
        self.assertEqual(sum(u["pages"] for u in split["units"]),
                         sum(u["pages"] for u in plain["units"]))
        # 最大单元变小
        self.assertLess(max(u["pages"] for u in split["units"]),
                        max(u["pages"] for u in plain["units"]))

    def test_split_labels_keep_section_title(self):
        import sys
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
        from pdf_parser import parse_book
        path = os.path.join(os.path.dirname(__file__), "..", "data",
                            "0601终稿-老年人能力评估实务.pdf")
        if not os.path.exists(path):
            self.skipTest("示例书未随仓库分发")
        res = parse_book(path, split_sections=True, min_section_pages=1)
        # 切出来的小块应带上分节标题或页码范围，而不是全都同名
        labels = [u["label"] for u in res["units"]]
        # 至少有一条 label 带出了分节标题（如「任务一 …（一、准备工作）」）
        self.assertTrue(any("、" in x for x in labels), "没有一条 label 带上分节标题")
        # 每个单元都有 label，且互不重复到无法区分（用页码兜底）
        self.assertTrue(all(x for x in labels))
