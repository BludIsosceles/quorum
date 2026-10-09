#!/usr/bin/env python3
"""The guard must be watched refusing -- and allowing -- something real.

v1 of this suite (2026-07-28) passed 5/5 on a host with NO agent binaries: its
allowed-path case dispatched a live lane, quorum swallowed the FileNotFoundError,
and the test only asserted that no IndependenceError was raised. Reported by the
Decatron desk (U-1) and reproduced by Delta. v2 ran a stub harness and asserted
the dispatch actually ran.

v2 still accepted ANY IndependenceError as proof of the rule it named, so a
routed lane relabelled into the same family passed "routed alias refused" for the
wrong reason, and no test put a routed lane on the PRODUCING side (grok-4.7
cross-family read, 2026-10-08). v3: every refusal asserts the exact rule that
fired; each attack from that read is a test; ROSTER and the family table are
deep-restored; no test dispatches a real agent CLI.
"""
import copy, os, pathlib, subprocess, sys, tempfile, shutil, time, dataclasses
QDIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(QDIR))
import quorum
from quorum import (Op, ROSTER, IndependenceError, OVERSEER_FAMILY, ROUTED, UNKNOWN, Harness,
                    RoutedFamilyError, UnknownFamilyError, SameFamilyError,
                    OverseerFamilyError, RecordMismatchError, MODEL_FAMILIES, PROBE_RECIPES,
                    resolve, vet)

FAILS = []
def check(name, fn):
    saved = copy.deepcopy(ROSTER)                          # U-6 + grok S3: objects, not just keys
    saved_tab, saved_rec = list(MODEL_FAMILIES), copy.deepcopy(PROBE_RECIPES)
    saved_alias = set(quorum.ROUTED_ALIASES)
    try:
        fn(); print(f"  PASS  {name}")
    except AssertionError as e:
        FAILS.append(name); print(f"  FAIL  {name}: {e}")
    except Exception as e:                                 # U-6: a crash is a recorded failure
        FAILS.append(name); print(f"  FAIL  {name}: unexpected {type(e).__name__}: {e}")
    finally:
        ROSTER.clear(); ROSTER.update(saved)
        MODEL_FAMILIES[:] = saved_tab
        PROBE_RECIPES.clear(); PROBE_RECIPES.update(saved_rec)
        quorum.ROUTED_ALIASES.clear(); quorum.ROUTED_ALIASES.update(saved_alias)

def run(name, body):
    def wrapped():
        with tempfile.TemporaryDirectory() as root:      # U-6: always cleaned
            body(root)
    check(name, wrapped)

def stub(name, family, model, script="echo stub-dispatch-ok #{prompt}"):
    """A runnable lane: bash runs `script`; the trailing --model pin is what resolve()
    reads (bash -c ignores it as $0/$1)."""
    return Harness(name, family, ["bash", "-c", script, "--model", model],
                   web=False, shell=True, cost="free")

def setup(root):
    """Two pinned stub families, A and B. Returns an Op holding a real job 'w' by A."""
    MODEL_FAMILIES[:0] = [("stuba-", "stuba"), ("stubb-", "stubb")]
    ROSTER["a"] = stub("a", "stuba", "stuba-1")
    ROSTER["b"] = stub("b", "stubb", "stubb-1")
    o = Op("t", root=root)
    o.dispatch("w", "x", "a", min_bytes=1)
    return o

def refuses(exc, fn, msg):
    try:
        fn()
    except IndependenceError as e:
        assert type(e) is exc, f"{msg}: refused, but by {type(e).__name__}, not {exc.__name__}: {e}"
        return
    raise AssertionError(f"{msg}: ALLOWED")

# --- the allowed path is real -------------------------------------------------------------
def stub_is_runnable(root):
    assert shutil.which("bash"), "bash not found -- the allowed-path tests would be vacuous"

def cross_family_actually_dispatches(root):
    o = setup(root)
    j = o.dispatch("m", "x", "b", verifies="w", min_bytes=1)
    assert j["exit"] == 0, f"stub dispatch did not run (exit {j['exit']})"
    assert not j["blocked"] and j["bytes"] > 0, "stub dispatch produced nothing"
    assert "stub-dispatch-ok" in pathlib.Path(j["output"]).read_text(), "output is not the stub's"

# --- each rule, by name ------------------------------------------------------------------
def same_family_refused(root):
    o = setup(root); ROSTER["a2"] = stub("a2", "stuba", "stuba-2")
    refuses(SameFamilyError, lambda: o.dispatch("m", "x", "a2", verifies="w"), "stuba verifying stuba")

def same_family_ignores_case_and_space(root):
    o = setup(root); ROSTER["a3"] = stub("a3", " STUBA ", "STUBA-3")
    refuses(SameFamilyError, lambda: o.dispatch("m", "x", "a3", verifies="w"), "' STUBA ' verifying stuba")

def overseer_family_refused(root):
    o = setup(root); ROSTER["self"] = stub("self", OVERSEER_FAMILY, "claude-opus-5-5")
    refuses(OverseerFamilyError, lambda: o.dispatch("m", "x", "self", verifies="w"), "overseer family")

def explicit_overseer_is_used(root):
    o = setup(root); o.overseer = "stubb"
    refuses(OverseerFamilyError, lambda: o.dispatch("m", "x", "b", verifies="w"), "Op(overseer=stubb)")

def routed_alias_refused_as_verifier(root):
    o = setup(root)
    refuses(RoutedFamilyError, lambda: o.dispatch("m", "x", "qoder-ultimate", verifies="w"),
            "shipped qoder-ultimate as verifier")

def routed_alias_refused_as_producer(root):
    o = setup(root); ROSTER["r"] = stub("r", "stuba", "Ultimate")
    j = o.dispatch("rw", "x", "r", min_bytes=1)
    assert j["family"] == ROUTED, f"routed producer recorded as {j['family']!r}"
    refuses(RoutedFamilyError, lambda: o.dispatch("m", "x", "b", verifies="rw"), "verifying routed work")

def relabelled_routed_lane_still_routed(root):
    ROSTER["qoder-ultimate"] = dataclasses.replace(ROSTER["qoder-ultimate"], family="qwen")
    assert resolve(ROSTER["qoder-ultimate"]).family == ROUTED, "relabel to qwen hid the router"
    o = setup(root)
    refuses(RoutedFamilyError, lambda: o.dispatch("m", "x", "qoder-ultimate", verifies="w"), "relabelled")

def new_lane_on_routed_alias_refused(root):
    ROSTER["qoder-auto"] = Harness("qoder-auto", "qwen", ["qodercli", "-m", "Auto", "-p", "{prompt}"],
                                   web=True, shell=True, cost="free")
    o = setup(root)
    refuses(RoutedFamilyError, lambda: o.dispatch("m", "x", "qoder-auto", verifies="w"), "qoder -m Auto")

def routed_label_variants(root):
    for lab in ("routed-unknown ", "ROUTED-UNKNOWN", "routed unknown"):
        h = dataclasses.replace(ROSTER["qoder-ultimate"], family=lab)
        assert resolve(h).family == ROUTED, f"{lab!r} not treated as routed"

def argv_pin_cannot_be_edited(root):
    try:
        ROSTER["qoder"].argv[2] = "Ultimate"
        raise AssertionError("argv is mutable -- a pin can be retargeted under its label")
    except TypeError:
        pass

def unpinned_lane_refused(root):
    o = setup(root)
    refuses(UnknownFamilyError, lambda: o.dispatch("m", "x", "kimi", verifies="w"), "unpinned kimi")

def odd_pin_spellings_refused(root):
    for argv in (["x", "-mKimi-K3", "-m", "Qwen3.8-Max"], ["x", "-m", "Qwen3.8-Max", "--model Kimi-K3"],
                 ["x", "-m", "Qwen3.8-Max", "--model=Kimi-K3"], ["x", "-m", "Qwen3.8-Max", "-m", "GLM-5.3"]):
        r = resolve(Harness("o", "qwen", argv, True, True, "free"))
        assert r.family == UNKNOWN, f"{argv} resolved {r.family!r}"
    assert resolve(Harness("o", "qwen", ["x", "--max-output-tokens", "8", "-m", "Qwen3.8-Max"],
                           True, True, "free")).family == "qwen", "a non-model flag broke the pin"

def label_contradicting_pin_refused(root):
    o = setup(root); ROSTER["liar"] = stub("liar", "stubb", "stuba-9")   # says stubb, runs stuba
    refuses(UnknownFamilyError, lambda: o.dispatch("m", "x", "liar", verifies="w"), "label vs pin")

def unrecognised_model_refused(root):
    for mid in ("zephyr-7b", "nemotronx", "some/new-model", "gptx", "opus-x", "swe-xyz", "codexified"):
        assert quorum.model_family(mid) == UNKNOWN, f"{mid!r} defaulted to {quorum.model_family(mid)!r}"
    o = setup(root); ROSTER["new"] = stub("new", "zephyr", "zephyr-7b")
    refuses(UnknownFamilyError, lambda: o.dispatch("m", "x", "new", verifies="w"), "id not in table")

# Every pin the Decatron engine fielded on 2026-10-09 (decatron/lanes.json @49308b9),
# with the family it must resolve to. "gemini" for Gemma, "meta" for Llama/Muse and
# "openai" for gpt-oss are the lab rule, not the engine's labels.
FLEET = {
    "swe-1-7": "swe", "gemini-3.6-flash-high": "gemini", "Qwen3.8-Max": "qwen", "kimi-code/k3": "k3",
    "kimi-code/kimi-for-coding": "k3", "meta/llama-3.1-70b-instruct": "meta", "openai/gpt-oss-120b": "openai",
    "nvidia/nemotron-3-super-120b-a12b": "nemotron", "thinkingmachines/inkling": "inkling",
    "nvidia/nemotron-3-ultra-550b-a55b": "nemotron", "nvidia/nemotron-3-ultra-550b-a55b:free": "nemotron",
    "google/diffusiongemma-26b-a4b-it": "gemini", "nvidia/nemotron-3.5-lightning-30b-a3b": "nemotron",
    "meta/muse-glimmer-30b": "meta", "poolside/laguna-s-2.1:free": "laguna", "inception/mercury-2.5": "inception",
    "bytedance-seed/seed-1.6-flash": "seed", "bytedance-seed/seed-2-1-turbo": "seed", "gemma-4-31b-it": "gemini",
    "inclusionai/ling-3.0-flash": "ling", "upstage/solar-pro4": "solar", "amazon/nova-lite-v1": "nova",
    "xiaomi/mimo-v2.5": "mimo", "tencent/hy3": "hunyuan", "mistralai/mistral-large-4-0": "mistral",
    "claude-opus-5-5": "anthropic", "gpt-6-astra": "openai", "gpt-5.3-codex": "openai", "grok-4.7": "grok",
    "glm-5.3": "glm", "deepseek-v4-pro": "deepseek", "minimax-m3": "minimax", "Ultimate": ROUTED,
    "stealth/ox-alpha": UNKNOWN, "mistralai/mistral-nemotron": UNKNOWN,
}

def fleet_coverage(root):
    bad = {m: (quorum.model_family(m), f) for m, f in FLEET.items() if quorum.model_family(m) != f}
    assert not bad, f"fleet pins resolve wrongly: {bad}"

def unresolvable_ids_say_why(root):
    for m, word in (("stealth/ox-alpha", "undisclosed"), ("stealth/claude-opus-5-5", "undisclosed"),
                    ("mistralai/mistral-nemotron", "jointly")):
        r = resolve(Harness("x", "glm", ["x", "--model", m], True, True, "free"))
        assert r.family == UNKNOWN and word in r.why, (m, r)

def lab_rule_merges(root):
    for a, b in (("gemma-4-31b-it", "gemini-3.6-flash-high"), ("meta/muse-glimmer-30b", "meta/llama-3.1-70b-instruct"),
                 ("openai/gpt-oss-120b", "gpt-6-astra"), ("kimi-code/kimi-for-coding", "kimi-code/k3")):
        fa, fb = quorum.model_family(a), quorum.model_family(b)
        assert fa == fb != UNKNOWN, f"{a}={fa} vs {b}={fb}: one lab, two families"

def dash_m_equals_is_a_pin(root):
    assert resolve(Harness("x", "qwen", ["x", "-m=Qwen3.8-Max"], True, True, "free")).family == "qwen"
    assert resolve(Harness("x", "qwen", ["x", "-m", "Qwen3.8-Max", "-m=Kimi-K3"], True, True, "free")).family == UNKNOWN

def timed_out_output_is_blocked(root):
    ROSTER["chatty"] = stub("chatty", "stuba", "stuba-1", "yes partial-answer | head -c 5000; sleep 120 #{prompt}")
    MODEL_FAMILIES[:0] = [("stuba-", "stuba")]
    j = Op("t7", root=root).dispatch("c", "x", "chatty", timeout=2, min_bytes=10)
    assert j["timed_out"] and j["bytes"] >= 10, j
    assert j["blocked"], "a timed-out partial answer over min_bytes was not blocked"

# --- the record is not trusted over the roster -------------------------------------------
def edited_job_record_refused(root):
    o = setup(root); o.jobs["w"]["family"] = "stubc"                       # record says stubc
    refuses(RecordMismatchError, lambda: o.dispatch("m", "x", "b", verifies="w"), "edited family field")

def handwritten_routed_record_refused(root):
    o = setup(root)
    o.jobs["u"] = {"label": "u", "harness": "qoder-ultimate", "family": "qwen", "role": "worker"}
    refuses(RecordMismatchError, lambda: o.dispatch("m", "x", "b", verifies="u"), "routed job relabelled qwen")

def producer_repointed_between_dispatches(root):
    o = setup(root); ROSTER["a"] = stub("a", "stuba", "stuba-2")        # same label, new pin
    refuses(RecordMismatchError, lambda: o.dispatch("m", "x", "b", verifies="w"), "lane re-pointed")

def forged_record_without_argv_refused(root):
    o = setup(root); j = dict(o.jobs["w"]); del j["argv"]; o.jobs["f"] = j
    refuses(RecordMismatchError, lambda: o.dispatch("m", "x", "b", verifies="f"), "record with no argv")

def output_changed_after_production_refused(root):
    o = setup(root); pathlib.Path(o.jobs["w"]["output"]).write_text("swapped")
    refuses(RecordMismatchError, lambda: o.dispatch("m", "x", "b", verifies="w"), "output swapped")

def unknown_target_refused(root):
    try:
        setup(root).dispatch("m", "x", "b", verifies="nope")
        raise AssertionError("verifying an unknown job was allowed")
    except KeyError:
        pass

# --- the CLI gate is the same gate -------------------------------------------------------
def check_cli_matches_dispatch(root):
    def cli(*a):
        return subprocess.run([sys.executable, str(QDIR / "quorum.py"), "--check", *a],
                              capture_output=True, text=True).returncode
    cases = {("qoder-ultimate", "k3"): 1, ("qoder-ultimate", "qwen"): 1, ("devin", "routed-unknown"): 1,
             ("kimi", "swe"): 1, ("devin", "K3 "): 0, ("devin", "SWE"): 1, ("qoder", "agy"): 0,
             ("qoder", "qoder-ultimate"): 1, ("devin", "gemini"): 0,
             ("qoder", "made-up-family"): 1, ("qoder", "qwen3"): 1,
             ("qoder", "anthropic"): 0}       # Claude-authored work checked by Qwen: the point
    bad = {k: (cli(*k), v) for k, v in cases.items() if cli(*k) != v}
    assert not bad, f"--check disagrees with the rule: {bad}"
    assert subprocess.run([sys.executable, str(QDIR / "quorum.py"), "--check", "devin", "qwen",
                           "--overseer", "swe"], capture_output=True).returncode == 1, "--overseer ignored"

def vet_takes_no_prebuilt_resolution(root):
    try:
        vet(ROSTER["qoder"], quorum.Resolution("made-up-family", None, "forged"))
        raise AssertionError("a caller-built Resolution was trusted")
    except TypeError:
        pass

def suggestions_are_usable(root):
    try:
        vet(ROSTER["qoder"], "qwen")
        raise AssertionError("qwen verifying qwen allowed")
    except SameFamilyError as e:
        for bad in ("qoder-ultimate", "kimi", "'qoder'"):
            assert bad not in str(e), f"suggests {bad}, which would be refused: {e}"

# --- artifacts, labels, process control --------------------------------------------------
def write_once_holds(root):
    o = Op("t2", root=root)
    a = o._path("x-output.md"); a.write_text("first")
    assert o._path("x-output.md") != a, "second artifact would overwrite the first"
    b = o._path("prompts/p.md"); b.write_text("first")
    assert o._path("prompts/p.md").parent == b.parent != o.dir, "versioned prompt left prompts/"

def duplicate_label_refused_retry_versions(root):
    o = setup(root)
    try:
        o.dispatch("w", "y", "a", min_bytes=1)
        raise AssertionError("label reuse silently replaced the job")
    except ValueError:
        pass
    j = o.dispatch("w", "second prompt", "a", min_bytes=1, retry=True)
    assert len(o.attempts["w"]) == 1, "superseded job not kept"
    prompts = sorted(p.name for p in (o.dir / "prompts").iterdir())
    assert prompts == ["prompt-w.md", "prompt-w.v2.md"], f"prompt overwritten: {prompts}"
    assert o.attempts["w"][0]["output"] != j["output"], "output path reused"

def timeout_kills_process_group(root):
    pidf = pathlib.Path(root) / "child.pid"
    ROSTER["slow"] = stub("slow", "stuba", "stuba-1", f"sleep 120 & echo $! > {pidf}; wait #{{prompt}}")
    o = Op("t3", root=root); t0 = time.time()
    j = o.dispatch("s", "x", "slow", timeout=2, min_bytes=1)
    assert time.time() - t0 < 30, "timeout did not return promptly"
    assert j["timed_out"], "timeout not recorded"
    pid = int(pidf.read_text())
    for _ in range(20):
        try:
            os.kill(pid, 0); time.sleep(0.1)
        except ProcessLookupError:
            return
    raise AssertionError(f"grandchild {pid} survived the timeout")

def stdin_is_closed(root):
    # Asserts WHAT stdin is, not merely that `cat` returned: when the suite itself
    # runs with stdin on /dev/null, an inherited stdin also returns at once, and the
    # v3 form of this test passed with the protection removed.
    ROSTER["cat"] = stub("cat", "stuba", "stuba-1",
                         "echo stdin=$(readlink /proc/$$/fd/0); cat; echo read-done #{prompt}")
    # Point THIS process's stdin at an open pipe, so an inherited stdin would be
    # that pipe (and `cat` would block) whatever stdin the suite was started with.
    r, w = os.pipe(); saved = os.dup(0); os.dup2(r, 0)
    try:
        j = Op("t4", root=root).dispatch("c", "x", "cat", timeout=10, min_bytes=1)
    finally:
        os.dup2(saved, 0); os.close(saved); os.close(r); os.close(w)
    out = pathlib.Path(j["output"]).read_text()
    assert not j["timed_out"] and "read-done" in out, "a dispatch reading stdin hung"
    if pathlib.Path("/proc/self/fd/0").exists():
        assert "stdin=/dev/null" in out, f"child stdin was not /dev/null: {out.splitlines()[:1]}"

# --- probes recognise, they do not trust exit 0 ------------------------------------------
def probe_needs_positive_recognition(root):
    fake = pathlib.Path(root) / "fakecli"
    fake.write_text("#!/bin/sh\necho 'Not logged in · Please run /login'\nexit 0\n"); fake.chmod(0o755)
    ROSTER["f"] = Harness("f", "stuba", [str(fake), "--model", "stuba-1"], True, True, "free")
    MODEL_FAMILIES[:0] = [("stuba-", "stuba")]
    PROBE_RECIPES[str(fake)] = [("model-offered", [str(fake)], "{model}")]
    o = Op("t5", root=root)
    assert o.probe(["f"]) == {"f": False}, "exit 0 + 'Not logged in' passed the probe"
    assert o.probes["f"][-1]["checks"][0]["class"] == "not-logged-in", o.probes["f"]
    fake.write_text("#!/bin/sh\necho MODEL\necho stuba-1\n")
    assert o.probe(["f"]) == {"f": True}, "a live catalog offering the pin failed"
    fake.write_text("#!/bin/sh\necho MODEL\necho stuba-2\n")
    assert o.probe(["f"]) == {"f": False}, "a stale pin passed"
    fake.write_text("#!/bin/sh\necho MODEL\necho stuba-1\nexit 3\n")
    assert o.probe(["f"]) == {"f": False}, "recognised text with a failing exit passed"
    fake.write_text("#!/bin/sh\necho stuba-1\necho 'not logged in'\nexit 3\n")
    assert o.probe(["f"]) == {"f": False}, "nonzero exit passed because login text was present"

def probe_without_recipe_is_declared_only(root):
    ROSTER["s"] = stub("s", "stuba", "stuba-1")
    o = Op("t6", root=root)
    assert o.probe(["s"]) == {"s": False}, "no-recipe lane passed as if exercised"
    assert o.probe(["s"], allow_declared=True) == {"s": True}, "allow_declared ignored"

print("quorum guard tests (v3)")
for n, f in [
    ("stub harness is runnable",                    stub_is_runnable),
    ("cross-family dispatch ACTUALLY RUNS",         cross_family_actually_dispatches),
    ("same family refused [SameFamily]",            same_family_refused),
    ("family compare ignores case/space",           same_family_ignores_case_and_space),
    ("overseer family refused [Overseer]",          overseer_family_refused),
    ("explicit Op overseer is the one enforced",    explicit_overseer_is_used),
    ("routed alias refused as verifier [Routed]",   routed_alias_refused_as_verifier),
    ("routed alias refused as PRODUCER [Routed]",   routed_alias_refused_as_producer),
    ("relabelled routed lane still routed",         relabelled_routed_lane_still_routed),
    ("new lane on a routed alias refused",          new_lane_on_routed_alias_refused),
    ("routed label variants normalised",            routed_label_variants),
    ("argv pin cannot be edited in place",          argv_pin_cannot_be_edited),
    ("unpinned lane refused [Unknown]",             unpinned_lane_refused),
    ("odd pin spellings make the pin unknown",      odd_pin_spellings_refused),
    ("label contradicting pin refused [Unknown]",   label_contradicting_pin_refused),
    ("unrecognised model id refused [Unknown]",     unrecognised_model_refused),
    ("engine fleet pins all resolve as ruled",      fleet_coverage),
    ("unresolvable ids say why",                    unresolvable_ids_say_why),
    ("one lab is one family",                       lab_rule_merges),
    ("-m=ID is a pin",                              dash_m_equals_is_a_pin),
    ("timed-out partial output is BLOCKED",         timed_out_output_is_blocked),
    ("edited job record refused [Mismatch]",        edited_job_record_refused),
    ("hand-written routed record refused",          handwritten_routed_record_refused),
    ("producer re-pointed between dispatches",      producer_repointed_between_dispatches),
    ("forged record without argv refused",          forged_record_without_argv_refused),
    ("output changed after production refused",     output_changed_after_production_refused),
    ("unknown verify target refused",               unknown_target_refused),
    ("--check is the dispatch rule",                check_cli_matches_dispatch),
    ("vet() takes no pre-built Resolution",         vet_takes_no_prebuilt_resolution),
    ("refusal suggestions are usable",              suggestions_are_usable),
    ("write-once path never reused",                write_once_holds),
    ("duplicate label refused; retry versions",     duplicate_label_refused_retry_versions),
    ("timeout kills the process group",             timeout_kills_process_group),
    ("stdin closed: no dispatch hangs on input",    stdin_is_closed),
    ("probe: exit 0 is not a pass",                 probe_needs_positive_recognition),
    ("probe: no recipe = declared only",            probe_without_recipe_is_declared_only),
]:
    run(n, f)
print(f"\n{'ALL PASS' if not FAILS else 'FAILURES: ' + ', '.join(FAILS)}")
sys.exit(1 if FAILS else 0)
