# NB-A1 — abstention signal-source design doc (resolves the A-series fork)

> **STUB.** This document is committed empty before any real work (programme plan §2 global
> constraint 1: commit 1 is a stub; every green step commits after). It will be filled with the
> candidate-signal-source designs in subsequent numbered commits. No abstention mechanism,
> threshold, or prompt change ships from this ticket — design + feasibility measurement only.

Ticket: NB-A1, `docs/superpowers/plans/2026-08-24-next-build-programme.md` §4 Wave 3. Input
verdict it resolves: `2026-08-25-nb-d3-abstention-census.md` ("no separation found" across
17 features × both fixtures). Deliverable: a design doc for NEW abstention signal sources,
each explicitly NOT promised to work, each with a falsification criterion stated before any
build, a cheap feasibility measurement someone could run next, and its failure mode.

Planned sections:

- §0 Inputs and framing (what D3 ruled out, what it did not)
- §1 Candidate signal sources (3–5, chosen and justified), per candidate:
  mechanism sketch · why the D3 null does not rule it out (or does) · pre-committed
  falsification criterion · cheap feasibility measurement · failure mode
- §2 Recommendation ordering (which candidate to falsify first and why)
- Method notes

Status: not started.
