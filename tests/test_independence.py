#!/usr/bin/env python3
"""The guard must be watched refusing -- and allowing -- something real.

v1 of this suite (2026-07-28) passed 5/5 on a host with NO agent binaries: its
allowed-path case dispatched a live lane, quorum swallowed the FileNotFoundError,
and the test only asserted that no IndependenceError was raised. Reported by the
Decatron desk (U-1) and reproduced by Delta. A dispatch that could not happen was
counted as a pass -- the exact "silence is a result, not a pass" failure quorum's
own header names. v2: the allowed path runs a stub harness and asserts the
dispatch actually ran; any unexpected exception is a recorded FAIL (U-6); ROSTER
is restored after each mutation; temp dirs are cleaned.
"""
import pathlib, sys, tempfile, shutil
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import quorum
from quorum import Op, ROSTER, IndependenceError, OVERSEER_FAMILY, ROUTED, Harness

FAILS = []
def check(name, fn):
    saved = dict(ROSTER)
    try:
        fn(); print(f"  PASS  {name}")
    except AssertionError as e:
        FAILS.append(name); print(f"  FAIL  {name}: {e}")
    except Exception as e:                       # U-6: a crash is a recorded failure
        FAILS.append(name); print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")
    finally:
        ROSTER.clear(); ROSTER.update(saved)     # U-6: no leaked lanes

STUB = Harness("stub", "stubfam", ["bash", "-c", "echo stub-dispatch-ok #{prompt}"],
               web=False, shell=True, cost="free")

def _op(root):
    o = Op("t", root=root)
    o.jobs["w"] = {"label": "w", "family": "k3", "harness": "kimi", "role": "worker"}
    return o

def run(name, body):
    def wrapped():
        with tempfile.TemporaryDirectory() as root:  # U-6: always cleaned
            body(root)
    check(name, wrapped)

def stub_is_runnable(root):
    assert shutil.which("bash"), "bash not found -- the stub cannot run, so the allowed-path test would be vacuous"

def same_family_refused(root):
    try:
        _op(root).dispatch("m", "x", "kimi", verifies="w")
        raise AssertionError("k3 was ALLOWED to verify k3")
    except IndependenceError:
        pass

def overseer_family_refused(root):
    ROSTER["self"] = Harness("self", OVERSEER_FAMILY, ["true"], True, True, "paid")
    try:
        _op(root).dispatch("m", "x", "self", verifies="w")
        raise AssertionError("the orchestrator's own family was allowed to verify")
    except IndependenceError:
        pass

def routed_alias_refused(root):
    try:
        _op(root).dispatch("m", "x", "qoder-ultimate", verifies="w")
        raise AssertionError("a routed alias was allowed to verify; its family is unknowable")
    except IndependenceError:
        pass

def unknown_target_refused(root):
    try:
        _op(root).dispatch("m", "x", "devin", verifies="nope")
        raise AssertionError("verifying an unknown job was allowed")
    except KeyError:
        pass

def write_once_holds(root):
    o = Op("t2", root=root)
    a = o._path("x-output.md"); a.write_text("first")
    assert o._path("x-output.md") != a, "second artifact would overwrite the first"

def cross_family_actually_dispatches(root):
    ROSTER["stub"] = STUB
    j = _op(root).dispatch("m", "x", "stub", verifies="w", min_bytes=1)
    assert j["exit"] == 0, f"stub dispatch did not run (exit {j['exit']})"
    assert not j["blocked"] and j["bytes"] > 0, "stub dispatch produced nothing"
    assert "stub-dispatch-ok" in pathlib.Path(j["output"]).read_text(), "output is not the stub's"

print("quorum guard tests (v2)")
run("stub harness is runnable",               stub_is_runnable)
run("same family refused",                    same_family_refused)
run("orchestrator's own family refused",      overseer_family_refused)
run("routed alias refused as verifier",       routed_alias_refused)
run("unknown verify target refused",          unknown_target_refused)
run("write-once path never reused",           write_once_holds)
run("cross-family dispatch ACTUALLY RUNS",    cross_family_actually_dispatches)
print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
