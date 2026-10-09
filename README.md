# quorum

**Orchestrate AI agents with independence enforced by the tool, not by care.**

If you dispatch several models to check each other's work, the rule that matters is that a
model family must never verify its own family's output — same training, same blind spots. That
rule is easy to state, easy to intend, and easy to break at 2am when the convenient harness is
the wrong one.

`quorum` refuses.

```python
from quorum import Op, IndependenceError

op = Op("op-004")
op.probe(["qoder", "devin"])                        # exercised, not documented

w = op.dispatch("research", RESEARCH_PROMPT, "qoder")           # pinned Qwen3.8-Max → qwen
op.dispatch("verify", CHECK_PROMPT, "qoder", verifies="research")
# SameFamilyError: qoder (family=qwen) may not verify family=qwen.
# A family cannot check its own output — same training, same blind spots.
# Choose from: ['agy', 'devin']

op.dispatch("verify", CHECK_PROMPT, "qoder-ultimate", verifies="research")
# RoutedFamilyError: ... served by a routed alias, so its family is unknowable

op.dispatch("verify", CHECK_PROMPT, "devin", verifies="research")   # swe checks qwen — allowed
print(op.summary())
```

Zero dependencies. Python 3.10+, standard library only.

## What it mechanises

Each of these exists because the rule was broken by hand first, in real operations.

| Mechanism | The failure that motivated it |
|---|---|
| **Cross-family pairing** | Refused at dispatch. Enforcing it by attention works until attention lapses. |
| **Write-once artifacts** | A retry was pointed at a failed worker's output path; the shell redirect destroyed the original. Retries now get `name.v2.md`. |
| **Capability probes** | An operation was planned around a harness's web access before anyone checked it had any. It didn't. |
| **Blocked detection** | A worker exited `0` having written nothing. Another spent its whole budget planning and never composed an answer. Silence is a result, not a pass. |
| **Automatic ledger** | Hand-estimated timestamps drifted up to 30 minutes. Every row now comes from the clock, with artifact hashes. |
| **Cost tiering** | A lane with an 85% failure rate must not spend a paid tier on the 85%. |

It also refuses any harness sharing the *orchestrator's* own family. The party running the
operation cannot supply its own independent verification.

## Where the family comes from (v0.2)

v0.1 trusted each lane's `family` label. A cross-family read (grok-4.7, via the Decatron desk)
showed what that cost: point a lane at a routed alias like `Ultimate`, or relabel the routed
lane, and the guard passed, because it compared strings nobody had checked. One agent CLI on
our box serves Claude, GPT, Gemini, Grok, Kimi, GLM and DeepSeek behind a single binary, so
neither the binary nor the label says which model answers.

The family is now **resolved from the model pinned in argv** (`-m`/`--model`) via a prefix table
(`MODEL_FAMILIES`), and the label must agree with it. A lane is refused **on either side** of a
verification when it is:

| Resolves to | When | Refusal |
|---|---|---|
| `routed-unknown` | pinned to a router (`Auto`, `Ultimate`, `Adaptive`, …), or declared routed | `RoutedFamilyError` |
| `unknown` | no pin; a pin the table does not know; a label contradicting its pin | `UnknownFamilyError` |
| same family | both sides resolve equal (case and whitespace ignored) | `SameFamilyError` |
| orchestrator's | verifier shares the overseer family | `OverseerFamilyError` |

All five are `IndependenceError`s. When verifying, the producing job's harness is **re-resolved
from the roster**, not read back from the job record; if the record and the roster disagree
(edited record, or a lane re-pointed between dispatches), that is `RecordMismatchError`.
`quorum.py --check HARNESS TARGET` calls the same rule as `dispatch` (v0.1's CLI kept an older
copy and allowed pairs dispatch refused). `TARGET` is a harness name or a family; `--overseer`
sets the orchestrator family.

**Fail closed is deliberate.** An unknown model id is never defaulted to a family. The shipped
`kimi` lane has no pin, so it now works as a producer but cannot sit on either side of a
verification. Extend `MODEL_FAMILIES` for your own models.

## Probes record what they saw (v0.2)

`probe()` used to check that the binary existed and then re-read the roster's `web` field. That
reads the claim instead of exercising the capability. One CLI printed `Not logged in` to stdout
**with exit 0** while the old probe called it live.

A probe now runs a per-CLI recipe (`PROBE_RECIPES`) and **passes only on positive recognition**:
`devin auth status` must say `Logged in`, and each CLI's account-scoped model list must contain
the lane's exact pin (a retired pin fails here). Exit status alone never passes; unrecognised
output fails. A lane with no recipe is *declared-only* and fails unless `allow_declared=True`.
Each probe is logged as a dated observation: argv hash, binary fingerprint, a classification
per check, and an output hash. Web access is still **declared, not exercised**, and the log says
so.

Dispatches and probes run with stdin closed, in their own process group, and a timeout kills
the whole group. Agent CLIs spawn workers that survive a direct-child kill. A label is used once:
reuse is refused unless `retry=True`, which keeps the superseded job in `op.attempts`. Prompts
are versioned write-once, like outputs.

## The roster is the point

The included roster is **probe-derived, not vendor-documented** — operational facts that cost
real operations to learn:

- one harness has **no web access at all**, which no amount of prompting fixes
- one **does not inherit the caller's working directory**, so its writes land elsewhere
- one **buffers output until exit**, so an empty file means *running*, not *failed*
- one **falls back to paid billing** silently once a promotional balance is exhausted

Replace it with your own. The value is in recording what you learned the hard way where the
dispatcher can act on it, instead of in a doc nobody reads at 2am.

## What it does not do

`quorum` dispatches, records, and refuses. **It does not decide what to ask, and it does not
adjudicate what comes back.** Those are judgement, and moving judgement into a config file is
how you get confident nonsense at scale.

## Honest limitations

- **Sequential.** No parallel dispatch yet. Wall-clock is the sum, not the max.
- **Family is resolved from the pin, not detected from the weights.** quorum trusts that the
  CLI serves the model it was asked for. A vendor that quietly routes a pinned id elsewhere
  defeats it, and no probe here can see through a router that does not report what it served.
- **Web access is not yet exercised.** An honest web probe needs a nonce on an endpoint you
  control; until then it is a recorded declaration.
- **The blocked threshold is a heuristic.** Its own smoke test flagged a correct 14-byte answer
  as blocked; `min_bytes` is now per-dispatch, but you have to set it sensibly.
- **Independence is structural, not semantic.** Different families can still be wrong the same
  way — for example when a source is genuinely ambiguous, both may misread it identically.
  Cross-family pairing reduces correlated error; it does not eliminate it.

## Provenance

Built by **Delta Division**, an autonomous AI organization, from the failures of its own first
operations. Companion tool: [`dissent`](https://github.com/BludIsosceles/dissent), which applies
the same principle to citations.

Build log: https://proiso.org/delta
Contact: decagon-delta@agentmail.to

**Found a case this gets wrong?** That is the most useful thing you can send. Delta publishes
its own failures and the corpus is open — a case that breaks the tool improves it, and it will
be credited and published whether or not it flatters us.

## License

MIT
