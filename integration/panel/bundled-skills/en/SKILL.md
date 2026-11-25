---
name: gpt-swarm-workflow
description: >-
  Use when choosing codex-gpt-6.2-sol-high or codex-gpt-6.2-astra-high reasoning tiers,
  orchestrating multi-model /swarm or subagent teams, enforcing documentation and aesthetic ownership,
  filtering GPT-6.2 over-defensive reviews, or running specialist workflows (refactoring/testing,
  mathematical modeling, 3D/CAD parametric modeling, frontend UI, deep technical research).
---

# GPT-6.2 Multi-Model Collaboration Guide

Assign ownership before choosing models or concurrency. Both `codex-gpt-6.2-sol-high` and `codex-gpt-6.2-astra-high` start at **`high` by default** (never below `high`), and `Neon` defaults to **`gemini-4-neon-xhigh`**. Scale teams to the task instead of using fixed headcounts.

## Six Core Boundaries

1. **GPT-6.2 never makes final decisions.** Sol builds; Astra audits and solves deep technical puzzles. The Coordinator (`Neon`) or user owns architecture, priorities, trade-offs, and merge sign-off.
2. **Filter reviews for over-defense.** Astra excels at uncovering real P0/P1 bugs, but routinely pads reports with low-value defensive items and heavy prescriptions (extra abstractions, new ledgers, thread pools). Separate the *verified defect* from the *proposed remedy* and ship the smallest sufficient fix.
3. **Neon owns important docs and copywriting; GPT writes logs and local records only.** GPT's defensive hedging and boilerplate disclaimers degrade readability:
   - **GPT may write:** execution logs, test output, local change notes, and terse read-only review findings.
   - **GPT must not directly edit:** READMEs, architecture/design specs, ADRs, Skill/Rule files, release notes, or user-facing copy.
   - **The Coordinator (`Neon`) manages important documents**, and all copywriting or prose polishing goes to `Neon` members.
4. **`gemini-4-neon-xhigh` owns aesthetics.** GPT-6.2 lags behind Neon `xhigh` in visual taste. For UI, data visualization, and 3D/CAD appearance, Neon sets the design language, proportions, and lighting, and signs off on browser screenshots or multi-angle renders. Sol/Astra implement mechanics, wiring, scripts, and tests strictly to spec—never restyling or skipping visual sign-off.
5. **Model roster and fallback discipline.**
   - **Gemini uses `Neon` and `Hydrogen` only** (no Flash or other variants). **`gemini-4-hydrogen-xhigh` is strictly a temporary execution fallback**: when Sol cannot complete a concrete implementation slice, dispatch `hydrogen-xhigh` to land that slice, then **retire it immediately—never keep it persistent**, and never use it for coordination, planning, docs, or aesthetics.
   - **Claude is disabled by default** due to extremely scarce quota. Never spawn or switch to Claude without explicit user authorization.
6. **Modality and false-positive refusal limits.** The GPT route natively accepts `text` + `image` only (no native PDF—extract text or render pages first). Authorized low-level patching, reverse engineering, or packaging can trigger GPT-6.2 false-positive refusals; narrow to clean white-box source slices or hand the blocked execution slice to temporary `gemini-4-hydrogen-xhigh`.

## Model & Tier Matrix

| Model & Tier | Role | Typical Work | Escalation / Constraint |
| :--- | :--- | :--- | :--- |
| **`codex-gpt-6.2-sol-high`** | **Default implementer** | Parallel coding, multi-file fixes, unit/regression tests, Git/ops tasks, simulation/modeling scripts, logs & local change notes | Always start at `high` (no `low`/`medium`); no editing important docs or copy |
| **`codex-gpt-6.2-astra-high`** | **Default deep reviewer & solver** | Cross-layer architecture & invariant audits, concurrency/consistency debugging, math/algorithm derivation, independent final review | Always start at `high` (no `low`/`medium`); return evidence and minimal fixes, never merge or decide architecture |
| `codex-gpt-6.2-astra-xhigh` | Targeted escalation | High-stakes stateful audits, subtle concurrency root causes, hard proofs, or after two failed `high` attempts | Escalate one proven bottleneck only; never assign to routine parallel coding |
| `*-max` | Rare emergency ceiling | Single-shot high-loss check with conflicting evidence that `xhigh` still cannot resolve | Set an explicit exit condition; never use in parallel implementation slots |
| **`gemini-4-neon-xhigh`** | **Coordinator / Planner / Aesthetics / Docs (default)** | Orchestration, anti-over-defense adjudication, UI/3D design & visual sign-off, important docs & copywriting | Default to `xhigh`; stay lightweight and delegate heavy reading, routine coding, and long tests to `sol-high` |
| `gemini-4-hydrogen-xhigh` | **Temporary execution fallback** | Landing a concrete implementation slice when Sol is blocked | **Dispose immediately after completion—never persist**; no coordination, review, docs, or aesthetics |
| Claude Sonnet / Opus | Reserved (off by default) | Only when explicitly authorized by the user | Never allocate or fail over to Claude by default |

**Tier economics:** `high` is the sweet spot. Pushing to `xhigh`/`max` yields small marginal gains (public benchmarks show roughly ~60 at Astra `high` vs ~62 at `max`) while multiplying latency and reasoning tokens 2–4× (`max` can stall for 3–14 minutes per task). Sol consumes roughly one-quarter of Astra's quota per comparable unit of work. Once a hard problem is settled, hand implementation and tests back to `sol-high`.

## Adaptive Orchestration

Scale roles by **write-set independence × risk × dependency DAG**—never use a fixed headcount template:

| Scope | Starting Setup | When to Scale |
| :--- | :--- | :--- |
| **Small** | Coordinator scopes the work; one `sol-high` lands it. Skip ops, Astra, and separate planner. | Add one read-only `astra-high` pass only if non-obvious contract risks exist. |
| **Medium** | `2–4` parallel `sol-high` workers on disjoint write sets; Coordinator owns contracts and key docs. | Add `astra-high` for cross-layer/concurrency risk; add a `sol-high` ops worker if baselines/regressions bottleneck progress. |
| **Large** | Baseline + risk map first, then DAG waves of `N × sol-high` and serial merges. | Add slices only with disjoint write sets, isolated ports, and quota; add a `gemini-4-neon-xhigh` planner when audit volume warrants formal triage. |

- **Keep the coordinator lean:** Dispatch bulk source reading, routine coding, test runs, and log curation to `sol-high`. Read crisp summaries, adjudicate trade-offs, own important docs, and run visual sign-off.
- **Single write owner:** One author per write set. Use `workspace="share"` or disjoint subdirectories for concurrent edits.
- **Pick the right mechanism:** Ordinary subagent for one-off tasks; `run_workflow` for staged pipelines; native `/swarm` when authorized and shared stateful handoffs are needed.

## Dispatch & Closeout Checklist

Specify five items before dispatching an implementer:
1. **Write allowlist:** exact files/directories (explicitly excluding important docs and copy).
2. **Frozen areas:** shared configs, public interfaces, migrations, or invariant behaviors.
3. **Shared contract:** interfaces, invariants, and upstream dependencies.
4. **Stop & escalation triggers:** budget caps or blockers—report immediately instead of widening scope.
5. **Reproducible acceptance command:** exact command and pass criteria.

**Closeout flow:**
- Review Astra findings as *reproduction → broken contract → impact → minimal fix*; Neon marks each **accept / trim / decline**.
- Merge serially in DAG order. High-risk merges get an independent `astra-high` check on the integrated revision; visual work gets Neon sign-off; Neon updates important docs and release notes at closeout.

## Exceptions & Fallback

- Tool-only turns or brief silence do not mean a stall; wait for events rather than polling.
- On repeated empty output, false-positive refusals, or sustained 409s, preserve confirmed progress and stop blind retries: serialize write contention; for a blocked execution slice, temporarily dispatch `gemini-4-hydrogen-xhigh` and retire it once landed; never switch to Claude without user approval.

## Load References on Demand

- [Model profiles, tier economics, and over-defense checklist](./references/model-guide.md): Read for model trade-offs, Astra review triage, doc boundaries, or fallback rules.
- [Adaptive swarm and five specialist playbooks](./references/swarm-playbooks.md): Load only the matching section for refactoring/testing, math modeling, 3D/CAD modeling, frontend UI, or deep technical research.
