# Adaptive Swarms and Five Specialist Playbooks

Load only the section relevant to the current task. Scale headcount to disjoint write sets, dependencies, and risk—never lock into a fixed roster.

## 1. General Adaptive Swarm

### Dynamic Role Sizing

| Scope | Implementation | Ops / Review | Coordination / Planning / Docs |
| :--- | :--- | :--- | :--- |
| **Small** (single write set, low risk) | One `sol-high` | Skip; add one read-only `astra-high` pass only for non-obvious risks | Coordinator (`Neon`) scopes, closes out, and updates key docs |
| **Medium** (`2–4` disjoint sets) | `2–4 × sol-high` in DAG waves | Add `sol-high` ops if baselines/regressions bottleneck; add `astra-high` for cross-layer risk | Coordinator owns contracts, review triage, and key docs; keep independent final check for high-impact merges |
| **Large** (multi-module, multi-wave) | `N × sol-high` for ready disjoint sets only | Dedicated ops + domain-sharded read-only `astra-high` (`xhigh` only on proven bottlenecks) | Add a `gemini-4-neon-xhigh` planner for heavy audit triage; Coordinator retains key doc ownership |

**Concurrency cap** equals the tightest constraint among ready disjoint write sets, isolated ports/test DBs, quota, and regression cost. Serialize unsettled contracts or overlapping writes.

### Standard Protocol

1. **Contract first:** Pin baseline, public interfaces, write allowlists, frozen files, and acceptance commands before dispatch.
2. **Isolate writes:** Use `workspace="share"` or strictly disjoint subdirectories for concurrent writers, with isolated ports and temp paths.
3. **Keep the board crisp:** Workers report `status | touched paths | commands & results | open risks`. One owner maintains the run log; **key doc updates always return to the Coordinator (`Neon`)**.
4. **Temporary fallback SOP:** If `sol-high` stalls repeatedly, hits a false-positive refusal, or encounters route failure, preserve confirmed patches and stop blind retries. Temporarily dispatch `gemini-4-hydrogen-xhigh` to land that slice, then retire it immediately. Never use Claude without explicit user approval.
5. **Serial merge & verification:** Merge serially in DAG order; run full regression + independent `astra-high` check on the integrated revision for high-risk work; run Neon visual sign-off for visual tasks; Neon finishes key doc updates.

---

## 2. Five Specialist Playbooks

### 1. Large Codebase Refactoring, Full Testing, and Performance Tuning

- **Best for:** Cross-module refactors, test suite repair, performance work, and broad bug triage.
- **Adaptive setup:** `1–6` active workers scaled to disjoint modules: optional `sol-high` ops + read-only `astra-high` (`xhigh` only on hard stateful bottlenecks) + `N × sol-high` implementers; Neon owns triage, slicing, and key docs.
- **Flow & gates:**
  1. **Baseline & risk map:** Ops isolates a working copy/baseline commit and captures test + perf benchmarks (can run alongside read-only risk mapping).
  2. **Evidence audit:** `astra-high` audits cross-layer invariants, concurrency, and persistence read-only, reporting reproductions and minimal remedies.
  3. **Anti-over-defense slicing:** Neon trims overbuilt proposals into zero-overlap slices; `N × sol-high` land failing tests, minimal fixes, and green suites (logs only, no key docs).
  4. **Serial merge & final check:** Coordinator merges serially; independent `astra-high` checks stale out-of-order writes, memory spikes, identity drift, and perf methodology; Neon writes release/doc updates after full green gates.

### 2. Mathematical Modeling, Simulation, and Research Experiments

- **Best for:** Solvers, Monte Carlo runs, parameter sweeps, ablations, and statistical validation.
- **Adaptive setup:** `1–5` active workers: Neon pins problem framing, metrics, and narrative; `astra-high` (`xhigh` for tough proofs) handles derivations and rigor audits; `N × sol-high` implement solvers and experiment scripts.
- **Flow & gates:**
  1. **Problem & assumptions:** Neon locks objectives, units, acceptable assumptions, seeds, and train/eval isolation.
  2. **Derivation:** Astra writes formulas, boundary conditions, numerical stability checks, and leakage checks, separating proofs from heuristics.
  3. **Parallel simulation:** `N × sol-high` build solvers, sweeps, and ablations in isolated output dirs, preserving configs, seeds, and raw outputs.
  4. **Reproducibility & write-up:** Independent `astra-high` reruns pinned seeds and extreme cases. For publication plots and report prose, **Neon approves visual styling and authors the core narrative**; Sol writes plotting and aggregation scripts only.

### 3. 3D/CAD Parametric Modeling and Visualization (Blender / OpenSCAD / WebGL)

- **Best for:** Parametric parts/assemblies, procedural meshes, product visuals, and WebGL viewers.
- **Adaptive setup:** `1–6` active workers: **`gemini-4-neon-xhigh` owns all form and visual direction**; `N × sol-high` script subassemblies and automated render rigs; `astra-high` audits geometry and math.
- **Flow & gates:**
  1. **Visual & engineering contracts:** Neon sets proportions, silhouette, materials, lighting, cameras, and reference angles; engineering locks units, axes, origin, and tolerances.
  2. **Component builds:** `N × sol-high` author OpenSCAD / Blender Python / Three.js scripts, exports, and multi-angle render pipelines without altering visual proportions or styling.
  3. **Geometry audit:** `astra-high` verifies manifoldness/watertightness, tolerances, clearance/interference, coordinate transforms, and shader math.
  4. **Multi-angle visual gate:** Every iteration, Neon inspects front/side/oblique and detail renders of the same scene and directs refinements. Passing mesh export never substitutes for visual sign-off.

### 4. Frontend UI Prototyping and Interaction Development

- **Best for:** UI prototypes, design systems, interactive flows, responsive layouts, and accessibility upgrades.
- **Adaptive setup:** `1–5` active workers: **`gemini-4-neon-xhigh` owns design language, microcopy, and browser sign-off**; `N × sol-high` implement state, API wiring, layouts, and E2E tests; `astra-high` audits complex state risk.
- **Flow & gates:**
  1. **Design first:** Neon freezes typography, palette, spacing, restrained motion, UI copy, design tokens, and component contracts.
  2. **Implement to spec:** `N × sol-high` build state, API integration, responsive CSS, accessibility, and automated UI tests—no unauthorized restyling or copy rewrites.
  3. **Risk review:** `astra-high` hunts state races, out-of-order async updates, memory leaks, and edge inputs.
  4. **Dual gate:** After automated interaction and viewport tests pass, Neon personally reviews representative viewports, states, and motion in the live browser.

### 5. Deep Technical Research, Authorized Reverse Analysis, and Architecture Review

- **Best for:** Tech evaluations, protocol/source deep dives, migrations, and architecture reviews.
- **Adaptive setup:** `1–5` read-only researchers split by domain/angle: `sol-high` gathers source/doc/log facts; `astra-high` traces core protocols and invariants; **Neon synthesizes and authors the final ADR and review doc**.
- **Flow & gates:**
  1. **Slice the questions:** Partition non-overlapping read-only tracks by module, alternative, or protocol layer with clear decision questions.
  2. **Parallel evidence collection:** Sol returns traceable file/version citations and excerpts; Astra maps state machines, edge invariants, and counterevidence.
  3. **Refusal handling:** If authorized binary, unpacking, or patch analysis hits a GPT false-positive refusal, stop arguing—split out pure white-box source analysis or temporarily run the blocked script/check via `gemini-4-hydrogen-xhigh`, then retire Hydrogen immediately.
  4. **Decision write-up:** Neon reconciles conflicting findings, strips over-engineering, and personally writes a crisp trade-off matrix and actionable ADR (context, options, choice, impact, migration, rollback).
