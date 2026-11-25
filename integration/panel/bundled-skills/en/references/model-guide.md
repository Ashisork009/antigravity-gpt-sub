# Model Profiles, Tier Economics, and Over-Defense Checklist

## 1. Role Capability Matrix

| Dimension | `codex-gpt-6.2-sol-high` | `codex-gpt-6.2-astra-high` | `gemini-4-neon-xhigh` | `gemini-4-hydrogen-xhigh` |
| :--- | :--- | :--- | :--- | :--- |
| **Core role** | Default implementer | Default deep reviewer & hard problem solver | Coordinator, adjudicator, aesthetics & key docs owner | **Temporary execution fallback** (disposable) |
| **Strengths** | Multi-file delivery, unit/regression tests, ops/Git scripts, simulation & modeling code | Cross-layer invariants, concurrency/state bugs, math derivation, independent final review | Architectural trade-offs, stripping over-defense, UI/3D taste, crisp docs & copy | Unblocking a specific implementation slice when Sol stalls |
| **Limits & off-limits** | Not for final architecture or visual taste; **defensive prose ruins docs—no important docs or copy** | Prone to over-defense and heavy prescriptions; **no important docs or copy** | High-value quota/context—keep off routine grunt work | Execution fallback only—**retire once done**, never persist or own coordination/docs/aesthetics |
| **Context & cache** | 1M context; ~90%–97% KV cache hit on stable shared prefixes | 1M context; strong prefix caching; budget output room for deep derivations | Lightweight coordination and editorial control | Short-lived, focused slice delivery |
| **Relative quota** | ~1× (primary workhorse) | ~4× (spend on decisive questions) | Scarce—stay lean | Shares Gemini quota; use temporarily only |

> **Claude policy:** Claude quota is extremely scarce—**never use by default**. Only allocate or fail over to Claude when explicitly authorized by the user.

## 2. Default Tiers & Cost–Quality Curve

- **Sol & Astra start at `high`:** `low` and `medium` frequently miss implicit contracts and trigger rework that costs more than running `high` from the start. Never use GPT tiers below `high`.
- **Neon defaults to `gemini-4-neon-xhigh`:** `xhigh` is Neon's optimal tier for orchestration, triage, visual taste, and editorial prose—use it by default for the Coordinator, planners, and doc/visual owners.
- **`high` is the cost–quality inflection point:** External tracking (e.g., Artificial Analysis) and real-world runs show sharp diminishing returns past `high` (illustrative: Astra `high` ~60 vs `max` ~62), while latency and reasoning tokens climb 2–4× and `max` can take several to 14+ minutes on a single task.
- **When to escalate:**
  - `astra-high → astra-xhigh`: Only for high-stakes stateful audits, subtle concurrency root causes, difficult proofs, or two consecutive failed `high` attempts. Frame one concrete question with reproduction evidence.
  - `astra-xhigh → max`: Rare ceiling for high-loss conflicting evidence that `xhigh` still couldn't close. Always set a deadline and exit condition; never assign to parallel implementers.
  - **Once the hard question is solved, hand implementation and tests back to `sol-high`.**

## 3. Documentation & Copywriting Boundary

GPT-6.2 naturally pads human-facing writing with legalistic hedges, redundant caveats, and defensive disclaimers that hurt clarity and voice. Enforce a strict split:

- **GPT may write:**
  - Execution logs, raw benchmark/test outputs, and reproduction notes;
  - Local change records for a slice (touched files, commands run, pass/fail outcomes);
  - Terse read-only review findings aimed at the Coordinator, never direct reader prose.
- **`Neon` owns:**
  - **Important documents:** READMEs, architecture/design docs, ADRs, project standards, Skill/Rule specs, and release notes (managed by the Coordinator or delegated to Neon members);
  - **All copywriting:** product copy, UI microcopy, user-facing error messages, and final reports.

## 4. Over-Defense Filter: Six Review Checks

Even when Astra's P0/P1 detection is strong, roughly 15%–25% of recommendations are low-value and around a third of valid fixes propose heavier machinery than needed. Filter every item with six checks:

1. **Demand reproduction over speculation.** Require a failing test, concrete repro, or tight invariant proof. Unevidenced defensive worries do not block merges.
2. **Split defect from remedy.** Accept the bug while rejecting an oversized cure—local defects rarely justify new abstraction layers, state machines, separate ledgers, or thread pools.
3. **Protect existing contracts.** Decline recommendations that break compatibility tests, wire formats, or downstream expectations unless the Coordinator approves a contract change.
4. **Ship the smallest sufficient fix.** Group or defer low-value P2s; prefer lightweight fixes (transactional checks, bounded retries, clean readiness signals) over architectural rewrites.
5. **Audit concurrency and resource regressions.** Independently verify out-of-order stale writes, peak memory spikes, identity drift, and batch rollback on the integrated code.
6. **Record every disposition.** Mark `accept / trim / decline` with a one-line rationale so later workers don't relitigate closed items.

## 5. Runtime Guardrails & Temporary Fallback

- **Native modalities:** The GPT route accepts `text` + `image` natively, not PDFs. Extract text or render pages to images before sending PDF content.
- **Visual sign-off:** Neon must inspect real browser screenshots or multi-angle 3D renders; green functional tests never replace visual review.
- **Temporary fallback when Sol cannot land a slice:** If `sol-high` hits a false-positive refusal, repeated stall, or route failure on a concrete implementation task, save confirmed progress and hand off a crisp context packet (baseline, write allowlist, contract, run commands) to **`gemini-4-hydrogen-xhigh`**. **Retire/kill Hydrogen as soon as that slice lands—never keep it persistent.**
- **One writer at a time:** Always transfer write ownership cleanly before resuming; never let two workers race on the same files.
