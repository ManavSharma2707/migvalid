"""
test_python.py - unit tests for the Python side.   python tests/test_python.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import gen_data                      # noqa: E402
import render                        # noqa: E402
import validator_core as vc          # noqa: E402


class TestGenerator(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_layouts_and_determinism(self):
        a = gen_data.write_scenario("seeded", self.tmp / "a")
        b = gen_data.write_scenario("seeded", self.tmp / "b")
        for f in ("src_extract.txt", "tgt_extract.txt",
                  "customer_new_load.sql", "expected.json"):
            self.assertEqual((a / f).read_bytes(), (b / f).read_bytes())
        self.assertNotIn(b"\r", (a / "src_extract.txt").read_bytes())
        for ln in (a / "src_extract.txt").read_text().splitlines():
            self.assertEqual(len(ln), 80)
        for ln in (a / "tgt_extract.txt").read_text().splitlines():
            self.assertEqual(len(ln), 100)
        for ln in (a / "customer_new_load.sql").read_text().splitlines():
            self.assertLessEqual(len(ln), 72)

    def test_answer_key_matches_reference(self):
        for sc in gen_data.SCENARIOS:
            d = gen_data.write_scenario(sc, self.tmp)
            exp = json.loads((d / "expected.json").read_text())
            r = vc.reconcile(vc.read_lines(str(d / "src_extract.txt")),
                             vc.read_lines(str(d / "tgt_extract.txt")))
            self.assertEqual((r.rc, r.decision), (exp["rc"], exp["decision"]),
                             sc)
            if sc != "dup_target":
                for k in ("raw", "dups", "src_unique", "tgt_cnt", "matched",
                          "mismatch", "missing", "extra"):
                    self.assertEqual(getattr(r, k), exp[k], f"{sc}.{k}")

    def test_seeded_numbers_from_the_slides(self):
        d = gen_data.write_scenario("seeded", self.tmp)
        r = vc.reconcile(vc.read_lines(str(d / "src_extract.txt")),
                         vc.read_lines(str(d / "tgt_extract.txt")))
        self.assertEqual((r.raw, r.dups, r.src_unique, r.tgt_cnt), (1020, 20, 1000, 995))
        self.assertEqual((r.matched, r.mismatch, r.missing, r.extra), (975, 15, 10, 5))
        self.assertEqual(r.matched + r.mismatch + r.missing, 1000)
        self.assertEqual(len(vc.find_duplicates(
            vc.read_lines(str(d / "src_extract.txt")))), 20)


class TestRender(unittest.TestCase):
    CFG = {"hlq": "Z12345", "acct": "1", "job_class": "A", "msgclass": "H",
           "unit": "SYSDA", "db2_ssid": "DBCG", "db2_loadlib": "A.B.C",
           "db2_runlib": "A.B.D", "db2_plan": "DSNTEP12",
           "cobol_proc": "IGYWCL", "cobol_lngprfx": ""}

    def test_all_templates_render_clean(self):
        self.assertEqual(render.render(self.CFG), [])

    def test_lngprfx_override(self):
        cfg = dict(self.CFG, cobol_lngprfx="IGY.V6R3M0")
        self.assertEqual(render.render(cfg), [])
        txt = (render.BUILD / "jcl" / "COMPILE.jcl").read_text()
        self.assertIn("EXEC IGYWCL,LNGPRFX=IGY.V6R3M0", txt)

    def test_long_userid_is_rejected(self):
        p = Path(tempfile.mkdtemp()) / "c.json"
        p.write_text(json.dumps(dict(self.CFG, hlq="ABCDEFGH")))
        with self.assertRaises(render.ConfigError):
            render.load_config(p)

    def test_linter_catches_problems(self):
        self.assertTrue(render.lint("jcl", "x", "//X JOB\n" + "A" * 80))
        self.assertTrue(render.lint("rexx", "x", "a = b | c"))
        self.assertTrue(render.lint("cobol", "x", "\tMOVE"))

    def test_no_dataset_outside_own_hlq(self):
        render.render(self.CFG)
        import re
        for f in (render.BUILD / "jcl").glob("*.jcl"):
            for m in re.finditer(r"(?:DSN|DSNAME)=([A-Z0-9.$#@]+)",
                                 f.read_text()):
                dsn = m.group(1)
                if dsn in ("A.B.C",):          # DB2 library from the config
                    continue
                self.assertTrue(dsn.startswith("Z12345.MIG."),
                                f"{f.name}: {dsn}")


class TestApp(unittest.TestCase):
    def test_offline_mode_all_scenarios(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(str(ROOT / "python" / "app.py"),
                               default_timeout=90).run()
        self.assertFalse(at.exception)
        for sc in gen_data.SCENARIOS:
            at.sidebar.selectbox[0].select(sc).run()
            self.assertFalse(at.exception, sc)

    def test_mainframe_mode_with_a_saved_run(self):
        from streamlit.testing.v1 import AppTest
        d = gen_data.write_scenario("seeded", Path(tempfile.mkdtemp()))
        src = vc.read_lines(str(d / "src_extract.txt"))
        tgt = vc.read_lines(str(d / "tgt_extract.txt"))
        res = vc.reconcile(src, tgt)
        run = ROOT / "runs" / "B_UNITTEST"
        shutil.rmtree(run, ignore_errors=True)
        run.mkdir(parents=True)
        try:
            for n in ("src_extract.txt", "tgt_extract.txt", "expected.json"):
                shutil.copy(d / n, run / n)
            kv = vc.result_to_dict(res)
            kv["BATCH_ID"] = "B_UNITTEST"
            (run / "result.txt").write_text(
                "".join(f"{k}={v}\n" for k, v in kv.items()))
            lines = []
            for e in res.exceptions:
                lines.append(e.cust_id.ljust(8) + e.acct_no.ljust(10)
                             + e.err_type.ljust(8) + e.field.ljust(8)
                             + e.src_val.ljust(30) + e.tgt_val.ljust(30))
            (run / "exceptions.txt").write_text("\n".join(lines) + "\n")
            (run / "report.txt").write_text("REPORT\n")
            at = AppTest.from_file(str(ROOT / "python" / "app.py"),
                                   default_timeout=90).run()
            self.assertFalse(at.exception)
            self.assertEqual(at.sidebar.radio[0].value, "Mainframe runs")
            self.assertTrue(any("identical" in s.value for s in at.success))
        finally:
            shutil.rmtree(run, ignore_errors=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
