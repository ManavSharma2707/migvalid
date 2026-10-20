"""
test_mainframe_logic.py - runs the REAL COBOL program (GnuCOBOL) and the
REAL REXX exec (Regina REXX) on all four scenarios and compares the output
with the pure-Python reference implementation.

    python tests/test_mainframe_logic.py

Needs:  cobc (GnuCOBOL 3.x)  and  regina (Regina REXX)  installed.
The DFSORT / ICETOOL steps are emulated in Python (they are standard
utilities, not code we wrote).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "python"))
import gen_data                       # noqa: E402
import validator_core as vc           # noqa: E402

COBOL = ROOT / "mainframe" / "cobol" / "MIGMATCH.cbl"
REXX = ROOT / "mainframe" / "rexx" / "MIGREXX.rexx"

SHIM = r'''
ReadAll:
   parse arg zzdd
   zzp = value('MIGDIR',,'ENVIRONMENT')'/'zzdd
   io.0 = 0
   zzn = 0
   do while lines(zzp) > 0
      zzn = zzn + 1
      io.zzn = linein(zzp)
   end
   call lineout zzp
   io.0 = zzn
   return

WriteAll:
   parse arg zzdd
   zzp = value('MIGDIR',,'ENVIRONMENT')'/'zzdd'.out'
   call lineout zzp
   address system 'rm -f' zzp
   do zzi = 1 to out.0
      call lineout zzp, out.zzi
   end
   call lineout zzp
   return
'''


def build_rexx_test(dest: Path) -> None:
    text = REXX.read_text()
    head = text.split("/* ==IO-BEGIN==")[0]
    dest.write_text(head + SHIM)


def emulate_sort(lines: list[str], lrecl: int, dedupe: bool) -> list[str]:
    """DFSORT: SORT FIELDS=(1,18,CH,A), OPTION EQUALS, optional SUM NONE."""
    ordered = sorted(lines, key=lambda x: x[:18].ljust(18))   # stable
    if not dedupe:
        return ordered
    out, last = [], None
    for ln in ordered:
        k = ln[:18]
        if k != last:
            out.append(ln)
            last = k
    return out


def write_fixed(path: Path, lines: list[str], lrecl: int) -> None:
    path.write_bytes(b"".join(x.ljust(lrecl).encode("ascii") for x in lines))


def read_fixed(path: Path, lrecl: int) -> list[str]:
    b = path.read_bytes().decode("ascii")
    assert len(b) % lrecl == 0, f"{path} length {len(b)} not multiple of {lrecl}"
    return [b[i:i + lrecl] for i in range(0, len(b), lrecl)]


def run_scenario(sc: str, work: Path) -> list[str]:
    gen_data.write_scenario(sc, work / "data")
    src = vc.read_lines(str(work / "data" / sc / "src_extract.txt"))
    tgt = vc.read_lines(str(work / "data" / sc / "tgt_extract.txt"))
    return run_lines(sc, src, tgt, work)


def run_lines(sc: str, src: list[str], tgt: list[str], work: Path,
              expect_cobol_rc: int | None = None) -> list[str]:
    errors: list[str] = []
    d = work / sc
    d.mkdir()

    # ---- STEP010/015/020 emulation
    dedup = emulate_sort(src, 80, True)
    tsort = emulate_sort(tgt, 100, False)
    write_fixed(d / "SRCIN.bin", dedup, 80)
    write_fixed(d / "TGTIN.bin", tsort, 100)
    for dd, label, n in (("CNTRAW", "RAW=", len(src)),
                         ("CNTDED", "DEDUP=", len(dedup)),
                         ("CNTTGT", "TGT=", len(tsort))):
        (d / dd).write_text(f"{label}{n:010d}".ljust(80) + "\n")

    # ---- STEP030 COBOL
    env = dict(os.environ, DD_SRCIN=str(d / "SRCIN.bin"),
               DD_TGTIN=str(d / "TGTIN.bin"),
               DD_EXCOUT=str(d / "EXCOUT.bin"),
               DD_CTLOUT=str(d / "CTLOUT.bin"))
    p = subprocess.run([str(work / "migmatch")], env=env,
                       capture_output=True, text=True)
    want = 12 if sc == "dup_target" else 0
    if expect_cobol_rc is not None:
        want = expect_cobol_rc
    if p.returncode != want:
        errors.append(f"COBOL RC {p.returncode}, expected {want}\n{p.stdout}")
    exc_recs = read_fixed(d / "EXCOUT.bin", 100)
    ctl = read_fixed(d / "CTLOUT.bin", 120)
    assert len(ctl) == 1, "control file must hold exactly 1 record"
    (d / "EXCIN").write_text("".join(x + "\n" for x in exc_recs))
    (d / "CTLIN").write_text(ctl[0] + "\n")

    # ---- STEP040 REXX
    rx = work / "migrexx_test.rexx"
    build_rexx_test(rx)
    env = dict(os.environ, MIGDIR=str(d))
    p = subprocess.run(["regina", str(rx)], env=env, capture_output=True,
                       text=True)
    oracle = vc.reconcile(src, tgt)
    if p.returncode != oracle.rc:
        errors.append(f"REXX RC {p.returncode}, reference RC {oracle.rc}\n"
                      f"{p.stdout}\n{p.stderr}")
        return errors

    result = vc.parse_result((d / "RESULT.out").read_text())
    exc = vc.parse_excsort((d / "EXCSORT.out").read_text())
    diffs = vc.compare_to_oracle(result, exc, oracle)
    errors += diffs

    # ---- format checks on every dataset REXX produced
    sql = [x.rstrip() for x in (d / "SQLOUT.out").read_text().splitlines()]
    if any(len(x.rstrip()) > 72 for x in sql):
        errors.append("SQL line longer than 72")
    if not sql or sql[-1].strip() != "COMMIT;":
        errors.append("SQL must end with COMMIT;")
    n_ins = sum(1 for x in sql if x.startswith("INSERT INTO MIG_EXCEPTION"))
    if oracle.rc != 12 and n_ins != len(oracle.exceptions):
        errors.append(f"SQL has {n_ins} exception inserts, "
                      f"expected {len(oracle.exceptions)}")
    for dd, w in (("EXCSORT.out", 100), ("REPORT.out", 133),
                  ("RESULT.out", 80), ("CTLREC.out", 120), ("SQLOUT.out", 80)):
        for ln in (d / dd).read_text().splitlines():
            if len(ln) > w:
                errors.append(f"{dd}: line longer than LRECL {w}")
                break
    ctlrec = (d / "CTLREC.out").read_text().rstrip("\n")
    if len(ctlrec.rstrip()) < 15 or len(ctlrec) > 120:
        errors.append("CTLREC layout")
    if oracle.rc != 12:
        # sort order check: MISSING rows first, then MISMATCH, then EXTRA
        order = [e.err_type for e in exc]
        rank = {"MISSING": 1, "MISMATCH": 2, "EXTRA": 3}
        if [rank[x] for x in order] != sorted(rank[x] for x in order):
            errors.append("EXCSORT not sorted by type")
    return errors


def edge_cases() -> dict[str, tuple[list[str], list[str]]]:
    def S(cid, acct, name, bal, date, st):
        return (cid.ljust(8) + acct.ljust(10) + name.ljust(20) + bal
                + date + st).ljust(80)

    def T(cid, acct, name, bal, date, st):
        return (cid.ljust(8) + acct.ljust(10) + name.ljust(40)
                + bal.rjust(12) + date + st).ljust(100)

    ok_s = S("C0000001", "A000000001", "ASHA RAO", "00000500000",
             "20260101", "A")
    ok_t = T("C0000001", "A000000001", "ASHA RAO", "5000.00",
             "2026-01-01", "A")
    cases = {}
    # odd formats on the target side
    cases["edge_badfmt"] = (
        [ok_s,
         S("C0000002", "A000000002", "O'NEIL", "00000100000", "20260102", "A"),
         S("C0000003", "A000000003", "BAD BAL", "00000100000", "20260103", "A"),
         S("C0000004", "A000000004", "BAD DATE", "00000100000", "20260104", "A"),
         S("C0000005", "A000000005", "BLANK BAL", "00000100000", "20260105", "A"),
         S("C0000006", "A000000006", "NEG BAL", "00000100000", "20260106", "A")],
        [ok_t,
         T("C0000002", "A000000002", "O'NEIL X", "1000.00", "2026-01-02", "A"),
         T("C0000003", "A000000003", "BAD BAL", "ABC", "2026-01-03", "A"),
         T("C0000004", "A000000004", "BAD DATE", "1000.00", "2026/01/04", "A"),
         T("C0000005", "A000000005", "BLANK BAL", "", "2026-01-05", "A"),
         T("C0000006", "A000000006", "NEG BAL", "-1000.00", "2026-01-06", "A")])
    cases["edge_empty_tgt"] = ([ok_s], [])
    cases["edge_empty_src"] = ([], [ok_t])
    cases["edge_both_ok"] = ([ok_s], [ok_t])
    # key ordering: only the first and last record match
    cases["edge_interleaved"] = (
        [S("C0000001", "A000000001", "A", "00000000100", "20260101", "A"),
         S("C0000003", "A000000003", "C", "00000000300", "20260101", "A"),
         S("C0000005", "A000000005", "E", "00000000500", "20260101", "A")],
        [T("C0000002", "A000000002", "B", "2.00", "2026-01-01", "A"),
         T("C0000003", "A000000003", "C", "3.00", "2026-01-01", "A"),
         T("C0000004", "A000000004", "D", "4.00", "2026-01-01", "A")])
    return cases


def main() -> int:
    if not (shutil.which("cobc") and shutil.which("regina")):
        print("cobc and/or regina not installed - skipping")
        return 0
    work = Path(tempfile.mkdtemp(prefix="migtest_"))
    subprocess.run(["cobc", "-x", "-Wall", "-o", str(work / "migmatch"),
                    str(COBOL)], check=True, capture_output=True)
    bad = 0
    for sc in gen_data.SCENARIOS:
        errs = run_scenario(sc, work)
        print(f"{sc:11s}", "PASS" if not errs else "FAIL")
        for e in errs:
            print("   -", e)
        bad += bool(errs)
    for name, (src, tgt) in edge_cases().items():
        errs = run_lines(name, src, tgt, work)
        print(f"{name:16s}", "PASS" if not errs else "FAIL")
        for e in errs:
            print("   -", e)
        bad += bool(errs)
    shutil.rmtree(work, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
