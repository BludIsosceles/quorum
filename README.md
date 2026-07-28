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
op.probe(["kimi", "devin"], need_web=True)          # capability, not documentation

w = op.dispatch("research", RESEARCH_PROMPT, "kimi")            # k3 family
op.dispatch("verify", CHECK_PROMPT, "kimi", verifies="research")
# IndependenceError: kimi (family=k3) may not verify research (family=k3).
# A family cannot check its own output — same training, same blind spots.
# Choose from: ['agy', 'devin', 'qoder', 'qoder-ultimate']

op.dispatch("verify", CHECK_PROMPT, "devin", verifies="research")   # swe checks k3 — allowed
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
- **`family` is declared, not detected.** Mislabel a harness and the guarantee is void.
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
