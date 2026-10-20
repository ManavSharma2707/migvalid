"""
run_batch.py - runs one complete validation on the mainframe and saves
everything into runs/<BATCH_ID>/ so the Streamlit app can display it.

    python run_batch.py --scenario seeded                 (expected RC 8)
    python run_batch.py --scenario clean --load-db2       (expected RC 0)

Steps: generate data -> upload source/target extracts -> (optional) reload
the DB2 target table -> submit MIGVALID -> wait -> download results ->
compare with expected.json and with the Python reference implementation.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import gen_data
import render
import validator_core as vc
from mf_client import MFError, Zowe, cc_value

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run(scenario: str, load_db2: bool, cfg: dict, log=print) -> Path:
    hlq = cfg["hlq"]
    zowe = Zowe(cfg.get("zosmf_profile", ""), log=log)
    data_dir = gen_data.write_scenario(scenario, ROOT / "data")
    log(f"test data: {data_dir}")

    zowe.upload(data_dir / "src_extract.txt", f"{hlq}.MIG.SRC.EXTRACT")
    zowe.upload(data_dir / "tgt_extract.txt", f"{hlq}.MIG.TGT.EXTRACT")

    if load_db2:
        zowe.upload(data_dir / "customer_new_load.sql",
                    f"{hlq}.MIG.SQL.CUSTLOAD")
        jid = zowe.submit_dataset(f"{hlq}.MIG.JCL(DB2LOAD)")
        rc = zowe.wait(jid, timeout=900)
        log(f"DB2LOAD {jid}: {rc}")
        if cc_value(rc) not in (0, 4):
            raise MFError(f"DB2LOAD ended {rc}\n{zowe.spool(jid)[-4000:]}")

    jid = zowe.submit_dataset(f"{hlq}.MIG.JCL(MIGVALID)")
    rc = zowe.wait(jid, timeout=900)
    log(f"MIGVALID {jid}: {rc}")
    spool = zowe.spool(jid)
    if cc_value(rc) is None:
        raise MFError(f"MIGVALID failed with {rc}.\n{spool[-6000:]}")

    tmp = ROOT / "runs" / f"_tmp_{jid}"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    zowe.download(f"{hlq}.MIG.RECON.RESULT", tmp / "result.txt")
    zowe.download(f"{hlq}.MIG.RECON.REPORT", tmp / "report.txt")
    try:
        zowe.download(f"{hlq}.MIG.RECON.EXCSORT", tmp / "exceptions.txt")
    except MFError:                       # an empty dataset (clean batch)
        (tmp / "exceptions.txt").write_text("")
    (tmp / "spool.txt").write_text(spool, encoding="utf-8", errors="replace")
    for name in ("src_extract.txt", "tgt_extract.txt", "expected.json"):
        shutil.copy(data_dir / name, tmp / name)

    result = vc.parse_result((tmp / "result.txt").read_text())
    batch = result.get("BATCH_ID") or jid
    final = ROOT / "runs" / batch
    shutil.rmtree(final, ignore_errors=True)
    tmp.rename(final)
    (final / "meta.json").write_text(json.dumps(
        {"jobid": jid, "job_retcode": rc, "scenario": scenario,
         "db2_reloaded": load_db2}, indent=2))
    return final


def verify(run_dir: Path) -> list[str]:
    result = vc.parse_result((run_dir / "result.txt").read_text())
    exc = vc.parse_excsort((run_dir / "exceptions.txt").read_text())
    src = vc.read_lines(str(run_dir / "src_extract.txt"))
    tgt = vc.read_lines(str(run_dir / "tgt_extract.txt"))
    oracle = vc.reconcile(src, tgt)
    return vc.compare_to_oracle(result, exc, oracle)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scenario", choices=gen_data.SCENARIOS, default="seeded")
    ap.add_argument("--load-db2", action="store_true",
                    help="reload table CUSTOMER_NEW first (needed once per "
                         "scenario if you want DB2 to hold the same target)")
    ap.add_argument("--config", default=str(HERE / "config.json"))
    a = ap.parse_args()
    try:
        cfg = render.load_config(Path(a.config))
        d = run(a.scenario, a.load_db2, cfg)
    except (render.ConfigError, MFError) as e:
        print("\nERROR:", e)
        return 1
    result = vc.parse_result((d / "result.txt").read_text())
    print("\n=== RESULT ===")
    for k in ("BATCH_ID", "DECISION", "RC", "SRC_RAW", "DUPS", "SRC_UNIQUE",
              "TGT_CNT", "MATCHED", "MISMATCH", "MISSING", "EXTRA"):
        print(f"{k:11s} {result.get(k)}")
    diffs = verify(d)
    if diffs:
        print("\nDIFFERENCES vs the Python reference implementation:")
        for x in diffs:
            print("  -", x)
        return 3
    print("\nMainframe result == Python reference result  (verified)")
    print(f"saved in {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
