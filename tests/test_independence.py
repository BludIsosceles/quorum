#!/usr/bin/env python3
"""The guard must be watched refusing something, or it is not a guard.

External brief (2026-07-28): "A constraint that is not applied produces plausible
output, which is why it survives review." quorum's entire value proposition is
that the tool refuses rather than the operator remembering, and until now nothing
verified the refusal actually fires. This closes that.
"""
import pathlib, sys, tempfile
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from quorum import Op, ROSTER, IndependenceError, OVERSEER_FAMILY

FAILS = []
def check(name, fn):
    try:
        fn(); print(f"  PASS  {name}")
    except AssertionError as e:
        FAILS.append(name); print(f"  FAIL  {name}: {e}")

tmp = tempfile.mkdtemp()

def _op():
    o = Op("t", root=tmp)
    o.jobs["w"] = {"label": "w", "family": "k3", "harness": "kimi", "role": "worker"}
    return o

def same_family_refused():
    o = _op()
    try:
        o.dispatch("m", "x", "kimi", verifies="w")
        raise AssertionError("k3 was ALLOWED to verify k3 — the guard did not fire")
    except IndependenceError:
        pass

def cross_family_allowed_past_guard():
    """devin (swe) checking k3 must pass the guard. It will then really dispatch,
    so we only assert the guard did not raise."""
    o = _op()
    try:
        o.dispatch("m2", "Reply with one word: OK", "devin", verifies="w", min_bytes=1)
    except IndependenceError as e:
        raise AssertionError(f"cross-family wrongly refused: {e}")

def overseer_family_refused():
    o = _op()
    H = type(ROSTER["devin"])
    ROSTER["self"] = H("self", OVERSEER_FAMILY, ["true"], True, True, "paid")
    try:
        o.dispatch("m3", "x", "self", verifies="w")
        raise AssertionError("the orchestrator's OWN family was allowed to verify its work")
    except IndependenceError:
        pass

def unknown_target_refused():
    o = _op()
    try:
        o.dispatch("m4", "x", "devin", verifies="nonexistent")
        raise AssertionError("verifying an unknown job was allowed")
    except KeyError:
        pass

def write_once_holds():
    o = Op("t2", root=tmp)
    a = o._path("x-output.md"); a.write_text("first")
    b = o._path("x-output.md")
    if a == b:
        raise AssertionError("second artifact would OVERWRITE the first")

print("quorum guard tests")
check("same family refused",                 same_family_refused)
check("orchestrator's own family refused",   overseer_family_refused)
check("unknown verify target refused",       unknown_target_refused)
check("write-once path never reused",        write_once_holds)
check("cross-family passes the guard",       cross_family_allowed_past_guard)
print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
