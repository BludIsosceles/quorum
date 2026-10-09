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
  family from the pin    a routed alias labelled "qwen" could have been Kimi
                         checking Kimi; the family is now read from the model
                         pinned in argv, and anything unpinned, routed, or
                         contradicting its label is refused as unverifiable
  process-group kill     a timeout killed the CLI and left its workers running;
                         stdin is closed so a prompt cannot hang a dispatch

Read-only with respect to judgement: quorum dispatches, records, and refuses.
It does not decide what to ask, and it does not adjudicate what comes back.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

__version__ = "0.3.0"


# --------------------------------------------------------------------- roster

@dataclasses.dataclass(frozen=True)
class Harness:
    """A dispatchable agent CLI.

    `family` is the DECLARED independence key. It is not trusted on its own:
    `resolve()` reads the model pinned in argv and refuses a lane whose pin is
    missing, routed, unknown, or contradicts the declaration. Two harnesses
    resolving to the same family may never check each other.
    """
    name: str
    family: str
    argv: tuple[str, ...]    # {prompt} is substituted; frozen so a pin cannot be edited in place
    web: bool                # verified by probe, not by documentation
    shell: bool              # can execute local commands
    cost: str                # "free" | "cheap" | "paid"
    notes: str = ""

    def __post_init__(self) -> None:
        # A list here let `ROSTER["qoder"].argv[2] = "Ultimate"` retarget a lane while
        # its family label stayed put (grok-4.7 cross-family read, 2026-10-08).
        object.__setattr__(self, "argv", tuple(self.argv))

    def command(self, prompt: str) -> list[str]:
        return [a.replace("{prompt}", prompt) for a in self.argv]


# A routed alias (qodercli "Ultimate", "Auto", ...) picks a model per request from a
# catalog spanning several families -- Qwen, Kimi, GLM, DeepSeek, MiniMax on the
# 2026-10-07 listing. Its family is not knowable at dispatch. Labelling it "qwen", as
# this roster once did, let the independence check trust a claim nobody could verify:
# an Ultimate verifier could be Kimi-K3 checking k3 work, with no error raised.
# Reported by the Decatron desk (review-3 roster note).
#
# v0.1 fixed that by relabelling one lane, and the guard still read only the label:
# point any lane at "Ultimate", or relabel the routed lane, and it passed (grok-4.7
# cross-family read, 2026-10-08). So the family is now RESOLVED from the model pinned
# in argv, and the declared label must agree with it. Devin's catalog alone serves
# Claude, GPT, Gemini, Grok, Kimi, GLM and DeepSeek behind one binary, so a binary
# name says nothing about family; only the pin does.
ROUTED = "routed-unknown"      # served by a router; family decided per request
UNKNOWN = "unknown"            # unpinned, unrecognised, or contradicting its label

MODEL_FLAGS = ("-m", "--model")

# Router names observed in live catalogs (qodercli --list-models and devin models
# list, 2026-10-08). Matched after normalisation, so case does not matter.
ROUTED_ALIASES = {"auto", "ultimate", "performance", "efficient", "lite", "sonus",
                  "cantus", "adaptive", "fusion", "default"}

# Model id -> family. A FAMILY IS THE LAB THAT TRAINED THE MODEL: same lab, same
# data and habits, same blind spots. So Gemma is Google's and resolves gemini, Llama
# and Muse are both Meta's, gpt-oss is OpenAI's. That is the conservative reading,
# and the one this table already applied to Claude/Opus and to Kimi K2/K3.
#
# Each entry is a regex matched (re.match, so anchored at the start) against the
# normalised id with any vendor prefix ("nvidia/", "kimi-code/") removed. v0.2.0
# used bare startswith prefixes; "gpt", "opus" and "swe-" could claim ids they
# merely prefix (grok-47 and gpt-5.6-luna reads), so patterns now end on a digit,
# a separator, or the end of the id. First match wins. An id no entry matches is
# UNKNOWN and refused, never defaulted. Extend it for your own lanes. Coverage was
# extended 2026-10-09 to every pin the Decatron engine fields.
MODEL_FAMILIES: list[tuple[str, str]] = [
    ("qwen\\d", "qwen"),
    ("kimi-", "k3"), ("k3$", "k3"),                          # Moonshot; K2.x and K3 are one family
    ("glm-\\d", "glm"),
    ("deepseek-", "deepseek"),
    ("minimax-", "minimax"),
    ("gemini-\\d", "gemini"), ("gemma-\\d", "gemini"), ("diffusiongemma-", "gemini"),   # Google
    ("swe(-\\d|$)", "swe"),                                    # Cognition; bare "swe" is an alias
    ("claude-", "anthropic"), ("(opus|sonnet|haiku|fable)$", "anthropic"),
    ("gpt-oss-", "openai"), ("gpt-\\d", "openai"), ("codex$", "openai"),
    ("grok-\\d", "grok"),
    ("llama-", "meta"), ("muse-", "meta"),                   # Meta
    ("nemotron-", "nemotron"),                               # NVIDIA
    ("mistral-", "mistral"),
    ("mercury-", "inception"),
    ("seed-", "seed"),                                       # ByteDance Seed
    ("nova-", "nova"),                                       # Amazon
    ("solar-", "solar"),                                     # Upstage
    ("hy\\d", "hunyuan"), ("hunyuan-", "hunyuan"),             # Tencent
    ("laguna-", "laguna"),                                   # Poolside
    ("ling-", "ling"),                                       # inclusionAI
    ("mimo-", "mimo"),                                       # Xiaomi
    ("inkling$", "inkling"),                                 # Thinking Machines
]

# Ids whose family cannot be established however the table grows. Checked first.
UNRESOLVABLE: list[tuple[str, str]] = [
    ("mistral-nemotron", "trained jointly by Mistral and NVIDIA, so it belongs to two families; "
                         "independence from either cannot be shown"),
]
UNRESOLVABLE_VENDORS = {
    "stealth": "a stealth model's lab is undisclosed by definition",
}


def norm(family: str) -> str:
    """Compare families as identifiers: "K3 " and "k3" are one family, as are
    "routed unknown" and "routed-unknown"."""
    return re.sub(r"[\s_]+", "-", str(family).strip().casefold())


# Spellings a CLI might read as a model flag that this parser does not take apart
# ("-mKimi-K3", "--model Kimi-K3" as one element, "-m=X"). Rather than guess which one
# the CLI honours, their presence makes the pin ambiguous.
UNPARSED_PIN = re.compile(r"^(-m\S|-m\s|--model\s)")


def pinned_models(argv) -> list[str]:
    """Every model named by -m/--model (or --model=) in argv. An unparsed spelling
    counts as a second, unknowable pin, so resolve() refuses the lane."""
    out, it = [], iter(argv)
    for a in it:
        if a in MODEL_FLAGS:
            out.append(next(it, ""))
        elif a.startswith(("--model=", "-m=")):
            out.append(a.split("=", 1)[1])
        elif UNPARSED_PIN.match(a):
            out.append(f"<unparsed {a!r}>")
    return out


def _split(model: str) -> tuple[str, str]:
    m = norm(model)
    return (m.split("/", 1)[0] if "/" in m else ""), m.rsplit("/", 1)[-1]


def unresolvable(model: str) -> str | None:
    """Why this id can never resolve to a family, or None."""
    vendor, tail = _split(model)
    if vendor in UNRESOLVABLE_VENDORS:
        return UNRESOLVABLE_VENDORS[vendor]
    for pat, why in UNRESOLVABLE:
        if re.match(pat, tail):
            return why
    return None


def model_family(model: str) -> str:
    vendor, tail = _split(model)
    if tail in ROUTED_ALIASES:
        return ROUTED
    if unresolvable(model):
        return UNKNOWN
    for pat, fam in MODEL_FAMILIES:
        if re.match(pat, tail):
            return fam
    return UNKNOWN


@dataclasses.dataclass(frozen=True)
class Resolution:
    family: str              # a concrete family, ROUTED, or UNKNOWN
    model: str | None
    why: str


def resolve(h: "Harness") -> Resolution:
    """The family a harness can be SHOWN to run, from its argv -- not its label."""
    declared = norm(h.family)
    pins = pinned_models(h.argv)
    model = pins[-1] if pins else None
    if declared == ROUTED:
        return Resolution(ROUTED, model, "declared routed")
    if len({norm(x) for x in pins}) > 1 or any(x.startswith("<unparsed") for x in pins):
        return Resolution(UNKNOWN, model, f"argv pins several models {pins}")
    if model is None:
        return Resolution(UNKNOWN, None,
                          f"no model pinned in argv; {h.argv[0]} runs whatever its config "
                          f"defaults to, so the declared family {h.family!r} is a claim only")
    fam = model_family(model)
    if fam == ROUTED:
        return Resolution(ROUTED, model, f"pin {model!r} is a routed alias")
    if fam == UNKNOWN:
        why = unresolvable(model)
        return Resolution(UNKNOWN, model, f"pin {model!r}: {why}" if why
                          else f"pin {model!r} is not in MODEL_FAMILIES")
    if fam != declared:
        return Resolution(UNKNOWN, model,
                          f"declared {h.family!r} but pin {model!r} is family {fam!r}")
    return Resolution(fam, model, "pinned")


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
        notes="UNPINNED: runs config.toml's default_model, so its family cannot be "
              "established and it is refused on either side of a verification. "
              "Appends reasoning bullets and a session-resume line to stdout. Has "
              "aborted before composing a final answer — give it a compose deadline."),
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
        notes="ROUTED: serves several families per request, so it is refused on "
              "either side of a verification. Worker use only. Promotional balance "
              "— falls back to PAID billing once exhausted."),
}

# The default Overseer family. Anything Delta authors is checked by something else.
# This is only a DEFAULT: an Op constructed with an explicit `overseer=` uses that
# instead, and `--check --overseer` does the same. It does not constrain such runs.
OVERSEER_FAMILY = "anthropic"




class IndependenceError(RuntimeError):
    """Raised when a dispatch would let a family check its own work."""

class RoutedFamilyError(IndependenceError):
    """One side is served by a router; its family is decided per request."""

class UnknownFamilyError(IndependenceError):
    """One side's family cannot be established from its pinned model."""

class SameFamilyError(IndependenceError):
    """Both sides resolve to one family."""

class OverseerFamilyError(IndependenceError):
    """The verifier shares the orchestrator's family."""

class RecordMismatchError(IndependenceError):
    """The job record and the roster disagree about what produced the work."""


def _alternatives(target_family: str, overseer: str) -> list[str]:
    return sorted(x.name for x in ROSTER.values()
                  if (f := resolve(x).family) not in (ROUTED, UNKNOWN, target_family, norm(overseer)))


def vet(verifier: Harness, target: Harness | str, overseer: str = OVERSEER_FAMILY) -> None:
    """THE independence rule. Raises if `verifier` may not check work produced by
    `target` (a Harness, resolved here) or by a named family. dispatch() and the
    --check CLI both call this; there is no second copy to drift (v0.1's --check
    allowed pairs dispatch refused). It never accepts a pre-built Resolution: a
    caller-supplied one bypassed the family table (luna confirmation read)."""
    v = resolve(verifier)
    if isinstance(target, Harness):
        t = resolve(target)
    elif not isinstance(target, str):
        raise TypeError(f"vet() target must be a Harness or a family name, not {type(target).__name__}")
    else:
        # A family given as a string must be one the table can produce. An arbitrary
        # string ("made-up-family", a typo) is not an established family, and v0.2's
        # first cut allowed it (gpt-5.6-luna cross-family read, 2026-10-09).
        f = norm(target)
        known = {norm(x) for _, x in MODEL_FAMILIES}
        t = Resolution(f if f in known | {ROUTED} else UNKNOWN, None,
                       "given" if f in known | {ROUTED} else
                       f"family {target!r} is not one MODEL_FAMILIES can produce")
    if ROUTED in (v.family, t.family):
        side = "verifier" if v.family == ROUTED else "target"
        raise RoutedFamilyError(
            f"{verifier.name} (family={v.family}) verifying family={t.family}: the {side} is "
            f"served by a routed alias, so its family is unknowable at dispatch and independence "
            f"cannot be established. Use a lane pinned to one model.")
    if UNKNOWN in (v.family, t.family):
        why = v.why if v.family == UNKNOWN else t.why
        raise UnknownFamilyError(
            f"{verifier.name} (family={v.family}) verifying family={t.family}: independence cannot "
            f"be established — {why}. Pin a model the family table recognises.")
    if v.family == t.family:
        raise SameFamilyError(
            f"{verifier.name} (family={v.family}) may not verify family={t.family}. A family "
            f"cannot check its own output — same training, same blind spots. "
            f"Choose from: {_alternatives(t.family, overseer)}")
    if v.family == norm(overseer):
        raise OverseerFamilyError(
            f"{verifier.name} shares the Overseer's family ({norm(overseer)}); it cannot "
            f"provide independent verification of this operation's work.")


# Exact-capability probes, keyed by binary. A probe passes only on POSITIVE
# recognition of expected content -- never on exit status alone: qodercli prints
# "Not logged in" to STDOUT, sometimes with exit 0 (Decatron R5c, 2026-08-09).
# Unrecognised output is a FAIL. "{model}" means: some line's first token is exactly
# the lane's pinned model, i.e. the account's live catalog still offers the pin (the
# stale Qwen3.8-Max-Preview pin would have failed here). Recipes were checked against
# the installed CLIs on 2026-10-08.
PROBE_RECIPES: dict[str, list[tuple[str, list[str], str]]] = {
    "devin":    [("auth", ["devin", "auth", "status"], r"(?m)^Logged in\b"),
                 ("model-offered", ["devin", "models", "list"], "{model}")],
    "qodercli": [("model-offered", ["qodercli", "--list-models"], "{model}")],
    "agy":      [("model-offered", ["agy", "models"], "{model}")],
}
NOT_LOGGED_IN = re.compile(r"not logged in|please (run )?/?login|unauthori[sz]ed|sign in", re.I)


def run_isolated(argv: list[str], timeout: float) -> tuple[int, str, str, bool]:
    """Run non-interactively in its own process group: stdin closed, no TTY, and on
    timeout the WHOLE group is killed. subprocess.run(timeout=) kills only the direct
    child, and agent CLIs spawn workers (U-2)."""
    try:
        p = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as e:
        return -1, "", f"{type(e).__name__}: {e}", False
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out or "", err or "", False
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            out, err = p.communicate(timeout=10)
        except subprocess.TimeoutExpired as e:      # a descendant escaped the group and holds the pipe
            dec = lambda b: b.decode(errors="replace") if isinstance(b, bytes) else (b or "")
            out, err = dec(e.stdout), dec(e.stderr) + "\n[quorum] pipe still held after group kill"
        return -9, out or "", (err or "") + f"\n[quorum] timeout after {timeout}s; process group killed", True


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
        self.attempts: dict[str, list[dict]] = {}     # superseded jobs, on retry
        self.probes: dict[str, list[dict]] = {}
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
        while (alt := p.with_name(f"{p.stem}.v{n}{p.suffix}")).exists():
            n += 1
        return alt

    @staticmethod
    def _sha(p: pathlib.Path) -> str:
        return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "—"

    # -- probes ------------------------------------------------------------
    def probe(self, names: list[str], need_web: bool = False,
              allow_declared: bool = False, timeout: float = 60) -> dict[str, bool]:
        """Exercise what each harness is about to be asked to do.

        A capability listed in documentation is a claim. An operation was once
        planned around a harness's web access that it did not have, and a liveness
        check once green-lit a CLI that printed "Not logged in" with exit 0.

        Each result is a dated observation under a recorded invocation (argv hash,
        binary fingerprint), passing only on positive recognition of expected
        content. A harness with no exercise recipe is DECLARED-ONLY and fails
        unless `allow_declared=True`. `need_web` is still checked against the
        roster's declaration, and is logged as declared, not exercised.
        """
        results = {}
        for name in names:
            h = ROSTER[name]
            rec = {"at": self._now(), "harness": name, "argv_sha": hashlib.sha256(
                json.dumps(list(h.argv)).encode()).hexdigest()[:16], "checks": []}
            self.probes.setdefault(name, []).append(rec)
            ok, why = self._probe_one(h, rec, need_web, allow_declared, timeout)
            results[name] = ok
            self.log("quorum", "—", "PROBE",
                     f"{name}: {'PASS' if ok else 'FAIL'} — {why} "
                     f"(family={resolve(h).family}, cost={h.cost}, argv {rec['argv_sha']}, "
                     f"bin {rec.get('bin', '—')})")
        return results

    def _probe_one(self, h: Harness, rec: dict, need_web: bool,
                   allow_declared: bool, timeout: float) -> tuple[bool, str]:
        path = shutil.which(h.argv[0])
        if path is None:
            return False, "binary not found"
        st = os.stat(path)
        rec["bin"] = hashlib.sha256(f"{path}:{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:12]
        if need_web and not h.web:
            return False, f"web required, roster records no web access. {h.notes}"
        recipes = PROBE_RECIPES.get(h.argv[0]) or PROBE_RECIPES.get(os.path.basename(h.argv[0]))
        if not recipes:
            return allow_declared, ("no exercise recipe for this binary — DECLARED-ONLY"
                                    + ("" if allow_declared else "; refused (allow_declared=False)"))
        model = resolve(h).model
        for kind, argv, expect in recipes:
            code, out, err, timed_out = run_isolated(argv, timeout)
            text = out + "\n" + err
            if timed_out:
                cls = "timeout"
            elif code != 0:                         # never ok, whatever the text says
                cls = "not-logged-in" if NOT_LOGGED_IN.search(text) else "nonzero-exit"
            elif expect == "{model}":
                cls = ("ok" if model and any(ln.split()[:1] == [model] for ln in out.splitlines())
                       else "not-logged-in" if NOT_LOGGED_IN.search(text) else "model-not-offered"
                       if out.strip() else "unrecognised")
            else:
                cls = ("ok" if re.search(expect, out) else "not-logged-in"
                       if NOT_LOGGED_IN.search(text) else "unrecognised")
            rec["checks"].append({"kind": kind, "exit": code, "class": cls,
                                  "out_sha": hashlib.sha256(text.encode()).hexdigest()[:16]})
            if cls != "ok":
                return False, f"{kind}: {cls} (exit {code})" + (
                    f" — pin {model!r} not in the live catalog" if cls == "model-not-offered" else "")
        web = "; web DECLARED (not exercised)" if need_web else ""
        return True, "exercised: " + ", ".join(c["kind"] for c in rec["checks"]) + web

    # -- dispatch ----------------------------------------------------------
    def dispatch(self, label: str, prompt: str, harness: str,
                 verifies: str | None = None, role: str = "worker",
                 min_bytes: int = 200, timeout: float = 3600, retry: bool = False) -> dict:
        """Run one agent. Refuses same-family verification.

        `verifies` names a previous job. When set, this dispatch is a check on
        that job's output and the independence rule is enforced here rather
        than trusted to whoever wrote the plan.

        `min_bytes` is the floor below which output counts as BLOCKED. Set it to
        the smallest plausible real answer for THIS dispatch — a one-word probe
        and a research report do not share a threshold.

        A label is used once. `retry=True` supersedes the label's job (kept in
        `self.attempts`); prompt and output files are versioned, never overwritten.
        """
        h = ROSTER[harness]
        res = resolve(h)

        if verifies is not None:
            target = self.jobs.get(verifies)
            if target is None:
                raise KeyError(f"cannot verify unknown job {verifies!r}")
            # Re-resolve the producer from the roster rather than trusting the job's
            # stored `family` field, and refuse if the two disagree: a record edited
            # after the fact, or a lane re-pointed between dispatches, is not the
            # thing that produced the work (grok-4.7, 2026-10-08).
            th = ROSTER.get(target.get("harness", ""))
            if th is None:
                raise RecordMismatchError(
                    f"job {verifies!r} names harness {target.get('harness')!r}, which is not in "
                    f"the roster; what produced it cannot be established.")
            tres = resolve(th)
            if norm(target.get("family", "")) != tres.family or \
                    tuple(target.get("argv") or ()) != th.argv:
                raise RecordMismatchError(
                    f"job {verifies!r} records family={target.get('family')!r} but its harness "
                    f"{th.name} now resolves to {tres.family!r} ({tres.why}); the record and the "
                    f"roster disagree, so independence cannot be established.")
            outp = pathlib.Path(target.get("output", ""))
            if not target.get("sha") or not outp.is_file() or self._sha(outp) != target["sha"]:
                raise RecordMismatchError(
                    f"job {verifies!r}'s output is missing or changed since it was produced "
                    f"(recorded sha {target.get('sha')!r}); the verifier would not be checking "
                    f"the recorded work.")
            vet(h, th, self.overseer)

        if label in self.jobs:
            if not retry:
                raise ValueError(
                    f"label {label!r} already has a job; pass retry=True to supersede it "
                    f"(the earlier job is kept in op.attempts) or use a new label (U-3)")
            self.attempts.setdefault(label, []).append(self.jobs[label])

        pp = self._path(f"prompts/prompt-{label}.md")   # write-once, like outputs (U-3)
        pp.write_text(prompt)
        out = self._path(f"{label}-output.md")

        self.log(harness, pp.name, "DISPATCH",
                 f"{role} '{label}'"
                 + (f" (retry #{len(self.attempts[label])})" if retry and label in self.attempts else "")
                 + (f" verifying '{verifies}' (cross-family {tres.family}→{res.family})" if verifies else "")
                 + ("" if res.family not in (ROUTED, UNKNOWN) or verifies
                    else f" — family {res.family}: {res.why}; this output cannot be verified "
                         f"by an independence-checked dispatch")
                 + f". Output → {out.name}.", self._sha(pp))

        t0 = time.time()
        code, stdout, err, timed_out = run_isolated(h.command(prompt), timeout)
        out.write_text(stdout)
        err = err[-400:]

        size = out.stat().st_size
        # Expected output length varies by three orders of magnitude between a
        # one-word probe and a research report, so the floor is per-dispatch.
        # A fixed threshold flagged a correct 14-byte answer as BLOCKED during
        # this module's own smoke test — a verification tool that cries wolf
        # gets ignored, which is the failure mode it exists to prevent.
        # A timeout's partial output is not an answer, however long it is: it would
        # otherwise become a job a later dispatch could verify (grok-47 read).
        blocked = size < min_bytes or timed_out
        job = {"label": label, "harness": harness, "family": res.family, "model": res.model,
               "argv": list(h.argv), "sha": self._sha(out), "role": role, "timed_out": timed_out,
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
    ap.add_argument("--check", nargs=2, metavar=("HARNESS", "TARGET"),
                    help="would HARNESS be allowed to verify output from TARGET "
                         "(a roster harness name, or a family)? Same rule as dispatch.")
    ap.add_argument("--overseer", default=OVERSEER_FAMILY,
                    help=f"orchestrator family for --check (default {OVERSEER_FAMILY})")
    a = ap.parse_args()

    if a.check:
        name, tgt = a.check
        h = ROSTER.get(name)
        if not h:
            print(f"unknown harness {name!r}"); return 2
        target = ROSTER[tgt] if tgt in ROSTER else tgt
        tfam = resolve(target).family if isinstance(target, Harness) else norm(tgt)
        try:
            vet(h, target, a.overseer)
        except IndependenceError as e:
            print(f"{name} (family={resolve(h).family}) verifying {tfam}: REFUSED "
                  f"[{type(e).__name__}]\n  {e}")
            return 1
        print(f"{name} (family={resolve(h).family}) verifying {tfam}: ALLOWED")
        return 0

    rows = [(h.name, h.family, (r := resolve(h)).family, r.model or "—",
             "yes" if h.web else "NO", "yes" if h.shell else "no", h.cost, h.notes)
            for h in ROSTER.values()]
    head = ("name", "declared", "resolved", "pin", "web", "shell", "cost")
    w = [max(len(head[i]), *(len(r[i]) for r in rows)) + 2 for i in range(len(head))]
    print(f"quorum {__version__} — harness roster (empirical; probe-derived)\n")
    print("".join(f"{head[i]:<{w[i]}}" for i in range(len(head))) + "notes")
    print("-" * (sum(w) + 40))
    for r in rows:
        print("".join(f"{r[i]:<{w[i]}}" for i in range(len(head))) + r[7][:60])
    print(f"\noverseer family: {OVERSEER_FAMILY} (default) — excluded from verifying this operation's work")
    print(f"resolved {ROUTED} / {UNKNOWN}: refused on either side of a verification")
    return 0


if __name__ == "__main__":
    sys.exit(main())
