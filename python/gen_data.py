"""
gen_data.py - builds the test data for the Migration Validator.

    python gen_data.py --scenario seeded        (default, expected RC 8)
    python gen_data.py --scenario dups          (expected RC 4)
    python gen_data.py --scenario clean         (expected RC 0)
    python gen_data.py --scenario dup_target    (expected RC 12)

Files written to ../data/<scenario>/ :
    src_extract.txt        1,000 (+20 dups) records, 80 bytes, legacy layout
    tgt_extract.txt        modern-system extract, 100 bytes
    customer_new_load.sql  INSERTs that load the same target rows into DB2
    expected.json          the answer key the tests/UI compare against
Layouts (1-based columns):
  SOURCE 80 : CUST-ID 1-8 | ACCT-NO 9-18 | NAME 19-38 | BALANCE 39-49
              (9 digits + 2 implied decimals, unsigned) | TXN-DATE 50-57
              YYYYMMDD | STATUS 58 | filler 59-80
  TARGET 100: CUST_ID 1-8 | ACCT_NO 9-18 | NAME 19-58 | BALANCE 59-70
              (text 1234.56, right aligned) | TXN_DATE 71-80 YYYY-MM-DD
              | STATUS 81 | filler 82-100
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
from pathlib import Path

FIRST = ["AARAV", "ANANYA", "ARJUN", "DIYA", "ISHAAN", "KAVYA", "MEERA",
         "NEHA", "ROHAN", "SANYA", "VIKRAM", "TANVI", "KABIR", "RIYA",
         "SAMEER", "PRIYA", "NIKHIL", "ANJALI", "YASH", "POOJA"]
LAST = ["RAO", "IYER", "DAS", "SHARMA", "PATIL", "NAIR", "MEHTA", "JOSHI",
        "KULKARNI", "SINGH", "VERMA", "REDDY", "GUPTA", "DESAI", "BOSE"]
SCENARIOS = ["seeded", "dups", "clean", "dup_target"]


def make_base(rng: random.Random, n: int = 1000) -> list[dict]:
    recs = []
    start = dt.date(2025, 1, 1)
    for i in range(1, n + 1):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"[:20]
        recs.append({
            "cust_id": f"C{i:07d}",
            "acct_no": f"A{100000000 + i * 7:09d}",
            "name": name,
            "cents": rng.randint(10000, 9999999),
            "date": start + dt.timedelta(days=rng.randint(0, 600)),
            "status": rng.choice("AAAAIC"),
        })
    return recs


def src_line(r: dict) -> str:
    s = (r["cust_id"].ljust(8) + r["acct_no"].ljust(10) + r["name"].ljust(20)
         + f"{r['cents']:011d}" + r["date"].strftime("%Y%m%d") + r["status"])
    return s.ljust(80)


def tgt_line(r: dict) -> str:
    bal = f"{r['cents'] // 100}.{r['cents'] % 100:02d}".rjust(12)
    s = (r["cust_id"].ljust(8) + r["acct_no"].ljust(10) + r["name"].ljust(40)
         + bal + r["date"].strftime("%Y-%m-%d") + r["status"])
    return s.ljust(100)


def sql_lines(rows: list[dict]) -> list[str]:
    out = ["DELETE FROM CUSTOMER_NEW;"]
    for r in rows:
        out.append("INSERT INTO CUSTOMER_NEW VALUES")
        out.append(f" ('{r['cust_id']}','{r['acct_no']}',")
        out.append(f"  '{r['name']}',")
        out.append(f"  {r['cents'] // 100}.{r['cents'] % 100:02d},"
                   f"'{r['date'].isoformat()}','{r['status']}');")
    out.append("COMMIT;")
    assert all(len(x) <= 72 for x in out)
    return out


def build(scenario: str, seed: int = 42):
    rng = random.Random(seed)
    base = make_base(rng)
    exp = {"scenario": scenario, "missing_keys": [], "extra_keys": [],
           "changed": [], "dup_keys": []}

    # ---- source side
    src = list(base)
    if scenario in ("seeded", "dups", "dup_target"):
        for r in rng.sample(base, 20):
            src.append(dict(r))
            exp["dup_keys"].append(r["cust_id"] + r["acct_no"])
    rng.shuffle(src)

    # ---- target side
    tgt = [dict(r) for r in base]
    if scenario in ("seeded", "dup_target"):
        gone = rng.sample(range(len(tgt)), 10)
        for i in sorted(gone, reverse=True):
            exp["missing_keys"].append(tgt[i]["cust_id"])
            del tgt[i]
        idx = rng.sample(range(len(tgt)), 15)
        kinds = ["BALANCE"] * 6 + ["NAME"] * 3 + ["TXNDATE"] * 3 + ["STATUS"] * 3
        for i, kind in zip(idx, kinds):
            r = tgt[i]
            if kind == "BALANCE":
                r["cents"] += rng.choice([-4500, -50, 100, 2500, 99900])
                r["cents"] = max(r["cents"], 100)
            elif kind == "NAME":
                r["name"] = (r["name"][:-1] + "X") if r["name"][-1] != "X" \
                    else (r["name"][:-1] + "Z")
            elif kind == "TXNDATE":
                r["date"] = r["date"] + dt.timedelta(days=rng.randint(1, 20))
            else:
                r["status"] = "I" if r["status"] != "I" else "A"
            exp["changed"].append({"cust_id": r["cust_id"], "field": kind})
        for j in range(1, 6):
            tgt.append({"cust_id": f"C{1000 + j:07d}",
                        "acct_no": f"A{900000000 + j:09d}",
                        "name": f"EXTRA CUSTOMER {j}",
                        "cents": rng.randint(10000, 500000),
                        "date": dt.date(2026, 3, j), "status": "A"})
            exp["extra_keys"].append(f"C{1000 + j:07d}")
    sql_rows = [dict(r) for r in tgt]
    if scenario == "dup_target":
        tgt.append(dict(tgt[3]))          # same key twice in the extract
    rng.shuffle(tgt)

    if scenario == "seeded":
        exp.update(rc=8, decision="REJECTED", raw=1020, dups=20,
                   src_unique=1000, tgt_cnt=995, matched=975, mismatch=15,
                   missing=10, extra=5)
        exp["seeded_defects"] = 50
    elif scenario == "dups":
        exp.update(rc=4, decision="WARNING", raw=1020, dups=20,
                   src_unique=1000, tgt_cnt=1000, matched=1000, mismatch=0,
                   missing=0, extra=0)
    elif scenario == "clean":
        exp.update(rc=0, decision="APPROVED", raw=1000, dups=0,
                   src_unique=1000, tgt_cnt=1000, matched=1000, mismatch=0,
                   missing=0, extra=0)
    else:
        exp.update(rc=12, decision="ABORTED", raw=1020, dups=20,
                   src_unique=1000, tgt_cnt=996)
    return src, tgt, sql_rows, exp


def write_scenario(scenario: str, out_root: Path, seed: int = 42) -> Path:
    src, tgt, sql_rows, exp = build(scenario, seed)
    d = out_root / scenario
    d.mkdir(parents=True, exist_ok=True)
    def put(name: str, text: str) -> None:      # always LF line ends
        (d / name).write_bytes(text.encode("ascii"))

    put("src_extract.txt", "\n".join(src_line(r) for r in src) + "\n")
    put("tgt_extract.txt", "\n".join(tgt_line(r) for r in tgt) + "\n")
    put("customer_new_load.sql", "\n".join(sql_lines(sql_rows)) + "\n")
    put("expected.json", json.dumps(exp, indent=2) + "\n")
    return d


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--scenario", choices=SCENARIOS + ["all"], default="seeded")
    ap.add_argument("--out", default=str(Path(__file__).parent.parent / "data"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    for sc in (SCENARIOS if a.scenario == "all" else [a.scenario]):
        d = write_scenario(sc, Path(a.out), a.seed)
        print(f"wrote {d}")


if __name__ == "__main__":
    main()
