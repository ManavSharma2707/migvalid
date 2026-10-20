"""
render.py - turns the templates in mainframe/ into ready-to-use files in
build/ by replacing the @TOKENS@ with the values in config.json, and LINTS
the result so typical mistakes are caught on your laptop, not on z/OS.

    python render.py                (uses python/config.json)
    python render.py --config other.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = {"jcl": ROOT / "mainframe" / "jcl",
             "cobol": ROOT / "mainframe" / "cobol",
             "rexx": ROOT / "mainframe" / "rexx"}
BUILD = ROOT / "build"

REQUIRED = ["hlq", "acct", "job_class", "msgclass", "unit", "db2_ssid",
            "db2_loadlib", "db2_runlib", "db2_plan", "cobol_proc"]
# characters whose EBCDIC code differs between code pages -> never used
FORBIDDEN = set("\\|[]^~`!#{}")


class ConfigError(Exception):
    pass


def load_config(path: Path) -> dict:
    if not path.exists():
        raise ConfigError(f"{path} not found. Copy config.example.json to "
                          f"config.json and fill in your values.")
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for k in REQUIRED:
        if not str(cfg.get(k, "")).strip():
            raise ConfigError(f"config.json: '{k}' is empty")
    cfg["hlq"] = cfg["hlq"].strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9]{0,6}", cfg["hlq"]):
        raise ConfigError("hlq must be your userid: 1-7 characters, "
                          "letters/digits, starting with a letter "
                          "(job names are userid + 1 letter)")
    if cfg["hlq"].startswith("ZZZZZ"):
        raise ConfigError("replace the example userid in config.json")
    return cfg


def token_map(cfg: dict) -> dict[str, str]:
    lng = cfg.get("cobol_lngprfx", "").strip()
    return {
        "HLQ": cfg["hlq"], "ACCT": cfg["acct"], "CLASS": cfg["job_class"],
        "MSGCLASS": cfg["msgclass"], "UNIT": cfg["unit"],
        "DB2SSID": cfg["db2_ssid"], "DB2LOAD": cfg["db2_loadlib"],
        "DB2RUN": cfg["db2_runlib"], "DB2PLAN": cfg["db2_plan"],
        "COBPROC": cfg["cobol_proc"],
        "LNGPRFX_PARM": f",LNGPRFX={lng}" if lng else "",
    }


def lint(kind: str, name: str, text: str) -> list[str]:
    problems = []
    max_len = {"jcl": 71, "cobol": 72, "rexx": 80}[kind]
    for n, ln in enumerate(text.split("\n"), 1):
        where = f"{name}:{n}"
        if "\t" in ln:
            problems.append(f"{where}: TAB character")
        if any(ord(c) > 126 for c in ln):
            problems.append(f"{where}: non-ASCII character")
        bad = FORBIDDEN & set(ln)
        if bad:
            problems.append(f"{where}: forbidden character(s) {sorted(bad)}")
        if len(ln) > max_len:
            problems.append(f"{where}: {len(ln)} columns (max {max_len})")
        if "@" in ln:
            problems.append(f"{where}: unreplaced @TOKEN@")
    if kind == "jcl":
        first = text.split("\n", 1)[0]
        m = re.match(r"//(\S+)\s+JOB\b", first)
        if not m:
            problems.append(f"{name}:1: first line must be the JOB card")
        elif len(m.group(1)) > 8:
            problems.append(f"{name}:1: job name '{m.group(1)}' is longer "
                            f"than 8 characters (userid too long?)")
    return problems


def render(cfg: dict) -> list[str]:
    tokens = token_map(cfg)
    problems: list[str] = []
    for kind, folder in TEMPLATES.items():
        out_dir = BUILD / kind
        out_dir.mkdir(parents=True, exist_ok=True)
        for f in sorted(folder.iterdir()):
            if f.is_dir():
                continue
            text = f.read_text(encoding="utf-8").replace("\r\n", "\n")

            def sub(m: re.Match) -> str:
                key = m.group(1)
                if key not in tokens:
                    problems.append(f"{f.name}: unknown token @{key}@")
                    return m.group(0)
                return tokens[key]

            text = re.sub(r"@([A-Z0-9_]+)@", sub, text)
            problems += lint(kind, f.name, text)
            (out_dir / f.name).write_bytes(text.encode("ascii", "replace"))
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).parent / "config.json"))
    a = ap.parse_args()
    try:
        cfg = load_config(Path(a.config))
    except ConfigError as e:
        print("CONFIG ERROR:", e)
        return 2
    problems = render(cfg)
    if problems:
        print("LINT PROBLEMS:")
        for p in problems:
            print("  -", p)
        return 1
    print(f"OK - rendered {sum(1 for _ in BUILD.rglob('*') if _.is_file())} "
          f"files into {BUILD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
