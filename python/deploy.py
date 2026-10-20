"""
deploy.py - one-time (and re-runnable) deployment of the project to YOUR
OWN userid on the mainframe, using the Zowe CLI.

    python deploy.py alloc      create the datasets (ALLOC job, run once)
    python deploy.py setup      define GDGs + control KSDS (SETUP job, run once)
    python deploy.py upload     upload JCL / COBOL / REXX members
    python deploy.py compile    compile + link-edit MIGMATCH
    python deploy.py all        alloc -> upload -> setup -> compile

Nothing outside "<your userid>.MIG.*" is ever created or changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import render
from mf_client import MFError, Zowe, cc_value

HERE = Path(__file__).resolve().parent


def require_cc(zowe: Zowe, jobid: str, name: str, ok=(0,)) -> None:
    rc = zowe.wait(jobid)
    print(f"  {name} ({jobid}) finished: {rc}")
    if cc_value(rc) not in ok:
        print("---- job output ----")
        print(zowe.spool(jobid)[-6000:])
        raise MFError(f"{name} ended with {rc}. See the output above.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("step", choices=["alloc", "setup", "upload", "compile",
                                     "all"])
    ap.add_argument("--config", default=str(HERE / "config.json"))
    a = ap.parse_args()

    try:
        cfg = render.load_config(Path(a.config))
    except render.ConfigError as e:
        print("CONFIG ERROR:", e)
        return 2
    problems = render.render(cfg)
    if problems:
        print("LINT PROBLEMS - fix these first:")
        for p in problems:
            print("  -", p)
        return 1

    hlq = cfg["hlq"]
    zowe = Zowe(cfg.get("zosmf_profile", ""))
    steps = ["alloc", "upload", "setup", "compile"] if a.step == "all" \
        else [a.step]
    try:
        for s in steps:
            print(f"== {s}")
            if s == "alloc":
                jid = zowe.submit_local(render.BUILD / "jcl" / "ALLOC.jcl")
                require_cc(zowe, jid, "ALLOC")
            elif s == "upload":
                for f in sorted((render.BUILD / "jcl").glob("*.jcl")):
                    zowe.upload(f, f"{hlq}.MIG.JCL({f.stem.upper()})")
                zowe.upload(render.BUILD / "cobol" / "MIGMATCH.cbl",
                            f"{hlq}.MIG.COBOL(MIGMATCH)")
                zowe.upload(render.BUILD / "rexx" / "MIGREXX.rexx",
                            f"{hlq}.MIG.REXX(MIGREXX)")
                print("  members uploaded")
            elif s == "setup":
                jid = zowe.submit_dataset(f"{hlq}.MIG.JCL(SETUP)")
                require_cc(zowe, jid, "SETUP")
            elif s == "compile":
                jid = zowe.submit_dataset(f"{hlq}.MIG.JCL(COMPILE)")
                require_cc(zowe, jid, "COMPILE", ok=(0, 4))
    except MFError as e:
        print("\nERROR:", e)
        return 1
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
