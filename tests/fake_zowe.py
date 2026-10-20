"""
fake_zowe.py - a stand-in for the Zowe CLI used ONLY by test_end_to_end.py.
Datasets live in a folder ($FAKE_MF_STORE); submitting MIGVALID runs the
real COBOL (GnuCOBOL binary $FAKE_MF_COBOL) and the real REXX (Regina)
behind it, so deploy.py / run_batch.py / mf_client.py can be tested without
a mainframe.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STORE = Path(os.environ["FAKE_MF_STORE"])
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import test_mainframe_logic as t          # noqa: E402


def key(dsn: str) -> Path:
    return STORE / dsn.replace("(", "_").replace(")", "")


def out(data=None, ok=True, text=None):
    if text is not None:
        sys.stdout.write(text)
    else:
        print(json.dumps({"success": ok, "exitCode": 0 if ok else 1,
                          "data": data or {}}))
    sys.exit(0 if ok else 1)


def fail(msg):
    sys.stderr.write(msg + "\n")
    sys.exit(1)


def run_migvalid() -> int:
    hlq = os.environ["FAKE_MF_HLQ"]
    g = lambda n: key(f"{hlq}.MIG.{n}")                   # noqa: E731
    src = [x for x in g("SRC.EXTRACT").read_text().splitlines() if x.strip()]
    tgt = [x for x in g("TGT.EXTRACT").read_text().splitlines() if x.strip()]
    w = Path(tempfile.mkdtemp())
    dedup = t.emulate_sort(src, 80, True)
    tsort = t.emulate_sort(tgt, 100, False)
    t.write_fixed(w / "SRCIN.bin", dedup, 80)
    t.write_fixed(w / "TGTIN.bin", tsort, 100)
    for dd, lab, n in (("CNTRAW", "RAW=", len(src)),
                       ("CNTDED", "DEDUP=", len(dedup)),
                       ("CNTTGT", "TGT=", len(tsort))):
        (w / dd).write_text(f"{lab}{n:010d}".ljust(80) + "\n")
    env = dict(os.environ, DD_SRCIN=str(w / "SRCIN.bin"),
               DD_TGTIN=str(w / "TGTIN.bin"), DD_EXCOUT=str(w / "EXCOUT.bin"),
               DD_CTLOUT=str(w / "CTLOUT.bin"))
    subprocess.run([os.environ["FAKE_MF_COBOL"]], env=env, capture_output=True)
    (w / "EXCIN").write_text("".join(
        x + "\n" for x in t.read_fixed(w / "EXCOUT.bin", 100)))
    (w / "CTLIN").write_text(t.read_fixed(w / "CTLOUT.bin", 120)[0] + "\n")
    rx = w / "x.rexx"
    t.build_rexx_test(rx)
    p = subprocess.run(["regina", str(rx)], env=dict(os.environ, MIGDIR=str(w)),
                       capture_output=True, text=True)
    for dd, name in (("RESULT", "RECON.RESULT"), ("REPORT", "RECON.REPORT"),
                     ("EXCSORT", "RECON.EXCSORT"), ("SQLOUT", "RECON.SQL")):
        shutil.copy(w / f"{dd}.out", g(name))
    return p.returncode


def main():
    a = sys.argv[1:]
    if a[:3] == ["zos-files", "upload", "file-to-data-set"]:
        shutil.copy(a[3], key(a[4]))
        out()
    if a[:3] == ["zos-files", "download", "data-set"]:
        p = key(a[3])
        if not p.exists():
            fail(f"data set not found: {a[3]}")
        dest = a[a.index("--file") + 1]
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(p, dest)
        out()
    if a[:3] in (["zos-jobs", "submit", "local-file"],
                 ["zos-jobs", "submit", "data-set"]):
        name = a[3]
        rc = 0
        if "(MIGVALID)" in name:
            rc = run_migvalid()
        (STORE / "_lastjob").write_text(f"CC {rc:04d}")
        out({"jobid": "JOB00001", "retcode": None, "status": "INPUT"})
    if a[:3] == ["zos-jobs", "view", "job-status-by-jobid"]:
        out({"jobid": a[3], "status": "OUTPUT",
             "retcode": (STORE / "_lastjob").read_text()})
    if a[:3] == ["zos-jobs", "view", "all-spool-content"]:
        out(text="FAKE SPOOL OUTPUT\n")
    fail("fake zowe: unsupported " + " ".join(a))


main()
