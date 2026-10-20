"""
app.py - Streamlit dashboard for the Migration Validator.

    streamlit run python/app.py

Two modes (sidebar):
  * Mainframe runs  - shows the files downloaded by run_batch.py
                      (the real RESULT / EXCSORT / REPORT datasets)
  * Offline demo    - runs the Python reference validator on the generated
                      test data, so you can use the UI without a mainframe
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gen_data                      # noqa: E402
import validator_core as vc          # noqa: E402

ROOT = HERE.parent
RUNS = ROOT / "runs"
DATA = ROOT / "data"

COLORS = {"APPROVED": ("#1b873f", "SAFE TO CUT OVER"),
          "WARNING": ("#b7791f", "SAFE TO CUT OVER - DUPLICATES WERE REMOVED"),
          "REJECTED": ("#c53030", "DO NOT CUT OVER"),
          "ABORTED": ("#6b46c1", "HOLD - CONTROLS DISAGREE OR INPUT INVALID")}

st.set_page_config(page_title="Migration Validator", page_icon=":mag:",
                   layout="wide")


# ------------------------------------------------------------- loading
def list_runs() -> list[Path]:
    if not RUNS.exists():
        return []
    return sorted((p for p in RUNS.iterdir()
                   if p.is_dir() and (p / "result.txt").exists()),
                  key=lambda p: p.name, reverse=True)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") \
        if path.exists() else ""


def load_mainframe_run(d: Path) -> dict:
    src = vc.read_lines(str(d / "src_extract.txt")) \
        if (d / "src_extract.txt").exists() else []
    tgt = vc.read_lines(str(d / "tgt_extract.txt")) \
        if (d / "tgt_extract.txt").exists() else []
    return {
        "origin": "mainframe", "id": d.name,
        "summary": vc.parse_result(read(d / "result.txt")),
        "exc": vc.parse_excsort(read(d / "exceptions.txt")),
        "report": read(d / "report.txt"),
        "spool": read(d / "spool.txt"),
        "src": src, "tgt": tgt,
        "expected": json.loads(read(d / "expected.json") or "{}"),
        "meta": json.loads(read(d / "meta.json") or "{}"),
    }


def load_offline(scenario: str) -> dict:
    d = DATA / scenario
    if not (d / "src_extract.txt").exists():
        gen_data.write_scenario(scenario, DATA)
    src = vc.read_lines(str(d / "src_extract.txt"))
    tgt = vc.read_lines(str(d / "tgt_extract.txt"))
    res = vc.reconcile(src, tgt)
    summary = vc.result_to_dict(res)
    summary["BATCH_ID"] = f"OFFLINE-{scenario}"
    summary["REASON"] = res.reason
    return {"origin": "offline", "id": summary["BATCH_ID"],
            "summary": summary, "exc": res.exceptions, "report": "",
            "spool": "", "src": src, "tgt": tgt,
            "expected": json.loads(read(d / "expected.json") or "{}"),
            "meta": {}}


def exc_frame(exc: list[vc.Exception_]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"Type": e.err_type, "Customer": e.cust_id, "Account": e.acct_no,
          "Field": e.field, "Source value": e.src_val,
          "Target value": e.tgt_val} for e in exc],
        columns=["Type", "Customer", "Account", "Field", "Source value",
                 "Target value"])


def num(summary: dict, key: str) -> int:
    try:
        return int(str(summary.get(key, "0")).strip())
    except ValueError:
        return 0


# ----------------------------------------------------------- sidebar
st.sidebar.title("Migration Validator")
runs = list_runs()
mode = st.sidebar.radio("Data source",
                        ["Mainframe runs", "Offline demo"],
                        index=0 if runs else 1)

view = None
if mode == "Mainframe runs":
    if not runs:
        st.sidebar.info("No mainframe run saved yet. Use the form below "
                        "or run `python run_batch.py`.")
    else:
        pick = st.sidebar.selectbox("Batch", [r.name for r in runs])
        view = load_mainframe_run(RUNS / pick)
else:
    sc = st.sidebar.selectbox("Scenario", gen_data.SCENARIOS)
    view = load_offline(sc)
    st.sidebar.caption("Result computed by the Python reference "
                       "implementation - NOT by the mainframe.")

with st.sidebar.expander("Run on the mainframe"):
    sc_run = st.selectbox("Test scenario", gen_data.SCENARIOS, key="sc_run")
    load_db2 = st.checkbox("Reload DB2 table CUSTOMER_NEW first", value=False)
    if st.button("Generate data + run MIGVALID"):
        if not (HERE / "config.json").exists():
            st.error("python/config.json is missing - copy "
                     "config.example.json and fill it in.")
        else:
            cmd = [sys.executable, str(HERE / "run_batch.py"),
                   "--scenario", sc_run]
            if load_db2:
                cmd.append("--load-db2")
            with st.spinner("Submitting the job and waiting for output..."):
                p = subprocess.run(cmd, capture_output=True, text=True)
            st.code((p.stdout or "") + (p.stderr or ""), language="text")
            if p.returncode == 0:
                st.success("Done - pick the new batch in 'Mainframe runs'.")
            else:
                st.error(f"run_batch.py ended with exit code {p.returncode}")

# -------------------------------------------------------------- main
st.title("Legacy-to-Modern Data Migration Validator")
st.caption("Pre-cutover approval gate: DFSORT + COBOL + REXX + JCL + DB2")

if view is None:
    st.info("Nothing to show yet. Choose **Offline demo** in the sidebar to "
            "see the dashboard with generated data.")
    st.stop()

S = view["summary"]
decision = S.get("DECISION", "UNKNOWN")
colour, message = COLORS.get(decision, ("#4a5568", "UNKNOWN RESULT"))
origin = "real mainframe output" if view["origin"] == "mainframe" \
    else "Python reference implementation (offline)"
st.markdown(
    f"<div style='border-left:8px solid {colour};padding:12px 18px;"
    f"background:{colour}22;border-radius:6px'>"
    f"<span style='font-size:1.6rem;font-weight:700;color:{colour}'>"
    f"{decision}</span> &nbsp; RC {S.get('RC', '?')} &nbsp;-&nbsp; "
    f"<b>{message}</b><br><span style='opacity:.75'>Batch {view['id']} "
    f"&middot; source: {origin}</span></div>", unsafe_allow_html=True)
if S.get("REASON"):
    st.warning(f"Reason: {S['REASON']}")
st.write("")

cols = st.columns(8)
labels = [("Raw source", "SRC_RAW"), ("Duplicates", "DUPS"),
          ("Unique source", "SRC_UNIQUE"), ("Target rows", "TGT_CNT"),
          ("Matched", "MATCHED"), ("Changed", "MISMATCH"),
          ("Missing", "MISSING"), ("Extra", "EXTRA")]
for c, (lab, key) in zip(cols, labels):
    c.metric(lab, f"{num(S, key):,}")

tab_over, tab_miss, tab_extra, tab_chg, tab_dup, tab_ver, tab_rep, tab_hist = \
    st.tabs(["Overview", "Missing in target", "Extra in target",
             "Changed values", "Source duplicates", "Verification",
             "Report & logs", "History"])

df = exc_frame(view["exc"])

with tab_over:
    left, right = st.columns([3, 2])
    with left:
        st.subheader("Where did every record go?")
        chart = pd.DataFrame(
            {"records": [num(S, "MATCHED"), num(S, "MISMATCH"),
                         num(S, "MISSING"), num(S, "EXTRA")]},
            index=["Matched", "Changed", "Missing in target",
                   "Extra in target"])
        st.bar_chart(chart)
    with right:
        st.subheader("Reconciliation")
        m, c, s_, e, u, t = (num(S, k) for k in
                             ("MATCHED", "MISMATCH", "MISSING", "EXTRA",
                              "SRC_UNIQUE", "TGT_CNT"))
        st.write(f"**Source side:** matched {m:,} + changed {c:,} + "
                 f"missing {s_:,} = {m + c + s_:,} "
                 f"{'OK' if m + c + s_ == u else 'MISMATCH'} "
                 f"(unique source {u:,})")
        st.write(f"**Target side:** matched {m:,} + changed {c:,} + "
                 f"extra {e:,} = {m + c + e:,} "
                 f"{'OK' if m + c + e == t else 'MISMATCH'} "
                 f"(target rows {t:,})")
        st.write(f"**Duplicates removed by DFSORT:** {num(S, 'DUPS'):,} "
                 f"({num(S, 'SRC_RAW'):,} raw -> {u:,} unique)")
        try:
            diff = float(S.get("TGT_BAL_TOT", 0)) - float(S.get("SRC_BAL_TOT", 0))
            st.write(f"**Balance control totals:** source "
                     f"{float(S.get('SRC_BAL_TOT', 0)):,.2f} / target "
                     f"{float(S.get('TGT_BAL_TOT', 0)):,.2f} "
                     f"(difference {diff:,.2f})")
        except ValueError:
            pass
    if not df.empty:
        st.download_button("Download all exceptions (CSV)",
                           df.to_csv(index=False), "exceptions.csv",
                           "text/csv")

with tab_miss:
    st.caption("Present in the legacy extract, absent from the target.")
    d = df[df["Type"] == "MISSING"].copy()
    if d.empty:
        st.success("No missing records.")
    else:
        parts = d["Source value"].str.rsplit(" ", n=1, expand=True)
        d["Customer name"] = parts[0]
        d["Balance"] = parts[1] if parts.shape[1] > 1 else ""
        st.dataframe(d[["Customer", "Account", "Customer name", "Balance"]],
                     hide_index=True, width='stretch')

with tab_extra:
    st.caption("Present in the target, but not in the legacy extract.")
    d = df[df["Type"] == "EXTRA"].copy()
    if d.empty:
        st.success("No extra records.")
    else:
        parts = d["Target value"].str.rsplit(" ", n=1, expand=True)
        d["Customer name"] = parts[0]
        d["Balance"] = parts[1] if parts.shape[1] > 1 else ""
        st.dataframe(d[["Customer", "Account", "Customer name", "Balance"]],
                     hide_index=True, width='stretch')

with tab_chg:
    st.caption("Same customer + account on both sides, but a value differs "
               "(one row per differing field).")
    d = df[df["Type"] == "MISMATCH"]
    if d.empty:
        st.success("No changed values.")
    else:
        fields = sorted(d["Field"].unique())
        sel = st.multiselect("Field", fields, default=fields)
        shown = d[d["Field"].isin(sel)]
        st.bar_chart(d["Field"].value_counts())
        st.dataframe(shown[["Customer", "Account", "Field", "Source value",
                            "Target value"]],
                     hide_index=True, width='stretch')

with tab_dup:
    st.caption("Duplicate keys in the raw source extract. DFSORT keeps the "
               "first copy of each key and drops the rest.")
    dups = vc.find_duplicates(view["src"]) if view["src"] else []
    if not view["src"]:
        st.info("The source extract is not available for this batch.")
    elif not dups:
        st.success("No duplicate keys in the source.")
    else:
        dd = pd.DataFrame(dups).rename(columns={
            "cust_id": "Customer", "acct_no": "Account", "copies": "Copies",
            "conflicting": "Copies differ?", "name": "Name"})
        st.write(f"**{len(dd)} duplicated keys** "
                 f"({int(dd['Copies'].sum() - len(dd))} extra copies).")
        if dd["Copies differ?"].any():
            st.error("Some duplicate copies carry DIFFERENT data. DFSORT kept "
                     "the first one - review these by hand.")
        else:
            st.info("All duplicate copies are identical, so dropping them "
                    "loses no information.")
        st.dataframe(dd, hide_index=True, width='stretch')

with tab_ver:
    st.subheader("Independent check")
    if view["src"] and view["tgt"]:
        oracle = vc.reconcile(view["src"], view["tgt"])
        if view["origin"] == "mainframe":
            diffs = vc.compare_to_oracle(S, view["exc"], oracle)
            if diffs:
                st.error("The mainframe result differs from the Python "
                         "reference implementation:")
                for x in diffs:
                    st.write("- " + x)
            else:
                st.success("The mainframe result is identical to the result "
                           "of the independent Python implementation "
                           "(counts, decision and every exception row).")
        else:
            st.info("Offline mode: this IS the Python reference result.")
    else:
        st.info("Source/target extracts are not stored for this batch.")
    exp = view["expected"]
    if exp:
        st.subheader("Seeded-defect answer key (expected.json)")
        keys = ["raw", "dups", "src_unique", "tgt_cnt", "matched",
                "mismatch", "missing", "extra", "rc", "decision"]
        mapping = {"raw": "SRC_RAW", "dups": "DUPS", "src_unique": "SRC_UNIQUE",
                   "tgt_cnt": "TGT_CNT", "matched": "MATCHED",
                   "mismatch": "MISMATCH", "missing": "MISSING",
                   "extra": "EXTRA", "rc": "RC", "decision": "DECISION"}
        rows = []
        for k in keys:
            if k in exp:
                got = str(S.get(mapping[k], "")).strip()
                rows.append({"Item": k, "Expected": str(exp[k]),
                             "Actual": got,
                             "OK": "yes" if got == str(exp[k]) else "NO"})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True,
                         width='stretch')
    if view["meta"]:
        st.subheader("Job")
        st.json(view["meta"])

with tab_rep:
    if view["report"]:
        st.subheader("REXX report (dataset RECON.REPORT)")
        st.code(view["report"], language="text")
    else:
        st.info("The REXX report exists only for real mainframe runs.")
    if view["spool"]:
        with st.expander("Complete job output (JES spool)"):
            st.code(view["spool"], language="text")

with tab_hist:
    allruns = [load_mainframe_run(r) for r in list_runs()]
    if not allruns:
        st.info("History appears after the first mainframe run.")
    else:
        rows = []
        for r in allruns:
            s = r["summary"]
            rows.append({"Batch": r["id"], "Decision": s.get("DECISION"),
                         "RC": num(s, "RC"), "Raw": num(s, "SRC_RAW"),
                         "Dups": num(s, "DUPS"),
                         "Matched": num(s, "MATCHED"),
                         "Changed": num(s, "MISMATCH"),
                         "Missing": num(s, "MISSING"),
                         "Extra": num(s, "EXTRA")})
        hist = pd.DataFrame(rows)
        st.dataframe(hist, hide_index=True, width='stretch')
        trend = hist.sort_values("Batch").set_index("Batch")[
            ["Changed", "Missing", "Extra"]]
        st.subheader("Defects per batch (rehearsal trend)")
        st.line_chart(trend)
        st.caption("The same history is also stored in DB2 tables "
                   "MIG_BATCH_LOG and MIG_EXCEPTION (run job DB2QRY).")
