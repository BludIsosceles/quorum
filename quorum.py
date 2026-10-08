#!/usr/bin/env python3
"""
quorum — orchestrate agents with independence enforced by the tool, not by care.

Every rule in this file exists because the rule was broken by hand first.

The premise, learned the expensive way: **self-verification fails structurally.**
The mind that made an error is the least equipped to see it, because the error
came from its own model of the problem. So the load-bearing feature here is not
parallelism — it is that a monitor CANNOT be the same model family as the work
it checks. Not "should not". The dispatch refuses.

What is mechanised, and the failure that motivated each:

  cross-family pairing   a family verifying its own output shares its blind
                         spots; enforced at dispatch, not left to attention
  write-once artifacts   a retry once pointed at a failed worker's output path
                         and destroyed the original via shell redirect
  capability probes      a harness was assigned web research for a whole
                         operation before anyone checked it could reach the web
                         (it could not)
  blocked detection      a worker exited 0 having written nothing; another burned
                         its budget planning and never composed an answer
  automatic ledger       timestamps drifted up to 30 minutes when estimated by
                         hand instead of taken from the clock
  cost tiering           an 85%-failure lane must not spend a paid tier on the
                         85%

Read-only with respect to judgement: quorum dispatches, records, and refuses.
It does not decide what to ask, and it does not adjudicate what comes back.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

__version__ = "0.1.0"


# --------------------------------------------------------------------- roster

@dataclasses.dataclass(frozen=True)
class Harness:
    """A dispatchable agent CLI.

    `family` is the independence key. Two harnesses sharing a family may never
    check each other, regardless of vendor or model name.
    """
    name: str
    family: str
    argv: list[str]          # {prompt} is substituted
    web: bool                # verified by probe, not by documentation
    shell: bool              # can execute local commands
    cost: str                # "free" | "cheap" | "paid"
    notes: str = ""

    def command(self, prompt: str) -> list[str]:
        return [a.replace("{prompt}", prompt) for a in self.argv]


# A routed alias (qodercli "Ultimate", "Auto", ...) picks a model per request from a
# catalog spanning several families -- Qwen, Kimi, GLM, DeepSeek, MiniMax on the
# 2026-10-07 listing. Its family is not knowable at dispatch, so a lane served
# through one carries ROUTED rather than a guessed family. Labelling it "qwen", as
# this roster did, let the independence check trust a claim nobody could verify:
# an Ultimate verifier could be Kimi-K3 checking k3 work, with no error raised.
# Reported by the Decatron desk (review-3 roster note); this is the stopgap until
# per-model family slots (U-5) exist.
ROUTED = "routed-unknown"


# Empirical roster. Every field below was established by probe or by failure
# during Delta's first operations — not copied from vendor documentation.
ROSTER: dict[str, Harness] = {
    "devin": Harness(
        "devin", "swe",
        ["devin", "--model", "swe-1-7", "-p", "{prompt}"],
        web=False, shell=True, cost="free",
        notes="NO WEB ACCESS (probed). Strongest adversarial reviewer. "
              "Reason-from-embedded-text roles only."),
    "agy": Harness(
        "agy", "gemini",
        ["agy", "--model", "gemini-3.6-flash-high", "-p", "{prompt}"],
        web=True, shell=True, cost="paid",
        notes="Does NOT inherit caller cwd — writes land in its own scratch. "
              "Use absolute paths; unsuitable for local-filesystem verification."),
    "kimi": Harness(
        "kimi", "k3",
        ["kimi", "-p", "{prompt}"],
        web=True, shell=True, cost="free",
        notes="Appends reasoning bullets and a session-resume line to stdout; "
              "parsers must tolerate. Has aborted before composing a final answer "
              "— give it an explicit compose deadline."),
    "qoder": Harness(
        "qoder", "qwen",
        ["qodercli", "-m", "Qwen3.8-Max", "-p", "{prompt}",
         "--print", "--max-output-tokens", "8000", "--no-session-persistence"],
        web=True, shell=True, cost="cheap",
        notes="Buffers output until process exit — an empty file means running, "
              "not failed. Has stalled on shell-heavy dispatches."),
    "qoder-ultimate": Harness(
        "qoder-ultimate", ROUTED,
        ["qodercli", "-m", "Ultimate", "-p", "{prompt}",
         "--print", "--max-output-tokens", "8000", "--no-session-persistence"],
        web=True, shell=True, cost="free",
        notes="Top-tier routed. Promotional balance only — falls back to PAID "
              "billing once exhausted. Confirm balance before volume use."),
}

# The Overseer's own family. Anything Delta authors is checked by something else.
OVERSEER_FAMILY = "anthropic"




class IndependenceError(RuntimeError):
    """Raised when a dispatch would let a family check its own work."""


# ---------------------------------------------------------------- the operation

class Op:
    """One orchestrated operation. Owns artifacts, hashes, and the ledger."""

    def __init__(self, opid: str, root: str | pathlib.Path = ".", overseer: str = OVERSEER_FAMILY):
        self.opid = opid
        self.dir = pathlib.Path(root) / "builds" / opid
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "prompts").mkdir(exist_ok=True)
        self.overseer = overseer
        self.ledger = self.dir / "LEDGER.md"
        self.jobs: dict[str, dict] = {}
        if not self.ledger.exists():
            self.ledger.write_text(
                f"# {opid} Execution Ledger\n\n"
                "Append-only. Timestamps from the system clock, never estimated.\n\n"
                "| Timestamp (UTC) | Actor | Artifact | Event | Hash | Detail |\n"
                "|---|---|---|---|---|---|\n")
            self.log("quorum", "—", "INIT", f"Operation opened. Overseer family: {overseer}.")

    # -- ledger ------------------------------------------------------------
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def log(self, actor: str, artifact: str, event: str, detail: str, h: str = "—") -> None:
        detail = detail.replace("|", "\\|").replace("\n", " ")
        with self.ledger.open("a") as f:
            f.write(f"| {self._now()} | {actor} | {artifact} | {event} | {h} | {detail} |\n")

    # -- artifacts ---------------------------------------------------------
    def _path(self, name: str) -> pathlib.Path:
        """Never return a path that already holds an artifact.

        A retry once pointed at the failed attempt's output path; the shell
        redirect truncated it and the original was unrecoverable. Retries get
        their own file, always.
        """
        p = self.dir / name
        if not p.exists():
            return p
        n = 2
        while (alt := self.dir / f"{p.stem}.v{n}{p.suffix}").exists():
            n += 1
        return alt

    @staticmethod
    def _sha(p: pathlib.Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "—"

    # -- probes ------------------------------------------------------------
    def probe(self, names: list[str], need_web: bool = False) -> dict[str, bool]:
        """Verify each harness can do what it is about to be asked to do.

        A capability listed in documentation is a claim. An operation was once
        planned around a harness's web access that it did not have.
        """
        results = {}
        for name in names:
            h = ROSTER[name]
            if shutil.which(h.argv[0]) is None:
                results[name] = False
                self.log("quorum", "—", "PROBE", f"{name}: FAIL — binary not found")
                continue
            if need_web and not h.web:
                results[name] = False
                self.log("quorum", "—", "PROBE",
                         f"{name}: FAIL — web required, roster records no web access. {h.notes}")
                continue
            results[name] = True
            self.log("quorum", "—", "PROBE", f"{name}: PASS (family={h.family}, cost={h.cost})")
        return results

    # -- dispatch ----------------------------------------------------------
    def dispatch(self, label: str, prompt: str, harness: str,
                 verifies: str | None = None, role: str = "worker",
                 min_bytes: int = 200) -> dict:
        """Run one agent. Refuses same-family verification.

        `verifies` names a previous job. When set, this dispatch is a check on
        that job's output and the independence rule is enforced here rather
        than trusted to whoever wrote the plan.

        `min_bytes` is the floor below which output counts as BLOCKED. Set it to
        the smallest plausible real answer for THIS dispatch — a one-word probe
        and a research report do not share a threshold.
        """
        h = ROSTER[harness]

        if verifies is not None:
            target = self.jobs.get(verifies)
            if target is None:
                raise KeyError(f"cannot verify unknown job {verifies!r}")
            if ROUTED in (h.family, target["family"]):
                raise IndependenceError(
                    f"{harness} (family={h.family}) verifying {verifies} "
                    f"(family={target['family']}): a routed alias serves several families and "
                    f"its family is unknowable at dispatch, so independence cannot be "
                    f"established. Use a lane pinned to one model.")
            if h.family == target["family"]:
                raise IndependenceError(
                    f"{harness} (family={h.family}) may not verify {verifies} "
                    f"(family={target['family']}). A family cannot check its own output — "
                    f"same training, same blind spots. Choose from: "
                    f"{sorted({x.name for x in ROSTER.values() if x.family != target['family']})}")
            if h.family == self.overseer:
                raise IndependenceError(
                    f"{harness} shares the Overseer's family ({self.overseer}); it cannot "
                    f"provide independent verification of this operation's work.")

        pp = self.dir / "prompts" / f"prompt-{label}.md"
        pp.write_text(prompt)
        out = self._path(f"{label}-output.md")

        self.log(harness, pp.name, "DISPATCH",
                 f"{role} '{label}'"
                 + (f" verifying '{verifies}' (cross-family {target['family']}→{h.family})" if verifies else "")
                 + f". Output → {out.name}.", self._sha(pp))

        t0 = time.time()
        try:
            r = subprocess.run(h.command(prompt), capture_output=True, text=True, timeout=3600)
            out.write_text(r.stdout or "")
            code = r.returncode
            err = (r.stderr or "")[-400:]
        except Exception as e:  # noqa: BLE001
            out.write_text("")
            code, err = -1, f"{type(e).__name__}: {e}"

        size = out.stat().st_size
        # Expected output length varies by three orders of magnitude between a
        # one-word probe and a research report, so the floor is per-dispatch.
        # A fixed threshold flagged a correct 14-byte answer as BLOCKED during
        # this module's own smoke test — a verification tool that cries wolf
        # gets ignored, which is the failure mode it exists to prevent.
        blocked = size < min_bytes
        job = {"label": label, "harness": harness, "family": h.family, "role": role,
               "output": str(out), "bytes": size, "exit": code, "blocked": blocked,
               "secs": round(time.time() - t0), "verifies": verifies}
        self.jobs[label] = job

        if blocked:
            # Observed twice: exit 0 with no output, and a worker that spent its
            # budget planning and never composed. Silence is a result, not a pass.
            self.log(harness, out.name, "BLOCKED",
                     f"'{label}' produced {size} bytes in {job['secs']}s (exit {code}). "
                     f"{h.notes} stderr: {err[:150]}", self._sha(out))
        else:
            self.log(harness, out.name, "COMPLETE",
                     f"'{label}' returned {size} bytes in {job['secs']}s.", self._sha(out))
        return job

    # -- reporting ---------------------------------------------------------
    def summary(self) -> str:
        lines = [f"\n{self.opid} — {len(self.jobs)} dispatch(es)", "=" * 62]
        fams: dict[str, set] = {}
        for j in self.jobs.values():
            fams.setdefault(j["role"], set()).add(j["family"])
            flag = "BLOCKED" if j["blocked"] else "ok     "
            v = f"  verifies {j['verifies']}" if j["verifies"] else ""
            lines.append(f"  {flag} {j['label']:<22} {j['harness']:<15} "
                         f"{j['bytes']:>7}B {j['secs']:>4}s{v}")
        blocked = sum(1 for j in self.jobs.values() if j["blocked"])
        lines.append("=" * 62)
        lines.append(f"  blocked: {blocked}/{len(self.jobs)}")
        if self.jobs and blocked / len(self.jobs) > 0.5:
            lines.append("  >50% BLOCKED — protocol requires stopping and reporting to the operator.")
        lines.append(f"  families used: " + ", ".join(f"{k}={sorted(v)}" for k, v in fams.items()))
        lines.append(f"  ledger: {self.ledger}")
        return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="quorum", description="Roster and independence rules.")
    ap.add_argument("--roster", action="store_true", help="print the harness roster")
    ap.add_argument("--check", nargs=2, metavar=("HARNESS", "TARGET_FAMILY"),
                    help="would HARNESS be allowed to verify TARGET_FAMILY's output?")
    a = ap.parse_args()

    if a.check:
        name, fam = a.check
        h = ROSTER.get(name)
        if not h:
            print(f"unknown harness {name!r}"); return 2
        ok = h.family != fam and h.family != OVERSEER_FAMILY
        print(f"{name} (family={h.family}) verifying {fam}: {'ALLOWED' if ok else 'REFUSED'}")
        if not ok:
            print("  a family cannot check its own output — same training, same blind spots")
        return 0 if ok else 1

    print(f"quorum {__version__} — harness roster (empirical; probe-derived)\n")
    print(f"{'name':<16}{'family':<10}{'web':<6}{'shell':<7}{'cost':<7}notes")
    print("-" * 100)
    for h in ROSTER.values():
        print(f"{h.name:<16}{h.family:<10}{'yes' if h.web else 'NO':<6}"
              f"{'yes' if h.shell else 'no':<7}{h.cost:<7}{h.notes[:56]}")
    print(f"\noverseer family: {OVERSEER_FAMILY} — excluded from verifying this operation's work")
    return 0


if __name__ == "__main__":
    sys.exit(main())
