"""
mf_client.py - thin wrapper around the Zowe CLI (the same z/OSMF
connection your Zowe Explorer profile uses).  Every command is one
subprocess call, so you can copy any of them into a terminal and run it
by hand if something goes wrong.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path


class MFError(RuntimeError):
    pass


class Zowe:
    def __init__(self, profile: str = "", log=print):
        self.exe = shutil.which("zowe")
        if not self.exe:
            raise MFError("Zowe CLI not found. Install it with: "
                          "npm install -g @zowe/cli   (then: zowe --version)")
        self.profile = profile.strip()
        self.log = log

    # ---------------------------------------------------------- plumbing
    def _run(self, args: list[str], rfj: bool = True, timeout: int = 300) -> str:
        cmd = [self.exe, *args]
        if self.profile:
            cmd += ["--zosmf-profile", self.profile]
        if rfj:
            cmd.append("--rfj")
        self.log("$ zowe " + " ".join(args))
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=timeout)
        if p.returncode != 0:
            raise MFError(f"zowe {' '.join(args[:3])} failed "
                          f"(exit {p.returncode}):\n{p.stdout}\n{p.stderr}")
        return p.stdout

    def _json(self, args: list[str]) -> dict:
        out = self._run(args, rfj=True)
        try:
            return json.loads(out)
        except json.JSONDecodeError as e:
            raise MFError(f"zowe returned non-JSON output: {out[:500]}") from e

    # ------------------------------------------------------------ datasets
    def upload(self, local: Path, dsn: str) -> None:
        self._json(["zos-files", "upload", "file-to-data-set",
                    str(local), dsn])

    def download(self, dsn: str, local: Path) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        self._json(["zos-files", "download", "data-set", dsn,
                    "--file", str(local)])

    # ---------------------------------------------------------------- jobs
    def submit_local(self, local: Path) -> str:
        d = self._json(["zos-jobs", "submit", "local-file", str(local)])
        return d["data"]["jobid"]

    def submit_dataset(self, dsn_member: str) -> str:
        d = self._json(["zos-jobs", "submit", "data-set", dsn_member])
        return d["data"]["jobid"]

    def wait(self, jobid: str, timeout: int = 600, poll: int = 3) -> str:
        """Wait until the job is finished; returns e.g. 'CC 0008'."""
        end = time.time() + timeout
        while time.time() < end:
            d = self._json(["zos-jobs", "view", "job-status-by-jobid",
                            jobid])["data"]
            if str(d.get("status", "")).upper() == "OUTPUT":
                return str(d.get("retcode") or "UNKNOWN")
            time.sleep(poll)
        raise MFError(f"job {jobid} did not finish within {timeout}s "
                      f"(it may be waiting in the queue)")

    def spool(self, jobid: str) -> str:
        return self._run(["zos-jobs", "view", "all-spool-content", jobid],
                         rfj=False)


def cc_value(retcode: str) -> int | None:
    """'CC 0008' -> 8 ; 'ABEND S0C7' / 'JCL ERROR' -> None"""
    parts = retcode.split()
    if len(parts) == 2 and parts[0] == "CC" and parts[1].isdigit():
        return int(parts[1])
    return None
