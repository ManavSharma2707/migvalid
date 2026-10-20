"""
validator_core.py - record layouts, parsers and a pure-Python reference
implementation of the validator.

The reference implementation does the SAME job as the mainframe batch
(DFSORT dedupe -> COBOL match-merge -> REXX decision).  It is used
  * by the unit tests, to prove the COBOL/REXX results are right,
  * by the Streamlit app, as an independent "oracle" check and as an
    offline demo mode when the mainframe is not reachable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

# ----- fixed-width layouts (0-based slices of the record text) --------
SRC_LRECL = 80
TGT_LRECL = 100
EXC_LRECL = 100


@dataclass
class SrcRec:
    cust_id: str
    acct_no: str
    name: str
    balance_raw: str     # 11 digits, 2 implied decimals
    txn_date: str        # YYYYMMDD
    status: str

    @property
    def key(self) -> str:
        return self.cust_id + self.acct_no

    @property
    def balance(self) -> Decimal | None:
        if len(self.balance_raw) == 11 and self.balance_raw.isdigit():
            return Decimal(int(self.balance_raw)) / 100
        return None


@dataclass
class TgtRec:
    cust_id: str
    acct_no: str
    name: str
    balance_txt: str
    date_txt: str        # YYYY-MM-DD
    status: str

    @property
    def key(self) -> str:
        return self.cust_id + self.acct_no

    @property
    def balance(self) -> Decimal | None:
        t = self.balance_txt.strip()
        if not t:
            return None
        try:
            v = Decimal(t)
        except InvalidOperation:
            return None
        return v.quantize(Decimal("0.01"), rounding="ROUND_DOWN")

    @property
    def date_norm(self) -> str | None:
        d = self.date_txt
        if len(d) == 10 and d[4] == "-" and d[7] == "-":
            return d[0:4] + d[5:7] + d[8:10]
        return None


def parse_src_line(line: str) -> SrcRec:
    line = line.rstrip("\r\n").ljust(SRC_LRECL)
    return SrcRec(line[0:8], line[8:18], line[18:38], line[38:49],
                  line[49:57], line[57:58])


def parse_tgt_line(line: str) -> TgtRec:
    line = line.rstrip("\r\n").ljust(TGT_LRECL)
    return TgtRec(line[0:8], line[8:18], line[18:58], line[58:70],
                  line[70:80], line[80:81])


def read_lines(path: str) -> list[str]:
    with open(path, "r", encoding="ascii", errors="replace") as fh:
        return [ln.rstrip("\r\n") for ln in fh if ln.strip("\r\n") != ""]


# ----- reference implementation ---------------------------------------
@dataclass
class Exception_:
    cust_id: str
    acct_no: str
    err_type: str        # MISSING | MISMATCH | EXTRA
    field: str           # *RECORD | NAME | BALANCE | TXNDATE | STATUS
    src_val: str
    tgt_val: str


@dataclass
class Result:
    raw: int = 0
    dups: int = 0
    src_unique: int = 0
    tgt_cnt: int = 0
    matched: int = 0
    mismatch: int = 0
    missing: int = 0
    extra: int = 0
    rc: int = 0
    decision: str = ""
    reason: str = ""
    src_bal_tot: Decimal = Decimal("0")
    tgt_bal_tot: Decimal = Decimal("0")
    exceptions: list[Exception_] = field(default_factory=list)
    dup_keys: list[str] = field(default_factory=list)


def _fmt(d: Decimal) -> str:
    return f"{d:.2f}"


def reconcile(src_lines: list[str], tgt_lines: list[str]) -> Result:
    res = Result()
    src = [parse_src_line(x) for x in src_lines]
    tgt = [parse_tgt_line(x) for x in tgt_lines]
    res.raw = len(src)
    res.tgt_cnt = len(tgt)

    # DFSORT: SORT FIELDS=(1,18,CH,A) / SUM FIELDS=NONE / OPTION EQUALS
    first: dict[str, SrcRec] = {}
    seen_dups: dict[str, int] = {}
    for r in src:
        if r.key in first:
            seen_dups[r.key] = seen_dups.get(r.key, 1) + 1
        else:
            first[r.key] = r
    res.src_unique = len(first)
    res.dups = res.raw - res.src_unique
    res.dup_keys = sorted(seen_dups)

    # COBOL: the target must have unique keys, otherwise it aborts
    tkeys = [t.key for t in tgt]
    if len(set(tkeys)) != len(tkeys):
        res.rc, res.decision, res.reason = 12, "ABORTED", \
            "COBOL ABORT: TGT DUPLICATE KEY"
        return res
    tmap = {t.key: t for t in tgt}

    for r in first.values():
        if r.balance is not None:
            res.src_bal_tot += r.balance
    for t in tgt:
        if t.balance is not None:
            res.tgt_bal_tot += t.balance

    for k in sorted(first):
        s = first[k]
        t = tmap.get(k)
        if t is None:
            res.missing += 1
            sv = s.name.strip()
            if s.balance is not None:
                sv += " " + _fmt(s.balance)
            res.exceptions.append(Exception_(s.cust_id, s.acct_no,
                                             "MISSING", "*RECORD", sv[:30], ""))
            continue
        diffs: list[Exception_] = []
        if s.name.rstrip() != t.name.rstrip():
            diffs.append(Exception_(s.cust_id, s.acct_no, "MISMATCH",
                                    "NAME", s.name.strip(), t.name.strip()[:30]))
        if s.balance is None or t.balance is None:
            diffs.append(Exception_(s.cust_id, s.acct_no, "MISMATCH",
                                    "BALANCE", s.balance_raw.strip(),
                                    t.balance_txt.strip()))
        elif s.balance != t.balance:
            diffs.append(Exception_(s.cust_id, s.acct_no, "MISMATCH",
                                    "BALANCE", _fmt(s.balance), _fmt(t.balance)))
        if t.date_norm is None or t.date_norm != s.txn_date:
            diffs.append(Exception_(s.cust_id, s.acct_no, "MISMATCH",
                                    "TXNDATE", s.txn_date.strip(),
                                    t.date_txt.strip()))
        if s.status != t.status:
            diffs.append(Exception_(s.cust_id, s.acct_no, "MISMATCH",
                                    "STATUS", s.status.strip(),
                                    t.status.strip()))
        if diffs:
            res.mismatch += 1
            res.exceptions.extend(diffs)
        else:
            res.matched += 1

    for k in sorted(tmap):
        if k not in first:
            t = tmap[k]
            res.extra += 1
            tv = t.name.strip()
            if t.balance is not None:
                tv += " " + _fmt(t.balance)
            res.exceptions.append(Exception_(t.cust_id, t.acct_no, "EXTRA",
                                             "*RECORD", "", tv[:30]))

    if res.missing + res.extra + res.mismatch > 0:
        res.rc, res.decision = 8, "REJECTED"
    elif res.dups > 0:
        res.rc, res.decision = 4, "WARNING"
    else:
        res.rc, res.decision = 0, "APPROVED"

    rank = {"MISSING": 1, "MISMATCH": 2, "EXTRA": 3}
    res.exceptions.sort(key=lambda e: (rank[e.err_type], e.cust_id,
                                       e.acct_no, e.field))
    return res


# ----- parsers for the files the mainframe job produces ----------------
def parse_excsort(text: str) -> list[Exception_]:
    out = []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        ln = ln.ljust(EXC_LRECL)
        out.append(Exception_(ln[0:8].strip(), ln[8:18].strip(),
                              ln[18:26].strip(), ln[26:34].strip(),
                              ln[34:64].strip(), ln[64:94].strip()))
    return out


def parse_result(text: str) -> dict[str, str]:
    d: dict[str, str] = {}
    for ln in text.splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip()
    return d


def result_to_dict(res: Result) -> dict[str, str]:
    return {
        "DECISION": res.decision, "RC": str(res.rc),
        "SRC_RAW": str(res.raw), "DUPS": str(res.dups),
        "SRC_UNIQUE": str(res.src_unique), "TGT_CNT": str(res.tgt_cnt),
        "MATCHED": str(res.matched), "MISMATCH": str(res.mismatch),
        "MISSING": str(res.missing), "EXTRA": str(res.extra),
        "SRC_BAL_TOT": _fmt(res.src_bal_tot),
        "TGT_BAL_TOT": _fmt(res.tgt_bal_tot),
    }


COMPARE_KEYS = ["DECISION", "RC", "SRC_RAW", "DUPS", "SRC_UNIQUE", "TGT_CNT",
                "MATCHED", "MISMATCH", "MISSING", "EXTRA"]


def compare_to_oracle(mf: dict[str, str], mf_exc: list[Exception_],
                      oracle: Result) -> list[str]:
    """Return a list of human readable differences (empty = identical)."""
    diffs = []
    o = result_to_dict(oracle)
    if oracle.rc == 12:
        keys = ["DECISION", "RC"]
    else:
        keys = COMPARE_KEYS
    for k in keys:
        if str(mf.get(k, "")).strip() != o[k]:
            diffs.append(f"{k}: mainframe={mf.get(k)!r} reference={o[k]!r}")
    if oracle.rc != 12:
        a = sorted((e.cust_id, e.acct_no, e.err_type, e.field) for e in mf_exc)
        b = sorted((e.cust_id, e.acct_no, e.err_type, e.field)
                   for e in oracle.exceptions)
        if a != b:
            diffs.append(f"exception rows differ: mainframe={len(a)} "
                         f"reference={len(b)}")
    return diffs


def find_duplicates(src_lines: list[str]) -> list[dict]:
    """Keys that appear more than once in the raw source extract.
    'conflicting' = the copies are NOT identical (DFSORT keeps the first
    one and silently drops the rest, so these need a human look)."""
    groups: dict[str, list[str]] = {}
    for ln in src_lines:
        r = parse_src_line(ln)
        groups.setdefault(r.key, []).append(ln.ljust(SRC_LRECL))
    out = []
    for k, v in sorted(groups.items()):
        if len(v) > 1:
            out.append({"cust_id": k[:8], "acct_no": k[8:],
                        "copies": len(v),
                        "conflicting": len(set(v)) > 1,
                        "name": parse_src_line(v[0]).name.strip()})
    return out
