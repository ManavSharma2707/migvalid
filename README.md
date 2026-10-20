# Legacy-to-Modern Data Migration Validator

A mainframe course project that proves whether a data migration is correct. It
compares a **legacy source extract** with the **migrated target extract**,
finds every missing, extra, changed and duplicate record, and issues an
automatic **approve / warn / reject / abort** decision.

The validation logic is written in the classic mainframe stack
(**JCL + DFSORT/ICETOOL + COBOL + REXX**, with DB2 and VSAM for audit data) and
is driven from a modern **Python + Streamlit** front end through the Zowe CLI.

> **Status:** the full pipeline has been verified in a **local simulation** (see
> [Testing](#testing)). Running it on a real z/OS system (JCL, DFSORT/ICETOOL,
> GDG, VSAM, DB2) is the remaining step and is listed under
> [What is and is not verified](#what-is-and-is-not-verified).

---

## Table of contents

1. [The problem](#the-problem)
2. [How it works](#how-it-works)
3. [Decision codes](#decision-codes)
4. [Project layout](#project-layout)
5. [Test scenarios](#test-scenarios)
6. [Quick start (local simulation)](#quick-start-local-simulation)
7. [The Streamlit UI](#the-streamlit-ui)
8. [Running on a real mainframe](#running-on-a-real-mainframe)
9. [Testing](#testing)
10. [What is and is not verified](#what-is-and-is-not-verified)
11. [Design notes](#design-notes)

---

## The problem

When data moves from an old system to a new one, records can be lost,
duplicated, or silently altered. Eyeballing millions of rows is not an option.
This project automates the check: given a source extract and a target extract,
it reports exactly what differs and decides whether the migration may proceed.

## How it works

```
SRC.EXTRACT --DFSORT (dedupe)--> SRC.DEDUP --+
TGT.EXTRACT --DFSORT (sort)----> TGT.SORTED -+--COBOL match-merge--> RECON.EXCEPT + CTRL.OUT
ICETOOL counts (raw / dedup / target) --------------------------------+
   REXX : dedupe + sort exceptions, cross-check counts, decide RC 0/4/8/12
          -> RECON.EXCSORT, REPORT, RESULT, CTLREC, SQL
   DB2  : INSERT batch log + exceptions (MIG_BATCH_LOG, MIG_EXCEPTION)
   VSAM : control record -> MIG.CTRL.KSDS
   JCL  : IF RC <= 4 -> GATE.APPROVED(+1)   ELSE -> GATE.REJECTED(+1)
```

| Stage | Technology | Job |
|---|---|---|
| Sort / dedupe | DFSORT | Sort both extracts by key; remove duplicate source keys |
| Control counts | ICETOOL | Count raw source, deduped source and target rows |
| Match-merge | COBOL (`MIGMATCH`) | Walk both sorted files; classify each key as matched, changed, missing or extra |
| Decision and report | REXX (`MIGREXX`) | Cross-check the counts, apply the decision rules, build the report |
| Audit | DB2 + VSAM | Store the batch log, exceptions and a control record |
| Gate | JCL `IF` | Route the batch to an APPROVED or REJECTED generation dataset |
| Orchestration | Python + Zowe CLI | Generate data, deploy, submit the job, download results, verify |
| Review | Streamlit | Browse the results |

**Key** = `CUST-ID` + `ACCT-NO` (18 bytes, columns 1-18) in both files.
**Layouts:** source records are 80 bytes with an unsigned `9(9)V99` balance;
target records are 100 bytes with a text balance (`1234.56`) and an ISO date
(`YYYY-MM-DD`). The COBOL program normalizes both before comparing.

## Decision codes

| RC | Decision | Meaning |
|---|---|---|
| **0** | APPROVED | Source and target match exactly |
| **4** | WARNING | Data is correct, but the source contained duplicate keys |
| **8** | REJECTED | Records missing from the target, extra in the target, or with changed values |
| **12** | ABORTED | The controls disagree or the input is invalid (for example a duplicate key in the **target**, which makes a match unreliable) |

## Project layout

```
mainframe/
  jcl/     ALLOC, SETUP, DB2DDL, DB2LOAD, COMPILE, MIGVALID (main job), DB2QRY
  cobol/   MIGMATCH.cbl     match-merge of source vs target
  rexx/    MIGREXX.rexx     dedupe/sort exceptions, cross-checks, decision, report, SQL
python/
  app.py             Streamlit UI
  gen_data.py        test-data generator (4 scenarios) with an answer key
  validator_core.py  independent Python implementation of the validator (the "oracle")
  render.py          fills the @TOKENS@ in the JCL/COBOL/REXX templates and lints them
  deploy.py          allocates datasets, uploads members, compiles (via Zowe CLI)
  run_batch.py       uploads data, submits MIGVALID, downloads and verifies results
  mf_client.py       thin wrapper around the Zowe CLI
  config.example.json  settings template (copy to config.json)
tests/
  fake_zowe.py       a stand-in for the Zowe CLI that runs the COBOL locally
  test_python.py, test_mainframe_logic.py, test_end_to_end.py
GUIDE.md             original step-by-step build guide for the college mainframe
```

`build/`, `runs/` and `data/` are generated and are git-ignored.

## Test scenarios

`gen_data.py` creates four deterministic datasets, each with an answer key.

| Scenario | What it contains | Expected |
|---|---|---|
| `seeded` | 1,020 source rows incl. 20 duplicates; target has 10 missing, 15 changed, 5 extra | **REJECTED**, RC 8 |
| `clean` | 1,000 identical rows | **APPROVED**, RC 0 |
| `dups` | 20 duplicate source rows, otherwise identical | **WARNING**, RC 4 |
| `dup_target` | duplicate keys in the target | **ABORTED**, RC 12 |

Expected counts for `seeded`: source raw 1,020, duplicates 20, source unique
1,000, target 995, matched 975, mismatched 15, missing 10, extra 5.

## Quick start (local simulation)

This runs everything on your own machine, **without a mainframe**. A fake
`zowe` script (`tests/fake_zowe.py`) replaces the real Zowe CLI and runs your
real COBOL through GnuCOBOL.

**Requirements:** Linux or WSL (on Windows run `wsl --install` and use Ubuntu),
Python 3.10+, GnuCOBOL, Regina REXX.

```bash
sudo apt update && sudo apt install -y gnucobol regina-rexx python3-pip python3-venv
python3 -m venv .venv && . .venv/bin/activate
pip install -r python/requirements.txt

# 1. Automated tests
python tests/test_python.py
python tests/test_mainframe_logic.py
python tests/test_end_to_end.py

# 2. Build the fake mainframe
mkdir -p /tmp/mf/store /tmp/mf/bin
cobc -x -o /tmp/mf/migmatch mainframe/cobol/MIGMATCH.cbl
printf '#!/bin/sh\nexec python3 %s/tests/fake_zowe.py "$@"\n' "$PWD" > /tmp/mf/bin/zowe
chmod +x /tmp/mf/bin/zowe
export PATH=/tmp/mf/bin:$PATH
export FAKE_MF_STORE=/tmp/mf/store FAKE_MF_HLQ=Z12345 FAKE_MF_COBOL=/tmp/mf/migmatch
which zowe          # must print /tmp/mf/bin/zowe

# 3. Deploy and run the four scenarios
cd python
sed 's/ZZZZZ99/Z12345/' config.example.json > config.json
python deploy.py all
python run_batch.py --scenario seeded       # REJECTED, RC 8
python run_batch.py --scenario clean        # APPROVED, RC 0
python run_batch.py --scenario dups         # WARNING,  RC 4
python run_batch.py --scenario dup_target   # ABORTED,  RC 12
```

Batch ids are timestamped to the second, so wait about a second between runs.
Each run ends with *"Mainframe result == Python reference result (verified)"*.

> **Safety:** make sure `which zowe` prints the fake path before running
> `deploy.py` or `run_batch.py`, otherwise they would talk to a real system.
> `config.json` is git-ignored; never commit real credentials.

## The Streamlit UI

```bash
cd python
streamlit run app.py        # opens http://localhost:8501
```

In the sidebar choose **Data source**:

- **Mainframe runs** - pick a saved batch from `runs/`.
- **Offline demo** - computes a scenario with the Python reference; needs no
  mainframe at all, handy for a quick demo.

| Tab | Shows |
|---|---|
| Overview | Decision, return code and headline counts |
| Missing in target | Source records that never arrived |
| Extra in target | Target records with no source |
| Changed values | Records present in both with differing fields |
| Source duplicates | Repeated keys in the source |
| Verification | Mainframe result compared against the independent Python result |
| Report & logs | The REXX report and job logs |
| History | All batches run so far |

## Running on a real mainframe

Not part of the simulation. On a z/OS system with the Zowe CLI and a z/OSMF
profile:

1. Copy `python/config.example.json` to `python/config.json` and set your own
   high-level qualifier, DB2 subsystem, load libraries, DSNTEP2 plan and COBOL
   compile procedure (ask your instructor for these).
2. Run `python deploy.py all`, then `python run_batch.py --scenario seeded`.

[GUIDE.md](GUIDE.md) has the full step-by-step instructions, a troubleshooting
table and a map of which course topic each part covers. Everything runs under
your own userid (`YOURID.MIG.*`); nothing public is altered.

## Testing

| Suite | What it checks |
|---|---|
| `tests/test_python.py` | Data generator (determinism, answer key, seeded counts), template rendering and linting, the UI in offline mode |
| `tests/test_mainframe_logic.py` | Compiles the real COBOL and runs 9 cases against the Python reference: `seeded`, `dups`, `clean`, `dup_target`, plus edge cases (bad format, empty target, empty source, both valid, interleaved keys) |
| `tests/test_end_to_end.py` | `deploy all` plus all four `run_batch` scenarios through the fake Zowe |

All three suites pass.

## What is and is not verified

**Verified locally**

- The COBOL match-merge logic (`MIGMATCH`), including edge cases
- The REXX decision logic and the 0 / 4 / 8 / 12 return codes
- The Python orchestration: data generation, templating, deploy and run scripts
- The Streamlit UI (all tabs render for all four scenarios)
- Agreement between the mainframe-side result and an independent Python oracle

**Not yet verified (needs a real z/OS system)**

- Real JCL acceptance by JES
- Real DFSORT and ICETOOL behavior
- GDG (generation data groups)
- VSAM
- DB2 (the DB2 jobs are uploaded in the simulation but never executed)
- Real Zowe / z/OSMF authentication and job handling

## Design notes

- DB2 is used only for tables and the audit log, through DSNTEP2, with no BIND
  and no embedded SQL.
- COBOL reads the sorted **target extract file** rather than a DB2 cursor,
  because a cursor would need a BIND. The same rows are also loaded into the
  DB2 table `CUSTOMER_NEW`.
- A duplicate key in the **target** aborts the run (RC 12) because the match is
  no longer trustworthy, while duplicates in the **source** are removed
  upstream and only raise a warning (RC 4).
- Seeded defects: 20 duplicates + 10 missing + 15 changed + 5 extra. The
  exception report has 30 rows because the duplicates are removed earlier by
  DFSORT.
- An independent Python implementation (`validator_core.py`) acts as an oracle
  so the mainframe logic is checked against a second implementation, not
  against itself.

## License

Course project. Add a license here if you plan to share or reuse the code.
