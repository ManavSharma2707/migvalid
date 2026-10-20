"""
test_end_to_end.py - drives deploy.py and run_batch.py through a fake
`zowe` command that executes the real COBOL + REXX.   python tests/test_end_to_end.py
"""
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "python"


def main() -> int:
    if not (shutil.which("cobc") and shutil.which("regina")):
        print("cobc/regina missing - skipped")
        return 0
    tmp = Path(tempfile.mkdtemp())
    store = tmp / "store"
    store.mkdir()
    bindir = tmp / "bin"
    bindir.mkdir()
    exe = tmp / "migmatch"
    subprocess.run(["cobc", "-x", "-o", str(exe),
                    str(ROOT / "mainframe/cobol/MIGMATCH.cbl")],
                   check=True, capture_output=True)
    z = bindir / "zowe"
    z.write_text(f'#!/bin/sh\nexec {sys.executable} '
                 f'{ROOT / "tests/fake_zowe.py"} "$@"\n')
    z.chmod(z.stat().st_mode | stat.S_IEXEC)
    cfg = json.loads((PY / "config.example.json").read_text())
    cfg["hlq"] = "Z12345"
    cfgp = tmp / "config.json"
    cfgp.write_text(json.dumps(cfg))
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}",
               FAKE_MF_STORE=str(store), FAKE_MF_HLQ="Z12345",
               FAKE_MF_COBOL=str(exe))
    bad = 0

    def run(args):
        return subprocess.run([sys.executable, *args], env=env,
                              capture_output=True, text=True, cwd=PY)

    p = run(["deploy.py", "all", "--config", str(cfgp)])
    ok = p.returncode == 0 and (store / "Z12345.MIG.COBOL_MIGMATCH").exists() \
        and (store / "Z12345.MIG.REXX_MIGREXX").exists() \
        and (store / "Z12345.MIG.JCL_MIGVALID").exists()
    print("deploy all          ", "PASS" if ok else "FAIL")
    if not ok:
        print(p.stdout, p.stderr)
        bad += 1

    expect = {"seeded": (8, "REJECTED"), "dups": (4, "WARNING"),
              "clean": (0, "APPROVED"), "dup_target": (12, "ABORTED")}
    for sc, (rc, dec) in expect.items():
        p = run(["run_batch.py", "--scenario", sc, "--config", str(cfgp)])
        good = p.returncode == 0 and f"DECISION    {dec}" in p.stdout \
            and "verified" in p.stdout
        print(f"run_batch {sc:11s}", "PASS" if good else "FAIL")
        if not good:
            print(p.stdout, p.stderr)
            bad += 1
    # clean up the runs created by the test
    for r in (ROOT / "runs").glob("B2*"):
        shutil.rmtree(r, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
