# Legacy-to-Modern Data Migration Validator - build guide (2 days)

Everything runs under **your own userid** (`YOURID.MIG.*`, your own DB2
tables). Nothing public is read for update, altered or created.
DB2 is used only for **tables + audit log** (through DSNTEP2) - no BIND,
no embedded SQL.

## 0. What is in this folder

| Path | What it is |
|---|---|
| `mainframe/jcl/*.jcl` | ALLOC, SETUP, DB2DDL, DB2LOAD, COMPILE, **MIGVALID** (main job), DB2QRY |
| `mainframe/cobol/MIGMATCH.cbl` | COBOL match-merge (source vs target) |
| `mainframe/rexx/MIGREXX.rexx` | REXX: dedupe/sort exceptions, cross-checks, decision, report, SQL |
| `python/config.example.json` | your settings -> copy to `config.json` |
| `python/render.py` | fills the `@TOKENS@` in the templates + lints them -> `build/` |
| `python/deploy.py` | creates datasets, uploads members, compiles (via Zowe CLI) |
| `python/gen_data.py` | creates the test data (4 scenarios) + answer key |
| `python/run_batch.py` | uploads data, runs MIGVALID, downloads results, verifies |
| `python/app.py` | Streamlit UI |
| `python/validator_core.py` | independent Python version of the validator (oracle) |
| `tests/` | automated tests (see section 9) |

### How the job works
```
SRC.EXTRACT --DFSORT(dedupe)--> SRC.DEDUP --+
TGT.EXTRACT --DFSORT(sort)----> TGT.SORTED -+--COBOL match-merge--> RECON.EXCEPT + CTRL.OUT
ICETOOL counts (raw / dedup / target) ------------------------------------+
   REXX: dedupe+sort exceptions, cross-check counts, decide RC 0/4/8/12
         -> RECON.EXCSORT, REPORT, RESULT, CTLREC, SQL
   DB2 : INSERT batch log + exceptions (MIG_BATCH_LOG, MIG_EXCEPTION)
   VSAM: control record -> MIG.CTRL.KSDS
   JCL : IF RC<=4 -> GATE.APPROVED(+1)  ELSE -> GATE.REJECTED(+1)
```
Return codes: **0** approved, **4** approved with warning (only duplicates),
**8** rejected (missing/extra/changed), **12** aborted (controls disagree or
input invalid, e.g. duplicate key in the target).

### Honest differences from the PPT (update the slides!)
1. COBOL reads the **target extract file** (sorted by DFSORT), not a DB2
   cursor - a DB2 cursor needs BIND, which you cannot do. The same target
   rows are also loaded into DB2 table `CUSTOMER_NEW`; DB2 also holds the
   audit tables. Slides 2, 3, 6, 9 and 14: say "target extract (also held in
   DB2 CUSTOMER_NEW)".
2. Key = CUST-ID + ACCT-NO (18 bytes, contiguous: columns 1-18) in both files.
3. Layouts: source 80 bytes, balance unsigned `9(9)V99`; target 100 bytes,
   balance as text `1234.56`, date `YYYY-MM-DD` (COBOL normalises both).
4. Extra datasets: `RECON.EXCSORT`, `RECON.RESULT`, `RECON.CTLREC`,
   `RECON.SQL`, `CTRL.OUT`, `CNT.*`, `SQL.CUSTLOAD`, `TGT.*`.
5. 50 seeded defects = 20 duplicates + 10 missing + 15 changed + 5 extra;
   the exception report has 30 rows (dups are removed earlier by DFSORT).

## 1. Ask your instructor (5 minutes - do this first)
Send these in one message, you need the answers on Day 1:
1. DB2 subsystem name (e.g. `DBCG`), the DB2 load library (`...SDSNLOAD`),
   the DSNTEP2 run library (`...RUNLIB.LOAD`) and the DSNTEP2 plan name
   (`DSNTEP12`...). Easiest: "Can you send me a sample DSNTEP2 job?"
2. Can my id `CREATE TABLE` / `CREATE INDEX` in my own schema? (If a database
   name is mandatory, tell me - I add `IN DATABASE name`.)
3. Name of the Enterprise COBOL compile procedure (usually `IGYWCL`) and its
   `LNGPRFX` if it needs one.
4. Job card values: account string, CLASS, MSGCLASS, disk UNIT (usually `SYSDA`).
5. Is my userid the high-level qualifier of my datasets? (yes in 99% of cases)

## 2. Day 1

### Step 1 - Python + Zowe CLI on your laptop (20 min)
```
python --version            # 3.10 or newer
cd migvalid/python
pip install -r requirements.txt
npm install -g @zowe/cli    # needs Node.js; skip if `zowe --version` already works
zowe --version
zowe zosmf check status     # must say "successfully connected"
```
The Zowe CLI uses the same `zowe.config.json` profile as Zowe Explorer.
If it asks for user/password, set them for this terminal only:
`set ZOWE_OPT_USER=YOURID` and `set ZOWE_OPT_PASSWORD=...` (Windows) or
`export ...` (Linux/Mac). **Done when** `zowe zosmf check status` works.

### Step 2 - config.json (10 min)
```
copy config.example.json config.json      (cp on Linux/Mac)
```
Edit `config.json`: `hlq` = your userid in CAPITALS (max 7 characters, because
job names are userid + 1 letter) and the values from section 1. Leave
`zosmf_profile` empty to use your default profile.
Then check the templates:
```
python render.py
```
**Done when** it prints `OK - rendered 9 files`. It refuses to continue on
overlong lines, forbidden characters, unknown tokens or a bad userid.
Open `build/jcl/MIGVALID.jcl` and look at it: every dataset must start with
your userid.

### Step 3 - create your datasets, upload everything, compile (30 min)
```
python deploy.py alloc      # job ALLOC:  libraries + 3 input datasets
python deploy.py upload     # JCL, COBOL and REXX members
python deploy.py setup      # job SETUP:  2 GDGs + control KSDS
python deploy.py compile    # job COMPILE: MIGMATCH -> YOURID.MIG.LOAD
```
(`python deploy.py all` does all four.) In **Zowe Explorer** refresh Data Sets
and filter `YOURID.MIG.*` - you should see ~10 datasets. Each job prints its
result; on a failure it prints the job output.
**Done when** all four say `finished: CC 0000` (COMPILE may say `CC 0004`).

*Prefer clicking? (no Zowe CLI)* In VS Code open `build/jcl/ALLOC.jcl`, use the
Command Palette -> "Zowe Explorer: Submit active text editor content as JCL"
(search "Zowe submit"), then drag/upload the files of `build/` into the
members `MIG.JCL`, `MIG.COBOL(MIGMATCH)`, `MIG.REXX(MIGREXX)` with Explorer's
right-click "Upload to data set".

### Step 4 - DB2 tables (30 min)
In Explorer open `YOURID.MIG.JCL(DB2DDL)` -> right-click -> **Submit Job**.
Open the output in the JOBS view (`DDL` step -> `SYSPRINT`) and check that all
CREATE statements say `SUCCESSFUL`. **Done when** 3 tables + 1 index exist.
(An `SQLCODE -551/-552/-567` = no authority -> ask your instructor, section 1.2.
`SQLCODE -601` = table already exists = fine on a second run.)

### Step 5 - first full run (45 min)
```
python run_batch.py --scenario seeded --load-db2
```
This generates the data, uploads it, loads DB2 `CUSTOMER_NEW`, submits
**MIGVALID**, waits, downloads the results into `runs/<BATCH>/` and compares
them with the independent Python implementation.
Expected output:
```
DECISION    REJECTED      RC 8
SRC_RAW 1020  DUPS 20  SRC_UNIQUE 1000  TGT_CNT 995
MATCHED 975   MISMATCH 15   MISSING 10   EXTRA 5
Mainframe result == Python reference result  (verified)
```
In Explorer's JOBS view open the job: steps CLEAN, DEDUP, SORTTGT, COUNTS,
MATCH, AUDIT, LOGKSDS, REJECT show `CC 0000`, REXXRUN shows `CC 0008`
(that is the designed REJECT). Open these datasets and take screenshots:
`MIG.CNT.RAW` (shows `RAW=0000001020`), `MIG.RECON.REPORT`,
`MIG.RECON.EXCSORT`, `MIG.GATE.REJECTED.G0001V00`.

### Step 6 - the UI (20 min)
```
cd python
streamlit run app.py        # or: python -m streamlit run app.py
```
Pick **Mainframe runs** -> your batch. Tabs: Overview, Missing, Extra, Changed
values, Source duplicates, Verification (compares with the Python oracle and
with `expected.json`), Report & logs, History. The sidebar can also run a
scenario by itself. No mainframe at hand? **Offline demo** shows the same UI.

### Step 7 - end of Day 1 check
`MIG_BATCH_LOG` has one row: submit `YOURID.MIG.JCL(DB2QRY)` and read the output.
If steps 1-7 work, the hard part is done.

## 3. Day 2

### Step 8 - the four test scenarios (60 min)
```
python run_batch.py --scenario dups       --load-db2    # RC 4  WARNING
python run_batch.py --scenario clean      --load-db2    # RC 0  APPROVED
python run_batch.py --scenario dup_target --load-db2    # RC 12 ABORTED
python run_batch.py --scenario seeded     --load-db2    # RC 8  REJECTED
```
Screenshot every job output and the UI for each. Run DB2QRY at the end: four
rows of history. In `MIG.GATE.APPROVED` / `MIG.GATE.REJECTED` you see one
generation per run (GDG fall-back = the previous generation stays available).
(`dup_target` loads 995 rows into DB2; the duplicate key exists only in the
extract file on purpose.)

### Step 9 - restart demonstration (30 min)
1. In Explorer edit `YOURID.MIG.REXX(MIGREXX)`: find the line `dups = raw - ded` (line 25) and change it
   to `dups = raw - dedx`, then save.
2. Submit `YOURID.MIG.JCL(MIGVALID)`. CLEAN..MATCH end `CC 0000`, **REXXRUN ends
   `CC 0016`**, AUDIT and LOGKSDS are skipped (IF RC < 16), and the gate takes the
   ELSE branch: a result nobody can read is never approved (fail-safe REJECT).
3. Fix the typo and save. Delete these 5 datasets in Explorer (the failed step
   left them behind): `MIG.RECON.EXCSORT`, `.REPORT`, `.RESULT`, `.CTLREC`, `.SQL`.
4. Edit the JOB card of `MIGVALID`: add `,RESTART=REXXRUN` after
   `NOTIFY=&SYSUID` (keep the comma at the end of the previous line), submit.
   Sorting and COBOL are **not** repeated; the job restarts at REXXRUN.
5. Screenshot both runs, then remove `RESTART=REXXRUN` again.
This covers "restartable steps, COND/IF checks, GDG fall-back".

### Step 10 - real-life extras you can mention (optional, 60+ min)
* **Control totals** are already in the report (source vs target balance sum).
* **Conflicting duplicates**: the UI flags duplicate keys whose copies differ
  (DFSORT keeps the first one). Try it: edit one duplicated line in
  `data/seeded/src_extract.txt`, change a balance, re-run.
* **Rehearsal trend**: run seeded several times, show the History chart.
* **Masking / alerts / scheduling** -> list as future enhancements (slide 14).

### Step 11 - report + demo (rest of Day 2)
Update the slides per section 0, add the screenshots, and rehearse this demo
(5 min): 1) show Explorer datasets  2) run seeded batch (or show finished
job)  3) point at REXXRUN `CC 0008` + REJECTED GDG  4) UI Overview/Missing/
Changed tabs  5) DB2QRY output  6) run `clean` -> APPROVED.

## 4. Troubleshooting (symptom -> cause -> fix)
| Symptom | Fix |
|---|---|
| `render.py` says config error | follow the message; hlq must be your userid |
| ALLOC: `JCL ERROR` / `IEF...` duplicate dataset | it was run before; delete the `YOURID.MIG.*` datasets in Explorer and rerun |
| SETUP: IDC3009 / volume | ask instructor for `VOLUMES(xxxxxx)`; add to the DEFINE CLUSTER in `mainframe/jcl/SETUP.jcl`, run `python render.py`, `python deploy.py upload`, submit SETUP |
| COMPILE: `IGYWCL` not found | use the proc name your instructor gave -> `cobol_proc` in config.json |
| COMPILE: `FUNCTION TRIM` / `TEST-NUMVAL` error | COBOL too old (needs Enterprise COBOL 4.2+) - tell me, I give a version without them |
| MATCH: S806 | `MIGMATCH` not in `MIG.LOAD` -> COMPILE failed |
| REXXRUN `CC 0016` + message `NO RAW= LINE` | ICETOOL count record looks different: open `MIG.CNT.RAW`; it must read `RAW=0000001020`. If it differs (spaces, other text) send me the content |
| REXXRUN message `MIGREXX FAILED AT LINE n` | open the job SYSTSPRT; line n is printed with the condition |
| REXXRUN RC 12 | designed: counts disagree / duplicate target key; reason printed in the report |
| AUDIT `SQLCODE -204` | tables missing -> run DB2DDL; `-803` = same batch id twice (wait 1 s) |
| AUDIT `DSNT408I ... -805` / `-924` | wrong plan name / DB2 ssid / libs in config.json |
| `python run_batch.py` says job did not finish | job waits in the queue; check JOBS view, rerun later |
| `zowe` not found | install Node.js, then `npm install -g @zowe/cli` |

## 5. Where each course topic is covered
DFSORT: SORT / SUM FIELDS=NONE / OPTION EQUALS / ICETOOL COUNT.
COBOL: file I/O, match-merge, numeric edit, intrinsic functions, return code.
REXX: EXECIO, stems, shell sort, parsing, SQL generation, exit codes.
JCL: IEFBR14, IF/THEN/ELSE, GDG, IDCAMS (GDG, KSDS, REPRO), IKJEFT01, procs.
DB2: DDL, unique index, DSNTEP2, audit tables, query job.
Python: test data, Zowe automation, independent oracle, Streamlit UI.

## 6. Tests (run them whenever you change code)
```
python tests/test_python.py            # generator, renderer, UI (10 tests)
python tests/test_mainframe_logic.py   # needs GnuCOBOL + Regina REXX (optional)
python tests/test_end_to_end.py        # deploy + run_batch against a fake zowe
```
The last two run the real COBOL and REXX on 9 scenarios (4 + 5 edge cases)
on a Linux machine and compare with the Python oracle.
