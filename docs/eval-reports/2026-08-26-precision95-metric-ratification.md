# Metric ratification — the precision ≥ 0.95 push (programme ticket P0-2)

> ### OPERATOR SIGN-OFF REQUIRED — THIS RATIFICATION IS A DRAFT UNTIL SIGNED
>
> Signed: ____________________ (operator, GitHub `@MKamel1`)  Date: ____________
>
> Until the operator signs above, every statement in this document is a DRAFT proposal, not a
> ratified gate. Nothing here is self-signed. The PROJECT-STATUS tuning-decision entry is recorded
> by the programme orchestrator only AFTER sign-off — deliberately not in this branch.

Written 2026-08-26, branch `NB-P02-metric-ratify`, Wave-P0 ticket P0-2 of the
[precision-0.95 programme](../superpowers/plans/2026-08-25-precision95-programme.md). Docs only: no
fixture edited, no pipeline code touched, no retrieval re-run. The definitions below are **quoted
verbatim** from [NB-B0 §2](2026-08-25-nb-b0-benchmark-audit.md) ("§2 The metric definition for THIS
push"), the audit that derived each bound with shown achievability arithmetic; the two-arm statement
is quoted verbatim from the programme plan §1. This addendum adds no new measurement and introduces
no number not already committed in B0 or the plan.

---

## 1. The frozen metric definitions (quoted VERBATIM from NB-B0 §2.1)

The following two tables and their lead-in headings are reproduced character-for-character from
NB-B0 §2.1. They are what the operator's "precision ≥ 0.95" attaches to. The achievability bounds
behind each cell were derived in B0 §1.2(b)/(c) and are NOT restated here — this document ratifies;
B0 derives.

**Primary gate — paper-level P@1, answerable arm, shipped fused config:**

| fixture | achievability bound (arithmetic) | verdict |
|---|---|---|
| gt_wmr | max = R@10 = 69/70 = 0.9857; bar = 67/70; current 64/70 → Δ +3 | **feasible in shipped shape** |
| ver84 | max = R@10 = 61/68 = 0.8971 < 0.95 | **infeasible until the fusion-eviction question (X-F) resolves**; dense-only variant bound 66/68 = 0.9706, bar 65/68, current 54/68 → feasible conditional on X-F + X-O converting +11 |

**Secondary gate — block-level P@1, text-answerable arm, pool depth stated:**

| fixture | bound @K=32 / K=128 (perfect reranker) | verdict |
|---|---|---|
| gt_wmr | 63/65 = 0.9692 / 65/65 = 1.0000 | **feasible now** (all-arm too: 0.9545 @K=32) |
| ver84 | 56/60 = 0.9333 @K=128 (all-arm 0.8750) | **infeasible as bounded today** — one item short at K=128 |

Reading rules inherited from the audit, binding here: scored per fixture, never averaged; every
count carries its denominator; the absent arm stays reported, never blended.

---

## 2. Binding qualifier rule

Every number reported under this ratification carries the five-part qualifier **{metric, fixture,
arm (all/text), pool depth, config}**. A number without all five parts is not quotable as a
programme result. Example form: `block-P@1 / gt_wmr / text-arm / K=32 / fused w=0.7`.

## 3. Retired as gates (with reasons)

| candidate gate | reason retired |
|---|---|
| Paper-level P@10 | Structural ~1/k wall with single-gold-per-question fixtures and k-distinct results (flaw owned in the priority-baseline report §1; lessons §7.2 requires reachability arithmetic at freeze time — the bound tables above ARE that arithmetic) |
| Full-population precision before abstention exists | With no abstention mechanism every absent query returns a confident top-10, capping perfect-retrieval full-population precision at N_answerable/N_total: **gt_wmr 70/82 = 0.8537, ver84 68/82 = 0.8293** (B0 §1.2(d)) — structurally below 0.95 regardless of retrieval quality |
| Answer-level precision | No trend-grade instrument exists yet: the amended-rubric judge re-run is clean-delivery after the NUMCTX fix, but its adverse findings record single-pass sampling variance dominating run-to-run flips; seeded/repeated sampling is owed first |

## 4. Two-arm statement (quoted VERBATIM from the programme plan §1, items 1–2)

> 1. **Single-shot retrieval cannot reach 0.95 on ver84 all-arm. This is proven arithmetic, not
>    pessimism**: a perfect reranker over today's pools and extraction caps block-P@1 at 0.8750
>    all-arm / 0.9333 text-arm @K=128, and paper-P@1 in the shipped fused config at 0.8971
>    (B0 §1.2). Any plan that promises otherwise is lying.
> 2. **GT-WMR already clears the bar once citation honesty is counted**: member-block citation takes
>    its passage hit-rate to 95.5% with monotone-zero risk (X-C §2). That is real and cheap, but it is
>    a citation/metric-honesty fix — it must never be presented as a retrieval improvement.

Plan §1 item 3 adds the three-legged path: (a) citation honesty (QW-1 landed); (b) upstream structural
changes that move the bound itself — the ver84 text-arm crosses 0.95 exactly when ONE of the four
non-vision unexposed-at-K=128 D/E items becomes exposed (57/60 = 0.95; two make it comfortable); and
(c) agentic capability against purpose-built multi-hop GT (P0-3/SB-2).

## 5. Scope of this addendum

Once signed: names the instruments the 0.95 claim is measured against; binds the qualifier rule;
retires the listed candidates as gates programme-wide. NOT in effect: any change to fixtures,
retrieval code, or serving config; any abstention or confidence threshold (those carry their own
pre-committed criteria in NB-A1/NB-C1/C2 records — C1 DROPPED, C2 DEAD); any claim that these two
metrics are the only honest precision measures — they are the ratified ones FOR THIS PROGRAMME.

*Provenance note: predecessor dispatch timed out at 3600 s after writing §1 and the tables above;
orchestrator verified the quotes against B0 §2.1 verbatim and appended §2–§5 to complete ticket
P0-2 commit scope.*
